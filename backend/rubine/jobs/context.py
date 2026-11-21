"""Job state helpers shared by the API process and the job worker process."""
from __future__ import annotations

import time
from typing import Any

from ..db import Job, JobMetric, session_scope, utcnow


class JobStopped(Exception):
    pass


class JobContext:
    """Used inside the worker process to report progress and read control flags."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._last_beat = 0.0
        self._last_control_check = 0.0
        self._control: str | None = None

    def load(self) -> Job:
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            if job is None:
                raise RuntimeError(f"Job {self.job_id} existiert nicht")
            s.expunge(job)
            return job

    def update(self, **fields: Any) -> None:
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            job.heartbeat_at = utcnow()

    def merge_params(self, **params: Any) -> None:
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            job.params = {**(job.params or {}), **params}

    def progress(self, value: float, message: str | None = None) -> None:
        now = time.time()
        if now - self._last_beat < 0.5 and value < 1.0:
            return
        self._last_beat = now
        fields: dict[str, Any] = {"progress": max(0.0, min(1.0, value))}
        if message:
            fields["message"] = message[:300]
        self.update(**fields)

    def status(self, message: str) -> None:
        self.update(message=message[:300])

    def metric(self, step: int, loss: float | None = None, lr: float | None = None,
               kind: str = "train", extra: dict | None = None) -> None:
        with session_scope() as s:
            s.add(JobMetric(job_id=self.job_id, step=step, loss=loss, lr=lr, kind=kind, extra=extra))

    def control(self) -> str | None:
        """Return 'pause'/'stop' if requested (checked at most every 0.5 s)."""
        now = time.time()
        if now - self._last_control_check >= 0.5:
            self._last_control_check = now
            with session_scope() as s:
                job = s.get(Job, self.job_id)
                self._control = job.control if job else "stop"
        return self._control

    def raise_if_stopped(self) -> None:
        if self.control() == "stop":
            raise JobStopped()
