"""Job worker process: ``python -m rubine.jobs.runner <job_id>``.

Each job runs in its own process so that heavy training never blocks the API
and can be terminated safely. Every run is logged in the DB (status, metrics,
errors) and in ``data/jobs/<job_id>/log.txt``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from ..config import get_settings
from ..db import DatasetVersion, EvalRun, Job, ModelVersion, audit, init_db, session_scope, utcnow
from ..llm import registry
from ..security.logging_setup import setup_logging
from ..training import curriculum as cur
from ..training import data as data_mod
from ..training.evalset import combined_id, eval_prompt_hashes, load_eval_set
from ..training.teachers import get_teacher
from .context import JobContext, JobStopped

log = logging.getLogger("rubine.job")


# ------------------------------------------------------------------ evaluation
def _eval_cache_path(version_id: str, sha: str) -> Path:
    return get_settings().eval_dir / "runs" / f"{version_id}-{sha[:12]}.json"


def evaluate_versions(ctx: JobContext, version_ids: list[str], *, force: bool = False,
                      span: tuple[float, float] = (0.0, 1.0)) -> dict[str, dict]:
    """Evaluate versions on the frozen eval set, reusing cached runs for the same set hash."""
    from ..llm.engine import load_base_model, load_tokenizer, resolve_device
    from ..training.evaluate import eval_loss, evaluate_items

    settings = get_settings()
    items, sha = load_eval_set()
    out: dict[str, dict] = {}
    todo: list[tuple[str, str | None]] = []
    with session_scope() as s:
        for vid in version_ids:
            v = s.get(ModelVersion, vid)
            if v is None:
                raise ValueError(f"Unbekannte Version {vid}")
            cached = s.scalars(select(EvalRun).where(EvalRun.version_id == vid, EvalRun.eval_set_sha256 == sha)
                               .order_by(EvalRun.created_at.desc())).first()
            if cached and not force and cached.results_path and Path(cached.results_path).exists():
                data = json.loads(Path(cached.results_path).read_text(encoding="utf-8"))
                out[vid] = {**data, "cached": True, "eval_run_id": cached.id}
            else:
                todo.append((vid, v.adapter_path))
    if not todo:
        return out

    device = resolve_device(settings.device)
    ctx.status("Lade Modell für Evaluation …")
    tok = load_tokenizer(settings)
    base = load_base_model(settings, device)
    peft = None
    lo, hi = span
    for k, (vid, adapter_path) in enumerate(todo):
        if adapter_path:
            from peft import PeftModel
            name = vid.replace("-", "_")
            if peft is None:
                peft = PeftModel.from_pretrained(base, adapter_path, adapter_name=name)
            else:
                peft.load_adapter(adapter_path, adapter_name=name)
            peft.set_adapter(name)
            peft.eval()
            model, use_adapter = peft, True
        else:
            model, use_adapter = (peft, False) if peft is not None else (base, True)

        def prog(done: int, total: int, _k: int = k, _vid: str = vid) -> bool:
            frac = (_k + done / total) / len(todo)
            ctx.progress(lo + (hi - lo) * frac, f"Evaluiere {_vid}: {done}/{total}")
            return ctx.control() == "stop"

        try:
            res = evaluate_items(model, tok, items, device, use_adapter=use_adapter, progress=prog)
        except InterruptedError:
            raise JobStopped()
        res["eval_loss"] = eval_loss(model, tok, items, device, use_adapter=use_adapter)
        res.update(version_id=vid, eval_set_id=combined_id(), eval_set_sha256=sha)
        path = _eval_cache_path(vid, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        with session_scope() as s:
            run = EvalRun(version_id=vid, eval_set_id=combined_id()[:40], eval_set_sha256=sha, accuracy=res["accuracy"],
                          eval_loss=res["eval_loss"], n=res["n"], per_family=res["per_family"],
                          results_path=str(path), job_id=ctx.job_id)
            s.add(run)
            s.flush()
            res["eval_run_id"] = run.id
        ctx.metric(k, kind="eval", extra={"version": vid, "accuracy": res["accuracy"], "eval_loss": res["eval_loss"]})
        out[vid] = {**res, "cached": False}
    return out


def _summary(r: dict) -> dict:
    return {k: r[k] for k in ("accuracy", "eval_loss", "n", "per_family", "eval_set_sha256", "cached") if k in r}


# ------------------------------------------------------------------ handlers
def run_synthetic(ctx: JobContext, p: dict) -> dict:
    seed = p.get("seed") or int(time.time())
    n = min(int(p.get("n", 200)), get_settings().max_train_examples)
    ctx.status(f"Erzeuge {n} verifizierte synthetische Aufgaben …")
    with session_scope() as s:
        res = data_mod.add_synthetic(s, n, seed, p.get("families"), _weights(p))
        audit(s, "data.synthetic", job=ctx.job_id, seed=seed, **res)
    return {**res, "seed": seed}


def _weights(p: dict) -> dict[int, float] | None:
    w = p.get("difficulty_weights")
    return {int(k): float(v) for k, v in w.items()} if w else None


def run_build_dataset(ctx: JobContext, p: dict) -> dict:
    ctx.status("Baue versionierten Datensatz …")
    with session_scope() as s:
        ds = data_mod.build_dataset(s, seed=int(p.get("seed", 42)), families=p.get("families"),
                                    sources=p.get("sources"), max_examples=p.get("max_examples"))
        return {"dataset_id": ds.id, "n_examples": ds.n_examples, "sha256": ds.sha256, "counts": ds.counts}


def run_teacher(ctx: JobContext, p: dict) -> dict:
    teacher = get_teacher(p["teacher"])
    ok, detail = teacher.available()
    if not ok:
        raise RuntimeError(f"Lehrer nicht verfügbar: {detail}")
    n = min(int(p.get("n", 50)), 2000)
    seed = p.get("seed") or int(time.time())
    tasks = cur.generate_tasks(n, f"teacher-{seed}", p.get("families"), _weights(p),
                               exclude_hashes=eval_prompt_hashes())
    stats = {"asked": 0, "verified": 0, "rejected": 0, "errors": 0, "duplicates": 0}
    for i, t in enumerate(tasks):
        ctx.raise_if_stopped()
        ctx.progress(i / max(1, len(tasks)), f"Lehrer {teacher.name}: {i}/{len(tasks)}")
        stats["asked"] += 1
        try:
            answer = teacher.generate([{"role": "user", "content": t.prompt}])
        except Exception as e:  # noqa: BLE001
            stats["errors"] += 1
            log.warning("Lehrerfehler: %s", type(e).__name__)
            if stats["errors"] >= 5 and stats["verified"] == 0:
                raise RuntimeError("Lehrer liefert wiederholt Fehler – Abbruch") from e
            continue
        correct, _ = cur.verify(t, answer)
        if not correct:
            stats["rejected"] += 1
            continue
        with session_scope() as s:
            try:
                ex = data_mod.add_example(s, messages=[{"role": "user", "content": t.prompt}], response=answer,
                                          source=teacher.source, family=t.family, verified=True,
                                          verifier=f"curriculum.{t.family}", status="approved",
                                          meta={"teacher": teacher.name, "difficulty": t.difficulty})
                stats["verified" if ex else "duplicates"] += 1
            except data_mod.DataError:
                stats["rejected"] += 1
    # Free-form prompts (not verifiable) -> pending human review
    pending = 0
    for prompt in (p.get("prompts") or [])[:200]:
        ctx.raise_if_stopped()
        try:
            answer = teacher.generate([{"role": "user", "content": str(prompt)}], max_tokens=700)
            with session_scope() as s:
                if data_mod.add_example(s, messages=[{"role": "user", "content": str(prompt)}], response=answer,
                                        source=teacher.source, status="pending", meta={"teacher": teacher.name}):
                    pending += 1
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
    with session_scope() as s:
        audit(s, "data.teacher", job=ctx.job_id, teacher=teacher.name, **stats, pending=pending)
    return {**stats, "pending_review": pending, "seed": seed, "teacher": teacher.name}


def run_train(ctx: JobContext, p: dict) -> dict:
    from ..training.evaluate import promotion_gate
    from ..training.trainer import TrainConfig, TrainingInterrupted, train_lora

    settings = get_settings()
    cfg = TrainConfig.from_params(p, settings)
    with session_scope() as s:
        registry.ensure_base_version(s)
        if p.get("dataset_id"):
            ds = s.get(DatasetVersion, p["dataset_id"])
            if ds is None:
                raise ValueError("Datensatz nicht gefunden")
        else:
            ctx.status("Baue neuen Datensatz aus freigegebenen Beispielen …")
            ds = data_mod.build_dataset(s, seed=cfg.seed, families=p.get("families"))
        parent_id = p.get("parent_id") or registry.active_version_id(s)
        parent = s.get(ModelVersion, parent_id)
        if parent is None or parent.status not in registry.ACTIVATABLE_STATUSES:
            raise ValueError("Elternversion muss die Basis oder eine bestandene Version sein")
        init_adapter = parent.adapter_path if (parent.adapter_path and p.get("continue_from_parent", True)) else None
        vid = p.get("version_id")
        if vid and s.get(ModelVersion, vid):
            v = s.get(ModelVersion, vid)
            v.status = "training"
        else:
            vid = registry.next_version_id(s)
            s.add(ModelVersion(id=vid, name=p.get("name") or f"Rubine {vid}", parent_id=parent_id, status="training",
                               dataset_id=ds.id, job_id=ctx.job_id, base_model=settings.base_model,
                               hyperparams={**cfg.__dict__, "base_revision": settings.base_model_revision,
                                            "init_adapter_from": parent_id if init_adapter else None}))
        ds_id, ds_path, ds_sha = ds.id, ds.path, ds.sha256
        audit(s, "train.start", job=ctx.job_id, version=vid, dataset=ds_id, parent=parent_id)
    ctx.merge_params(dataset_id=ds_id, version_id=vid, parent_id=parent_id)

    rows = data_mod.load_dataset_file(ds_path, ds_sha)
    out_dir = registry.adapter_dir(vid)
    ckpt_dir = settings.jobs_dir / ctx.job_id / "checkpoint"

    def on_step(step: int, total: int, loss: float, lr: float) -> str | None:
        ctx.metric(step, loss=loss, lr=lr)
        ctx.progress(0.7 * step / total, f"Schritt {step}/{total} · Loss {loss:.4f}")
        return ctx.control()

    try:
        summary = train_lora(rows=rows, cfg=cfg, out_dir=out_dir, ckpt_dir=ckpt_dir, init_adapter=init_adapter,
                             on_step=on_step, on_status=ctx.status, settings=settings)
    except TrainingInterrupted as e:
        with session_scope() as s:
            s.get(ModelVersion, vid).status = "paused" if e.kind == "pause" else "stopped"
            audit(s, f"train.{e.kind}", job=ctx.job_id, version=vid, step=e.step)
        raise

    with session_scope() as s:
        v = s.get(ModelVersion, vid)
        v.status, v.adapter_path = "evaluating", str(out_dir)
        v.metrics = {"train": summary}
    ctx.status("Training abgeschlossen – starte unabhängige Evaluation …")
    evals = evaluate_versions(ctx, [parent_id, vid], span=(0.7, 1.0))
    passed, reasons = promotion_gate(evals[vid], evals[parent_id], settings)
    with session_scope() as s:
        v = s.get(ModelVersion, vid)
        v.status = "passed" if passed else "failed_eval"
        v.metrics = {"train": summary, "eval": _summary(evals[vid]), "parent_eval": _summary(evals[parent_id]),
                     "gate": {"passed": passed, "reasons": reasons}}
        audit(s, "train.finished", job=ctx.job_id, version=vid, passed=passed, accuracy=evals[vid]["accuracy"])
    shutil.rmtree(ckpt_dir, ignore_errors=True)
    return {"version_id": vid, "dataset_id": ds_id, "train": summary, "gate": {"passed": passed, "reasons": reasons},
            "accuracy": evals[vid]["accuracy"], "parent_accuracy": evals[parent_id]["accuracy"],
            "note": "Version wurde NICHT automatisch aktiviert." if passed else "Version hat die Tests nicht bestanden."}


def run_evaluate(ctx: JobContext, p: dict) -> dict:
    res = evaluate_versions(ctx, [p["version_id"]], force=bool(p.get("force")))
    return {"version_id": p["version_id"], **_summary(res[p["version_id"]])}


def run_compare(ctx: JobContext, p: dict) -> dict:
    a, b = p["a"], p["b"]
    if a == b:
        raise ValueError("Zwei unterschiedliche Versionen wählen")
    res = evaluate_versions(ctx, [a, b], force=bool(p.get("force")))
    ra, rb = res[a], res[b]
    diffs = []
    for x, y in zip(ra["results"], rb["results"]):
        if x["correct"] != y["correct"]:
            diffs.append({"prompt": x["prompt"], "family": x["family"], "expected": x["expected"],
                          "a": {"extracted": x["extracted"], "correct": x["correct"], "output": x["output"][:400]},
                          "b": {"extracted": y["extracted"], "correct": y["correct"], "output": y["output"][:400]}})
    return {"a": {"version_id": a, **_summary(ra)}, "b": {"version_id": b, **_summary(rb)},
            "only_a_correct": sum(1 for d in diffs if d["a"]["correct"]),
            "only_b_correct": sum(1 for d in diffs if d["b"]["correct"]), "diffs": diffs[:60]}


def run_sim_export(ctx: JobContext, p: dict) -> dict:
    """Export verified simulation tasks from the active (or given) world into the example pool."""
    from ..world2.service import load_registry, world_dir
    from ..world2.store import WorldStore
    from ..world2.export import export_to_pool
    if p.get("resident_decisions"):
        from ..world2.export import export_resident_decisions
        ctx.status("Erzeuge Bewohner-Entscheidungen aus Trainingswelten …")
        with session_scope() as s:
            res = export_resident_decisions(s, worlds=int(p.get("worlds", 6)), per_cat=int(p.get("per_cat", 10)))
            audit(s, "data.resident_decisions", job=ctx.job_id, **{k: v for k, v in res.items() if k != "categories"})
        return res
    world_id = p.get("world_id") or load_registry().get("active")
    if not world_id:
        raise ValueError("Keine Simulationswelt vorhanden")
    store = WorldStore(world_dir(world_id) / "world.db")
    ctx.status("Lade Weltzustand …")
    w = store.load_latest()
    if w is None:
        raise ValueError("Welt hat keinen Speicherstand")
    events = store.events(kind="tausch,abstimmung,dialog", limit=4000)
    ctx.status(f"Prüfe {len(events)} Ereignisse und {len(w.cases)} Fälle …")
    with session_scope() as s:
        res = export_to_pool(s, w, events, per_family=int(p.get("per_family", 60)), seed=int(p.get("seed", 1)),
                             include_dialogs=bool(p.get("include_dialogs", False)))
        audit(s, "data.sim_export", job=ctx.job_id, world=world_id, **{k: v for k, v in res.items() if k != "per_family"})
    return {"world_id": world_id, "tick": w.tick, **res}


def run_agent_bench(ctx: JobContext, p: dict) -> dict:
    """Resident decision benchmark on a held-out world (see rubine/world2/benchmark.py)."""
    from ..world2 import benchmark as B
    settings = get_settings()
    items = B.build_items(per_cat=int(p.get("per_cat", 10)))
    sha = B.items_sha(items)
    if p.get("hf_model"):
        name = p["hf_model"]
        if name not in settings.agent_bench_models:
            raise ValueError("Modell nicht freigegeben (agent_bench_models)")
        label, model, rev, adapter = name, name, settings.agent_bench_models[name], None
    else:
        vid = p.get("version_id") or registry.BASE_ID
        with session_scope() as s:
            v = s.get(ModelVersion, vid)
            if v is None or (v.id != registry.BASE_ID and not v.adapter_path):
                raise ValueError("Version hat keine Gewichte")
            adapter = v.adapter_path
        label, model, rev = vid, settings.base_model, settings.base_model_revision
    ctx.status(f"Lade {label} …")
    gen, info = B.hf_generator(model, adapter, revision=rev)

    def prog(done: int, total: int) -> bool:
        ctx.progress(done / total, f"Bewohner-Test {label}: {done}/{total}")
        return ctx.control() == "stop"

    try:
        res = B.run(gen, items, progress=prog)
    except InterruptedError:
        raise JobStopped()
    res.update(info, label=label, items_sha256=sha, seed=B.BENCH_SEED, job_id=ctx.job_id, created=time.time())
    out = settings.eval_dir / "agent_bench" / f"{label.replace('/', '_')}-{sha[:12]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in res.items() if k != "results"}


HANDLERS: dict[str, Callable[[JobContext, dict], dict]] = {
    "sim_export": run_sim_export, "agent_bench": run_agent_bench,
    "synthetic": run_synthetic, "build_dataset": run_build_dataset, "teacher": run_teacher,
    "train": run_train, "evaluate": run_evaluate, "compare": run_compare,
}


def main(job_id: str) -> int:
    setup_logging()
    init_db()
    ctx = JobContext(job_id)
    job = ctx.load()
    if job.type not in HANDLERS:
        ctx.update(status="failed", error=f"Unbekannter Jobtyp {job.type}", finished_at=utcnow())
        return 2
    ctx.update(status="running", pid=os.getpid(), started_at=job.started_at or utcnow(), error=None)
    log.info("Job %s (%s) gestartet", job_id, job.type)
    try:
        result = HANDLERS[job.type](ctx, dict(job.params or {}))
        ctx.update(status="completed", result=result, progress=1.0, finished_at=utcnow(), control=None,
                   message="Abgeschlossen")
        return 0
    except JobStopped:
        ctx.update(status="stopped", finished_at=utcnow(), control=None, message="Gestoppt")
        return 0
    except Exception as e:  # noqa: BLE001
        from ..training.trainer import TrainingInterrupted
        if isinstance(e, TrainingInterrupted):
            if e.kind == "pause":
                ctx.update(status="paused", control=None, message=f"Pausiert bei Schritt {e.step}")
            else:
                ctx.update(status="stopped", control=None, finished_at=utcnow(),
                           message=f"Gestoppt bei Schritt {e.step}")
            return 0
        tb = traceback.format_exc()
        log.error("Job %s fehlgeschlagen:\n%s", job_id, tb)
        ctx.update(status="failed", error=f"{type(e).__name__}: {e}"[:2000], finished_at=utcnow(), control=None)
        with session_scope() as s:
            j = s.get(Job, job_id)
            vid = (j.params or {}).get("version_id")
            if j.type == "train" and vid:
                v = s.get(ModelVersion, vid)
                if v and v.status in ("training", "evaluating"):
                    v.status = "failed"
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
