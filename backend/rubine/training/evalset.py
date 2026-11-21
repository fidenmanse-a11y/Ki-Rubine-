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


def ensure_eval_set(eval_id: str = EVAL_SET_ID) -> tuple[Path, str]:
    path = eval_path(eval_id)
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


def load_eval_set(eval_id: str = EVAL_SET_ID) -> tuple[list[dict], str]:
    path, sha = ensure_eval_set(eval_id)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()], sha


@lru_cache
def eval_prompt_hashes(eval_id: str = EVAL_SET_ID) -> frozenset[str]:
    items, _ = load_eval_set(eval_id)
    return frozenset(cur.prompt_hash(t["prompt"]) for t in items)
