"""Command line tools: ``python -m rubine.cli <command>`` (run inside backend/).

Commands
  import-data FILE [--approve]   import JSONL training data (e.g. written by Claude Code)
  import-seed NAME               import a file from data/seed/ (approved)
  synthetic N [--seed S]         add N verified synthetic tasks
  build-dataset [--seed S]       snapshot approved examples into a versioned dataset
  status                         print versions, datasets, example pool
  backup                         SQLite backup into data/backups/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .config import REPO_ROOT
from .db import DatasetVersion, ModelVersion, backup_sqlite, init_db, session_scope
from .llm import registry
from .training import data as D


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rubine.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import-data"); p.add_argument("file"); p.add_argument("--approve", action="store_true")
    p = sub.add_parser("import-seed"); p.add_argument("name")
    p = sub.add_parser("synthetic"); p.add_argument("n", type=int); p.add_argument("--seed", type=int, default=1)
    p = sub.add_parser("build-dataset"); p.add_argument("--seed", type=int, default=42)
    sub.add_parser("status")
    sub.add_parser("backup")
    a = ap.parse_args(argv)
    init_db()
    with session_scope() as s:
        registry.ensure_base_version(s)
        if a.cmd == "import-data":
            r = D.import_jsonl(s, Path(a.file).read_text(encoding="utf-8").splitlines(), approve=a.approve,
                               origin=f"cli:{Path(a.file).name}")
        elif a.cmd == "import-seed":
            r = D.import_jsonl(s, (REPO_ROOT / "data" / "seed" / a.name).read_text(encoding="utf-8").splitlines(),
                               approve=True, origin=f"seed:{a.name}")
        elif a.cmd == "synthetic":
            r = D.add_synthetic(s, a.n, a.seed)
        elif a.cmd == "build-dataset":
            ds = D.build_dataset(s, seed=a.seed)
            r = {"id": ds.id, "n": ds.n_examples, "sha256": ds.sha256, "counts": ds.counts}
        elif a.cmd == "status":
            r = {"active": registry.active_version_id(s),
                 "versions": [(v.id, v.status) for v in s.scalars(select(ModelVersion))],
                 "datasets": [(d.id, d.n_examples) for d in s.scalars(select(DatasetVersion))],
                 "pool": D.pool_counts(s)}
        else:
            r = {"backup": str(backup_sqlite("cli"))}
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
