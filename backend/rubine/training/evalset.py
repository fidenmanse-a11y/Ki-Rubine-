"""The frozen, held-out evaluation set.

Generated once from a separate seed namespace, written to disk, hashed and
never used for training (dataset builds exclude every prompt in it).
"""
from __future__ import annotations

import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from . import curriculum as cur

EVAL_SET_ID = "eval-v1"
_DIFFICULTY = {1: 0.5, 2: 0.3, 3: 0.2}


def eval_path(eval_id: str = EVAL_SET_ID) -> Path:
    return get_settings().eval_dir / f"{eval_id}.jsonl"


def configured_sets() -> list[str]:
    return [x.strip() for x in get_settings().eval_sets.split(",") if x.strip()] or [EVAL_SET_ID]


def combined_id() -> str:
    return "+".join(configured_sets())


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_eval_set(eval_id: str = EVAL_SET_ID) -> tuple[Path, str]:
    path = eval_path(eval_id)
    if not path.exists() and eval_id.startswith("eval-sim"):
        from ..world2.export import build_sim_eval
        st = get_settings()
        _write(path, build_sim_eval(n=st.eval_sim_size, days=st.eval_sim_days))
        eval_prompt_hashes.cache_clear()
    if not path.exists():
        n = get_settings().eval_set_size
        fams = sorted(cur.FAMILIES)
        rng = random.Random(f"rubine-{eval_id}")
        tasks, seen = [], set()
        i = 0
        while len(tasks) < n and i < n * 100:
            fam = fams[len(tasks) % len(fams)]  # balanced over families
            d = rng.choices(list(_DIFFICULTY), weights=list(_DIFFICULTY.values()))[0]
            t = cur.FAMILIES[fam](rng, d)
            i += 1
            if t.prompt_hash in seen:
                continue
            seen.add(t.prompt_hash)
            tasks.append(t)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(t.to_dict(), ensure_ascii=False) for t in tasks) + "\n",
                       encoding="utf-8")
        tmp.replace(path)
        eval_prompt_hashes.cache_clear()
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load_one(eval_id: str) -> tuple[list[dict], str]:
    path, sha = ensure_eval_set(eval_id)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()], sha


def load_eval_set() -> tuple[list[dict], str]:
    """All configured frozen sets combined; the hash identifies the exact combination."""
    items, shas = [], []
    for sid in configured_sets():
        rows, sha = load_one(sid)
        items += rows
        shas.append(sha)
    combined = shas[0] if len(shas) == 1 else hashlib.sha256("|".join(shas).encode()).hexdigest()
    return items, combined


def eval_set_info() -> list[dict]:
    out = []
    for sid in configured_sets():
        rows, sha = load_one(sid)
        fams: dict[str, int] = {}
        for r in rows:
            fams[r["family"]] = fams.get(r["family"], 0) + 1
        out.append({"id": sid, "sha256": sha, "n": len(rows), "families": fams})
    return out


@lru_cache
def eval_prompt_hashes() -> frozenset[str]:
    items, _ = load_eval_set()
    return frozenset(cur.prompt_hash(t["prompt"]) for t in items)
