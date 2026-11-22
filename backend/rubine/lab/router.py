"""AI Lab API: dashboard, training control, datasets, evaluation, versions."""
from __future__ import annotations

import asyncio
import json
import os

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import REPO_ROOT, get_settings
from ..db import (iso, Activation, DatasetVersion, EvalRun, Example, Job, JobMetric, ModelVersion, audit, get_db,
                  session_scope)
from ..jobs import manager as jm
from ..llm import registry
from ..llm.engine import get_engine
from ..security.auth import require_auth
from ..training import curriculum as cur
from ..training import data as data_mod
from ..training.evalset import combined_id, eval_set_info
from ..training.teachers import list_teachers
from ..training.trainer import TrainConfig

router = APIRouter(prefix="/api/lab", dependencies=[Depends(require_auth)])
SEED_DIR = REPO_ROOT / "data" / "seed"


# ------------------------------------------------------------------ helpers
def system_stats() -> dict:
    vm = psutil.virtual_memory()
    proc = psutil.Process(os.getpid())
    out = {"cpu_percent": psutil.cpu_percent(interval=None), "cpu_count": psutil.cpu_count(),
           "ram_total_gb": round(vm.total / 1e9, 2), "ram_used_gb": round((vm.total - vm.available) / 1e9, 2),
           "ram_percent": vm.percent, "server_rss_gb": round(proc.memory_info().rss / 1e9, 2), "gpus": []}
    try:
        du = psutil.disk_usage(str(get_settings().data_dir))
        out["disk_free_gb"] = round(du.free / 1e9, 1)
    except OSError:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                free, total = torch.cuda.mem_get_info(i)
                out["gpus"].append({"name": torch.cuda.get_device_name(i), "mem_total_gb": round(total / 1e9, 2),
                                    "mem_used_gb": round((total - free) / 1e9, 2)})
    except Exception:  # noqa: BLE001
        pass
    return out


def job_dict(j: Job, with_metrics: bool = False, s: Session | None = None) -> dict:
    d = {"id": j.id, "type": j.type, "status": j.status, "progress": j.progress, "message": j.message,
         "params": j.params, "result": j.result, "error": j.error, "created_at": iso(j.created_at),
         "started_at": iso(j.started_at),
         "finished_at": iso(j.finished_at)}
    if with_metrics and s is not None:
        rows = s.scalars(select(JobMetric).where(JobMetric.job_id == j.id).order_by(JobMetric.id))
        d["metrics"] = [{"step": m.step, "loss": m.loss, "lr": m.lr, "kind": m.kind, "extra": m.extra} for m in rows]
    return d


def version_dict(v: ModelVersion, active: str) -> dict:
    return {"id": v.id, "name": v.name, "parent_id": v.parent_id, "status": v.status, "dataset_id": v.dataset_id,
            "job_id": v.job_id, "base_model": v.base_model, "hyperparams": v.hyperparams, "metrics": v.metrics,
            "notes": v.notes, "created_at": iso(v.created_at), "active": v.id == active,
            "chat_allowed": v.status in registry.CHAT_STATUSES}


def _submit(job_type: str, params: dict) -> dict:
    try:
        return {"job_id": jm.submit(job_type, params)}
    except jm.JobError as e:
        raise HTTPException(409, str(e)) from e


# ------------------------------------------------------------------ dashboard
@router.get("/overview")
def overview(s: Session = Depends(get_db)) -> dict:
    from ..world.simulation import get_world
    active = registry.active_version_id(s)
    v = s.get(ModelVersion, active)
    last_eval = s.scalars(select(EvalRun).where(EvalRun.version_id == active).order_by(EvalRun.created_at.desc())).first()
    running = s.scalars(select(Job).where(Job.status.in_(jm.ACTIVE + ("paused", "queued")))
                        .order_by(Job.created_at.desc())).all()
    train_job = next((j for j in running if j.type == "train"), None)
    last_loss = None
    if train_job:
        m = s.scalars(select(JobMetric).where(JobMetric.job_id == train_job.id, JobMetric.kind == "train")
                      .order_by(JobMetric.id.desc())).first()
        last_loss = m.loss if m else None
    world = None
    if get_settings().sim_enabled:
        w = get_world()
        world = {"agents": len(w.agents), "running": w.running, "clock": w.snapshot()["clock"]["label"]}
    failed = s.scalar(select(func.count()).select_from(Job).where(Job.status == "failed"))
    stage = cur.stage_for(last_eval.accuracy if last_eval else None)
    return {
        "active_version": version_dict(v, active) if v else None,
        "engine": get_engine().info(), "system": system_stats(), "world": world,
        "jobs_open": [job_dict(j) for j in running], "training_job": job_dict(train_job) if train_job else None,
        "training_last_loss": last_loss,
        "datasets": s.scalar(select(func.count()).select_from(DatasetVersion)),
        "examples": data_mod.pool_counts(s),
        "examples_total_approved": s.scalar(select(func.count()).select_from(Example).where(Example.status == "approved")),
        "examples_pending": s.scalar(select(func.count()).select_from(Example).where(Example.status == "pending")),
        "eval": ({"accuracy": last_eval.accuracy, "eval_loss": last_eval.eval_loss, "n": last_eval.n,
                  "per_family": last_eval.per_family, "created_at": iso(last_eval.created_at)} if last_eval else None),
        "curriculum_stage": {"name": stage.name, "difficulty_weights": stage.difficulty_weights},
        "failed_jobs": failed,
    }


@router.get("/system")
def system() -> dict:
    return system_stats()


# ------------------------------------------------------------------ versions
@router.get("/versions")
def versions(s: Session = Depends(get_db)) -> dict:
    active = registry.active_version_id(s)
    vs = s.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc()))
    acts = s.scalars(select(Activation).order_by(Activation.id.desc()).limit(30))
    return {"active": active, "versions": [version_dict(v, active) for v in vs],
            "activations": [{"version_id": a.version_id, "previous_version_id": a.previous_version_id,
                             "reason": a.reason, "created_at": iso(a.created_at)} for a in acts]}


@router.post("/versions/{vid}/activate")
def activate(vid: str, s: Session = Depends(get_db)) -> dict:
    try:
        registry.activate(s, vid)
    except registry.RegistryError as e:
        raise HTTPException(409, str(e)) from e
    return {"active": vid}


@router.post("/rollback")
def rollback(s: Session = Depends(get_db)) -> dict:
    try:
        a = registry.rollback(s)
    except registry.RegistryError as e:
        raise HTTPException(409, str(e)) from e
    return {"active": a.version_id, "previous": a.previous_version_id}


# ------------------------------------------------------------------ jobs
@router.get("/jobs")
def jobs(limit: int = 50, s: Session = Depends(get_db)) -> list[dict]:
    return [job_dict(j) for j in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(min(limit, 200)))]


@router.get("/jobs/{job_id}")
def job(job_id: str, s: Session = Depends(get_db)) -> dict:
    j = s.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "Job nicht gefunden")
    d = job_dict(j, True, s)
    log = get_settings().jobs_dir / job_id / "log.txt"
    if log.exists():
        from ..security.logging_setup import redact
        d["log_tail"] = redact(log.read_bytes()[-6000:].decode("utf-8", errors="replace"))
    return d


class TrainRequest(BaseModel):
    dataset_id: str | None = None
    parent_id: str | None = None
    continue_from_parent: bool = True
    name: str | None = Field(default=None, max_length=80)
    families: list[str] | None = None
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    learning_rate: float = 2e-4
    epochs: float = 1.0
    max_steps: int | None = 60
    batch_size: int = 4
    grad_accum: int = 1
    max_seq_len: int = 384
    seed: int = 42


@router.post("/jobs/train")
def start_training(body: TrainRequest) -> dict:
    p = body.model_dump()
    try:
        TrainConfig.from_params(p, get_settings())  # validate limits early
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    if body.families and not set(body.families) <= set(cur.FAMILIES):
        raise HTTPException(422, "Unbekannte Aufgabenfamilie")
    return _submit("train", p)


@router.post("/jobs/{job_id}/pause")
def pause(job_id: str) -> dict:
    try:
        jm.request_pause(job_id)
    except jm.JobError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@router.post("/jobs/{job_id}/resume")
def resume(job_id: str) -> dict:
    try:
        jm.resume(job_id)
    except jm.JobError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@router.post("/jobs/{job_id}/stop")
def stop(job_id: str) -> dict:
    try:
        jm.request_stop(job_id)
    except jm.JobError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


class CompareRequest(BaseModel):
    a: str
    b: str
    force: bool = False


@router.post("/compare")
def compare(body: CompareRequest, s: Session = Depends(get_db)) -> dict:
    for vid in (body.a, body.b):
        v = s.get(ModelVersion, vid)
        if v is None or (v.id != registry.BASE_ID and not v.adapter_path):
            raise HTTPException(422, f"Version {vid} ist nicht vergleichbar (keine Gewichte).")
    return _submit("compare", body.model_dump())


class EvaluateRequest(BaseModel):
    version_id: str
    force: bool = False


@router.post("/evaluate")
def evaluate(body: EvaluateRequest, s: Session = Depends(get_db)) -> dict:
    v = s.get(ModelVersion, body.version_id)
    if v is None or (v.id != registry.BASE_ID and not v.adapter_path):
        raise HTTPException(422, "Version hat keine Gewichte")
    return _submit("evaluate", body.model_dump())


class AgentBenchRequest(BaseModel):
    version_id: str | None = None
    hf_model: str | None = None
    per_cat: int = Field(default=10, ge=2, le=40)


@router.post("/agent-bench")
def agent_bench(body: AgentBenchRequest, s: Session = Depends(get_db)) -> dict:
    if body.hf_model and body.hf_model not in get_settings().agent_bench_models:
        raise HTTPException(422, "Modell nicht freigegeben")
    if not body.hf_model:
        v = s.get(ModelVersion, body.version_id or registry.BASE_ID)
        if v is None or (v.id != registry.BASE_ID and not v.adapter_path):
            raise HTTPException(422, "Version hat keine Gewichte")
    return _submit("agent_bench", body.model_dump())


@router.get("/agent-bench")
def agent_bench_results() -> dict:
    import json as _json
    d = get_settings().eval_dir / "agent_bench"
    rows = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            r = _json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows.append({k: v for k, v in r.items() if k != "results"})
    rows.sort(key=lambda r: -(r.get("created") or 0))
    return {"results": rows, "models": list(get_settings().agent_bench_models),
            "note": "Misst Entscheidungen in klaren Situationen (gleiches Format wie die Simulation), nicht Verständnis oder Bewusstsein."}


@router.get("/evals")
def evals(s: Session = Depends(get_db)) -> list[dict]:
    rows = s.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(100))
    return [{"id": r.id, "version_id": r.version_id, "eval_set_id": r.eval_set_id, "accuracy": r.accuracy,
             "eval_loss": r.eval_loss, "n": r.n, "per_family": r.per_family, "created_at": iso(r.created_at)}
            for r in rows]


@router.get("/evalset")
def evalset() -> dict:
    return {"id": combined_id(), "sets": eval_set_info()}


class SimExportRequest(BaseModel):
    per_family: int = Field(default=60, ge=1, le=1000)
    include_dialogs: bool = False
    seed: int = 1
    resident_decisions: bool = False  # World 3.0: situation-determined decision examples from separate training worlds
    worlds: int = Field(default=6, ge=1, le=40)
    per_cat: int = Field(default=10, ge=1, le=40)


@router.post("/data/simulation")
def sim_export(body: SimExportRequest) -> dict:
    return _submit("sim_export", body.model_dump())


# ------------------------------------------------------------------ data
class SyntheticRequest(BaseModel):
    n: int = Field(default=300, ge=1, le=20000)
    families: list[str] | None = None
    seed: int | None = None
    difficulty_weights: dict[str, float] | None = None


@router.post("/data/synthetic")
def synthetic(body: SyntheticRequest) -> dict:
    if body.families and not set(body.families) <= set(cur.FAMILIES):
        raise HTTPException(422, "Unbekannte Aufgabenfamilie")
    return _submit("synthetic", body.model_dump())


class TeacherRequest(BaseModel):
    teacher: str = Field(pattern="^(openai_compatible|local_hf|anthropic)$")
    n: int = Field(default=50, ge=1, le=2000)
    families: list[str] | None = None
    prompts: list[str] | None = Field(default=None, max_length=200)
    seed: int | None = None


@router.post("/data/teacher")
def teacher(body: TeacherRequest) -> dict:
    return _submit("teacher", body.model_dump())


@router.get("/teachers")
def teachers() -> list[dict]:
    return list_teachers()


class BuildRequest(BaseModel):
    seed: int = 42
    families: list[str] | None = None
    sources: list[str] | None = None
    max_examples: int | None = None


@router.post("/datasets/build")
def build(body: BuildRequest) -> dict:
    return _submit("build_dataset", body.model_dump())


@router.get("/datasets")
def datasets(s: Session = Depends(get_db)) -> list[dict]:
    return [{"id": d.id, "sha256": d.sha256, "n_examples": d.n_examples, "counts": d.counts, "params": d.params,
             "created_at": iso(d.created_at)}
            for d in s.scalars(select(DatasetVersion).order_by(DatasetVersion.created_at.desc()))]


@router.get("/data/examples")
def examples(status: str = "pending", source: str | None = None, limit: int = 50,
             s: Session = Depends(get_db)) -> list[dict]:
    q = select(Example).where(Example.status == status).order_by(Example.created_at.desc()).limit(min(limit, 200))
    if source:
        q = q.where(Example.source == source)
    return [{"id": e.id, "messages": e.messages, "response": e.response, "source": e.source, "family": e.family,
             "verified": e.verified, "verifier": e.verifier, "status": e.status, "meta": e.meta,
             "created_at": iso(e.created_at)} for e in s.scalars(q)]


class Review(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")


@router.post("/data/examples/{eid}/review")
def review(eid: str, body: Review, s: Session = Depends(get_db)) -> dict:
    e = s.get(Example, eid)
    if e is None:
        raise HTTPException(404, "Beispiel nicht gefunden")
    e.status = "approved" if body.action == "approve" else "rejected"
    audit(s, "data.review", example=eid, action=body.action)
    return {"id": eid, "status": e.status}


@router.post("/data/import")
async def import_file(file: UploadFile = File(...), approve: bool = False) -> dict:
    raw = await file.read(10_000_001)
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Datei zu groß (max. 10 MB)")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(422, "Datei muss UTF-8 sein") from e
    with session_scope() as s:
        return data_mod.import_jsonl(s, text.splitlines(), approve=approve, origin=f"upload:{file.filename}"[:80])


@router.get("/data/seeds")
def seeds() -> list[dict]:
    out = []
    for p in sorted(SEED_DIR.glob("*.jsonl")):
        n = sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("//"))
        out.append({"name": p.name, "examples": n})
    return out


class SeedImport(BaseModel):
    name: str = Field(pattern=r"^[\w.\-]+\.jsonl$")
    approve: bool = True


@router.post("/data/seeds/import")
def import_seed(body: SeedImport) -> dict:
    path = (SEED_DIR / body.name).resolve()
    if path.parent != SEED_DIR.resolve() or not path.exists():
        raise HTTPException(404, "Seed-Datei nicht gefunden")
    with session_scope() as s:
        return data_mod.import_jsonl(s, path.read_text(encoding="utf-8").splitlines(), approve=body.approve,
                                     origin=f"seed:{body.name}")


@router.get("/curriculum")
def curriculum() -> dict:
    return {"families": sorted(cur.FAMILIES),
            "stages": [{"name": st.name, "difficulty_weights": st.difficulty_weights, "unlock_accuracy": st.unlock_accuracy}
                       for st in cur.CURRICULUM],
            "examples": [cur.FAMILIES[f](__import__("random").Random(1), 1).to_dict() for f in sorted(cur.FAMILIES)]}


# ------------------------------------------------------------------ live stream
@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    async def gen():
        last = None
        n = 0
        while not await request.is_disconnected():
            with session_scope() as s:
                open_jobs = s.scalars(select(Job).where(Job.status.in_(jm.ACTIVE + ("queued", "paused")))
                                      .order_by(Job.created_at)).all()
                payload = {"jobs": [job_dict(j) for j in open_jobs]}
                tj = next((j for j in open_jobs if j.type == "train"), None)
                if tj:
                    ms = s.scalars(select(JobMetric).where(JobMetric.job_id == tj.id, JobMetric.kind == "train")
                                   .order_by(JobMetric.id.desc()).limit(300)).all()
                    payload["train_metrics"] = {"job_id": tj.id, "points": [{"step": m.step, "loss": m.loss, "lr": m.lr}
                                                                            for m in reversed(ms)]}
            if n % 5 == 0:
                payload["system"] = system_stats()
                payload["engine"] = get_engine().info()
            blob = json.dumps(payload, ensure_ascii=False, default=str)
            if blob != last or n % 10 == 0:
                last = blob
                yield f"event: lab\ndata: {blob}\n\n"
            n += 1
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/backup")
def backup() -> dict:
    from ..db import backup_sqlite
    p = backup_sqlite("manual")
    return {"path": str(p) if p else None, "note": None if p else "Nur für SQLite verfügbar"}

