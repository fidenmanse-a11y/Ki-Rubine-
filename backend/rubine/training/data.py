"""Training example pool, imports and versioned dataset snapshots."""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import DatasetVersion, Example, audit, utcnow
from ..llm.engine import SYSTEM_PROMPT
from ..security.sanitize import is_clean_for_training, strip_control
from . import curriculum as cur
from .evalset import eval_prompt_hashes

SOURCES = {"synthetic_gold", "agent_verified", "teacher_local", "teacher_api", "manual_import", "user_chat"}
# Examples produced by Rubine itself (via the agents). Capped per dataset.
SELF_GENERATED = {"agent_verified"}


class DataError(ValueError):
    pass


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def add_example(s: Session, *, messages: list[dict], response: str, source: str,
                family: str | None = None, verified: bool = False, verifier: str | None = None,
                status: str = "pending", meta: dict | None = None) -> Example | None:
    """Insert an example. Returns None for duplicates; raises DataError for unsafe data."""
    if source not in SOURCES:
        raise DataError(f"Unbekannte Quelle: {source}")
    if not messages or messages[-1].get("role") != "user":
        raise DataError("Beispiel muss mit einer Nutzernachricht enden")
    clean_msgs = []
    for m in messages:
        role = m.get("role")
        if role not in ("system", "user", "assistant"):
            raise DataError(f"Ungültige Rolle: {role}")
        clean_msgs.append({"role": role, "content": strip_control(str(m.get("content", ""))).strip()})
    response = strip_control(response).strip()
    if not response or len(response) > 8000:
        raise DataError("Antwort leer oder zu lang")
    for text in [response] + [m["content"] for m in clean_msgs]:
        ok, reasons = is_clean_for_training(text)
        if not ok:
            raise DataError(f"Beispiel abgelehnt (Sicherheitsfilter: {', '.join(reasons)})")
    content_hash = _hash({"m": clean_msgs, "r": response})
    if s.scalars(select(Example.id).where(Example.content_hash == content_hash)).first():
        return None
    ex = Example(messages=clean_msgs, response=response, source=source, family=family,
                 verified=verified, verifier=verifier, status=status, content_hash=content_hash,
                 prompt_hash=cur.prompt_hash(last_user_text(clean_msgs)), meta=meta)
    s.add(ex)
    s.flush()
    return ex


def add_synthetic(s: Session, n: int, seed: int | str, families: list[str] | None = None,
                  difficulty_weights: dict[int, float] | None = None) -> dict:
    """Programmatically generated gold examples (correct by construction)."""
    tasks = cur.generate_tasks(n, f"train-{seed}", families, difficulty_weights,
                               exclude_hashes=eval_prompt_hashes())
    added = 0
    for t in tasks:
        ok, _ = cur.verify(t, t.solution)
        if not ok:  # generator bug guard – never store unverifiable gold
            continue
        if add_example(s, messages=[{"role": "user", "content": t.prompt}], response=t.solution,
                       source="synthetic_gold", family=t.family, verified=True,
                       verifier=f"curriculum.{t.family}", status="approved",
                       meta={"difficulty": t.difficulty, "answer": t.answer, "seed": str(seed)}):
            added += 1
    return {"requested": n, "added": added}


def parse_import_line(obj: dict) -> tuple[list[dict], str]:
    if "messages" in obj:
        msgs = obj["messages"]
        if not isinstance(msgs, list) or not msgs:
            raise DataError("'messages' muss eine nicht-leere Liste sein")
        if msgs[-1].get("role") == "assistant":
            return msgs[:-1], str(msgs[-1].get("content", ""))
        if "response" in obj:
            return msgs, str(obj["response"])
        raise DataError("Letzte Nachricht muss 'assistant' sein oder 'response' fehlt")
    if "prompt" in obj and "response" in obj:
        return [{"role": "user", "content": str(obj["prompt"])}], str(obj["response"])
    raise DataError("Erwartet 'messages' oder 'prompt'+'response'")


def import_jsonl(s: Session, lines: Iterable[str], *, source: str = "manual_import",
                 approve: bool = False, origin: str = "upload") -> dict:
    """Import JSONL. Lines with a 'task' block are verified programmatically."""
    if source not in ("manual_import", "teacher_api", "teacher_local"):
        raise DataError("Import-Quelle nicht erlaubt")
    stats = Counter()
    errors: list[str] = []
    evalh = eval_prompt_hashes()
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            obj = json.loads(line)
            msgs, resp = parse_import_line(obj)
            verified, verifier, family = False, None, obj.get("family")
            task = obj.get("task")
            if task:  # {"family":..,"answer":..,"kind":..}
                ok, _ = cur.verify({"kind": task.get("kind", "exact"), "answer": str(task["answer"])}, resp)
                if not ok:
                    stats["failed_verification"] += 1
                    continue
                verified, verifier = True, "import.task_answer"
            if cur.prompt_hash(last_user_text(msgs)) in evalh:
                stats["eval_contamination"] += 1
                continue
            status = "approved" if approve else "pending"
            ex = add_example(s, messages=msgs, response=resp, source=source, family=family,
                             verified=verified, verifier=verifier, status=status,
                             meta={"origin": origin, "line": i, "author": obj.get("author")})
            stats["added" if ex else "duplicate"] += 1
        except (DataError, json.JSONDecodeError, KeyError, TypeError) as e:
            stats["invalid"] += 1
            if len(errors) < 20:
                errors.append(f"Zeile {i}: {e}")
    audit(s, "data.import", source=source, origin=origin, stats=dict(stats))
    return {"stats": dict(stats), "errors": errors}


def pool_counts(s: Session) -> dict:
    rows = s.execute(select(Example.source, Example.status, func.count()).group_by(Example.source, Example.status))
    out: dict[str, dict[str, int]] = {}
    for src, st, n in rows:
        out.setdefault(src, {})[st] = n
    return out


def next_dataset_id(s: Session) -> str:
    ids = [i for i in s.scalars(select(DatasetVersion.id))]
    n = max([int(i.split("-")[1]) for i in ids if i.startswith("ds-")] or [0]) + 1
    return f"ds-{n:04d}"


def build_dataset(s: Session, *, seed: int = 42, families: list[str] | None = None,
                  sources: list[str] | None = None, max_examples: int | None = None,
                  max_self_fraction: float | None = None) -> DatasetVersion:
    """Snapshot approved examples into an immutable, hashed JSONL dataset."""
    st = get_settings()
    max_examples = min(max_examples or st.max_train_examples, st.max_train_examples)
    max_self = st.max_self_generated_fraction if max_self_fraction is None else max_self_fraction
    max_self = min(max(max_self, 0.0), st.max_self_generated_fraction)

    q = select(Example).where(Example.status == "approved")
    if families:
        q = q.where(Example.family.in_(families))
    if sources:
        q = q.where(Example.source.in_(sources))
    rows = list(s.scalars(q.order_by(Example.created_at, Example.id)))
    evalh = eval_prompt_hashes()
    excluded = Counter()
    clean = []
    for ex in rows:
        if ex.prompt_hash in evalh:
            excluded["eval_contamination"] += 1
            continue
        if ex.source in ("agent_verified",) and not ex.verified:
            excluded["unverified_self_generated"] += 1
            continue
        clean.append(ex)

    rng = random.Random(seed)
    rng.shuffle(clean)
    indep = [e for e in clean if e.source not in SELF_GENERATED]
    selfgen = [e for e in clean if e.source in SELF_GENERATED]
    if not indep and selfgen:
        raise DataError("Datensatz bestünde nur aus selbst erzeugten Beispielen – abgelehnt. "
                        "Füge unabhängige Daten hinzu (synthetisch, Lehrer, Import).")
    # self <= max_self * total  <=>  self <= max_self/(1-max_self) * indep
    cap = int(len(indep) * max_self / (1 - max_self)) if max_self < 1 else len(selfgen)
    if len(selfgen) > cap:
        excluded["self_generated_cap"] += len(selfgen) - cap
        selfgen = selfgen[:cap]
    chosen = indep + selfgen
    rng.shuffle(chosen)
    if len(chosen) > max_examples:
        excluded["size_limit"] += len(chosen) - max_examples
        chosen = chosen[:max_examples]
    if not chosen:
        raise DataError("Keine freigegebenen Beispiele vorhanden. Erzeuge zuerst Trainingsdaten.")

    ds_id = next_dataset_id(s)
    out_dir = st.datasets_dir / ds_id
    tmp_dir = st.datasets_dir / f".{ds_id}.tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for e in chosen:
        msgs = e.messages
        if not msgs or msgs[0]["role"] != "system":
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
        lines.append(json.dumps({"id": e.id, "messages": msgs + [{"role": "assistant", "content": e.response}],
                                 "source": e.source, "family": e.family}, ensure_ascii=False))
    data = ("\n".join(lines) + "\n").encode()
    sha = hashlib.sha256(data).hexdigest()
    (tmp_dir / "train.jsonl").write_bytes(data)
    counts = {"by_source": dict(Counter(e.source for e in chosen)),
              "by_family": dict(Counter(e.family or "frei" for e in chosen)),
              "excluded": dict(excluded)}
    params = {"seed": seed, "families": families, "sources": sources, "max_examples": max_examples,
              "max_self_fraction": max_self}
    manifest = {"id": ds_id, "sha256": sha, "n_examples": len(chosen), "counts": counts,
                "params": params, "created_at": utcnow().isoformat(), "system_prompt": SYSTEM_PROMPT}
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_dir.replace(out_dir)  # atomic publish
    ds = DatasetVersion(id=ds_id, path=str(out_dir / "train.jsonl"), sha256=sha, n_examples=len(chosen),
                        counts=counts, params=params)
    s.add(ds)
    audit(s, "dataset.build", id=ds_id, n=len(chosen), sha256=sha)
    s.flush()
    return ds


def load_dataset_file(path: str | Path, expected_sha: str | None = None) -> list[dict]:
    data = Path(path).read_bytes()
    if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
        raise DataError("Datensatz-Hash stimmt nicht – Datei wurde verändert!")
    return [json.loads(l) for l in data.decode().splitlines() if l.strip()]
