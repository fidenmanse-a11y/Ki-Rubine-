"""Server-side job queue.

Jobs are rows in the ``jobs`` table. A background thread in the API process
starts queued jobs as separate worker processes (respecting concurrency
limits), watches them, enforces timeouts and recovers after crashes.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import psutil
from sqlalchemy import func, select

from ..config import REPO_ROOT, get_settings
from ..db import Job, ModelVersion, audit, session_scope, utcnow

log = logging.getLogger("rubine.jobs")

ACTIVE = ("running", "pausing", "stopping")
OPEN = ("queued",) + ACTIVE
JOB_TYPES = {"synthetic", "build_dataset", "teacher", "train", "evaluate", "compare"}


class JobError(ValueError):
    pass


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def submit(job_type: str, params: dict) -> str:
    st = get_settings()
    if job_type not in JOB_TYPES:
        raise JobError("Unbekannter Jobtyp")
    with session_scope() as s:
        n_open = s.scalar(select(func.count()).select_from(Job).where(Job.status.in_(OPEN)))
        if n_open >= st.max_queued_jobs:
            raise JobError(f"Zu viele offene Jobs (max. {st.max_queued_jobs}).")
        if job_type == "train":
            busy = s.scalar(select(func.count()).select_from(Job).where(
                Job.type == "train", Job.status.in_(OPEN + ("paused",))))
            if busy:
                raise JobError("Es gibt bereits eine laufende oder pausierte Trainingsrunde.")
        job = Job(type=job_type, params=params, status="queued", message="Wartet in der Warteschlange")
        s.add(job)
        s.flush()
        audit(s, "job.submit", job=job.id, type=job_type)
        return job.id


def request_pause(job_id: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise JobError("Job nicht gefunden")
        if job.type != "train":
            raise JobError("Nur Trainingsjobs können pausiert werden.")
        if job.status != "running":
            raise JobError(f"Job ist nicht aktiv (Status {job.status}).")
        job.control, job.status, job.message = "pause", "pausing", "Pausiere beim nächsten Schritt …"
        audit(s, "job.pause", job=job_id)


def resume(job_id: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None or job.status != "paused":
            raise JobError("Nur pausierte Jobs können fortgesetzt werden.")
        job.status, job.control, job.message = "queued", None, "Fortsetzung eingeplant"
        audit(s, "job.resume", job=job_id)


def request_stop(job_id: str) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise JobError("Job nicht gefunden")
        if job.status == "queued":
            job.status, job.finished_at, job.message = "cancelled", utcnow(), "Abgebrochen"
        elif job.status == "paused":
            job.status, job.finished_at, job.message = "stopped", utcnow(), "Gestoppt (war pausiert)"
            vid = (job.params or {}).get("version_id")
            if vid and (v := s.get(ModelVersion, vid)) and v.status == "paused":
                v.status = "stopped"
        elif job.status in ("running", "pausing"):
            job.control, job.status, job.message = "stop", "stopping", "Stoppe sicher …"
        else:
            raise JobError(f"Job kann im Status {job.status} nicht gestoppt werden.")
        audit(s, "job.stop", job=job_id)


class JobManager:
    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopping_since: dict[str, float] = {}

    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="rubine-jobs", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        # Ask running training jobs to checkpoint (pause) so no work is lost.
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status == "running")):
                if job.type == "train":
                    job.control, job.status = "pause", "pausing"
        deadline = time.time() + 30
        for jid, proc in list(self._procs.items()):
            try:
                proc.wait(timeout=max(1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.terminate()

    def recover(self) -> None:
        """After a restart: jobs whose process vanished become paused (if a checkpoint exists) or failed."""
        st = get_settings()
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status.in_(ACTIVE))):
                if _pid_alive(job.pid) and job.pid != os.getpid():
                    continue
                ckpt = st.jobs_dir / job.id / "checkpoint" / "state.pt"
                if job.type == "train" and ckpt.exists():
                    job.status, job.control = "paused", None
                    job.message = "Nach Neustart pausiert – kann vom letzten Checkpoint fortgesetzt werden."
                    vid = (job.params or {}).get("version_id")
                    if vid and (v := s.get(ModelVersion, vid)):
                        v.status = "paused"
                else:
                    job.status, job.finished_at = "failed", utcnow()
                    job.error = "Prozess wurde unerwartet beendet (Server-Neustart oder Absturz)."
                    vid = (job.params or {}).get("version_id")
                    if job.type == "train" and vid and (v := s.get(ModelVersion, vid)) and \
                            v.status in ("training", "evaluating"):
                        v.status = "failed"
                audit(s, "job.recover", job=job.id, new_status=job.status)

    def _spawn(self, job_id: str) -> None:
        st = get_settings()
        log_dir = st.jobs_dir / job_id
        log_dir.mkdir(parents=True, exist_ok=True)
        logf = open(log_dir / "log.txt", "ab")
        env = dict(os.environ)
        backend = str(REPO_ROOT / "backend")
        env["PYTHONPATH"] = backend + os.pathsep + env.get("PYTHONPATH", "")
        env["RUBINE_DATA_DIR"] = str(st.data_dir)
        if st.database_url:
            env["RUBINE_DATABASE_URL"] = st.database_url
        env.setdefault("PYTHONIOENCODING", "utf-8")
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        proc = subprocess.Popen([sys.executable, "-m", "rubine.jobs.runner", job_id], cwd=backend, env=env,
                                stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
        logf.close()
        self._procs[job_id] = proc
        with session_scope() as s:
            job = s.get(Job, job_id)
            job.status, job.pid, job.message = "running", proc.pid, "Startet …"
            job.started_at = job.started_at or utcnow()
        log.info("Job %s gestartet (pid %s)", job_id, proc.pid)

    def tick(self) -> None:
        st = get_settings()
        # reap finished processes
        for jid, proc in list(self._procs.items()):
            code = proc.poll()
            if code is None:
                continue
            self._procs.pop(jid)
            self._stopping_since.pop(jid, None)
            with session_scope() as s:
                job = s.get(Job, jid)
                if job and job.status in ACTIVE:
                    job.status, job.finished_at = "failed", utcnow()
                    tail = _tail(st.jobs_dir / jid / "log.txt")
                    job.error = f"Worker beendet mit Code {code}.\n{tail}"
        with session_scope() as s:
            # timeouts & hard-stop fallback
            for job in s.scalars(select(Job).where(Job.status.in_(ACTIVE))):
                if job.started_at and utcnow() - _aware(job.started_at) > timedelta(hours=st.job_timeout_hours):
                    job.control = "stop"
                    job.status = "stopping"
                    job.message = "Zeitlimit erreicht – stoppe"
                if job.status == "stopping":
                    since = self._stopping_since.setdefault(job.id, time.time())
                    if time.time() - since > 180 and job.id in self._procs:
                        self._procs[job.id].kill()
                        job.status, job.finished_at = "stopped", utcnow()
                        job.message = "Hart beendet (keine Reaktion auf Stopp-Signal)"
            running = s.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE)))
            queued = list(s.scalars(select(Job.id).where(Job.status == "queued").order_by(Job.created_at)))
        free = st.max_concurrent_jobs - running
        for jid in queued[:max(0, free)]:
            self._spawn(jid)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("Fehler in der Job-Schleife")
            self._stop.wait(1.0)


def _aware(dt):  # SQLite returns naive datetimes
    from datetime import timezone
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tail(path: Path, n: int = 2000) -> str:
    try:
        data = path.read_bytes()[-n:]
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


_manager: JobManager | None = None


def get_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
