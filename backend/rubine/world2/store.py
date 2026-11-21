"""Persistence for one world: its own SQLite file (portable; backups are file copies).

A checkpoint writes, in ONE transaction: new events, archived memories, decision logs,
daily statistics and a compressed snapshot of the full world state. After a crash the
world resumes from the last checkpoint with a consistent event log.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path

from .state import World, from_snapshot, to_snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER, created REAL, data BLOB);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, tick INTEGER, cat TEXT, kind TEXT, region INTEGER,
    x INTEGER, y INTEGER, actors TEXT, data TEXT, cause INTEGER, text TEXT, public INTEGER);
CREATE INDEX IF NOT EXISTS ix_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS ix_events_cat ON events(cat);
CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS ix_events_region ON events(region);
CREATE TABLE IF NOT EXISTS event_actors (event_id INTEGER, agent_id TEXT);
CREATE INDEX IF NOT EXISTS ix_event_actors ON event_actors(agent_id, event_id);
CREATE TABLE IF NOT EXISTS memory_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, tick INTEGER, kind TEXT,
    text TEXT, importance REAL, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_mem_agent ON memory_archive(agent_id);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY, tick INTEGER, agent_id TEXT, kind TEXT, by TEXT, model TEXT,
    options TEXT, chosen TEXT, why TEXT);
CREATE INDEX IF NOT EXISTS ix_dec_agent ON decisions(agent_id, tick);
CREATE INDEX IF NOT EXISTS ix_dec_model ON decisions(model);
CREATE TABLE IF NOT EXISTS stats (day INTEGER PRIMARY KEY, data TEXT);
"""


class WorldStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    # ------------------------------------------------------------ write
    def checkpoint(self, w: World, keep_snapshots: int = 5) -> dict:
        t0 = time.time()
        events, archive, decisions, stats = w.event_buffer, w.archive_buffer, w.decision_buffer, w.stats_buffer
        snap = zlib.compress(json.dumps(to_snapshot(w), separators=(",", ":"), default=_default).encode(), 6)
        with self._lock, self._conn() as c:
            c.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          [(e["id"], e["tick"], e["cat"], e["kind"], e["region"], e["x"], e["y"], json.dumps(e["actors"]),
                            json.dumps(e["data"], default=_default), e["cause"], e["text"], int(e["public"])) for e in events])
            c.executemany("INSERT INTO event_actors VALUES (?,?)", [(e["id"], aid) for e in events for aid in e["actors"] if aid])
            c.executemany("INSERT INTO memory_archive (agent_id, tick, kind, text, importance, reason) VALUES (?,?,?,?,?,?)",
                          [(m["agent_id"], m["tick"], m["kind"], m["text"], m["importance"], m["reason"]) for m in archive])
            c.executemany("INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                          [(d["id"], d["t"], d["agent"], d["kind"], d["by"], d["model"], json.dumps(d["options"]), d["chosen"],
                            d["why"]) for d in decisions])
            c.executemany("INSERT OR REPLACE INTO stats VALUES (?,?)", [(s["day"], json.dumps(s, default=_default)) for s in stats])
            c.execute("INSERT INTO snapshots (tick, created, data) VALUES (?,?,?)", (w.tick, time.time(), snap))
            c.execute("DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)", (keep_snapshots,))
            c.execute("INSERT OR REPLACE INTO meta VALUES ('world', ?)", (json.dumps({"id": w.world_id, "name": w.name, "seed": w.seed,
                                                                                    "tick": w.tick}),))
        n = {"events": len(events), "archive": len(archive), "decisions": len(decisions), "stats": len(stats),
             "snapshot_kb": round(len(snap) / 1024, 1), "seconds": round(time.time() - t0, 3)}
        w.event_buffer, w.archive_buffer, w.decision_buffer, w.stats_buffer = [], [], [], []
        return n

    # ------------------------------------------------------------ read
    def load_latest(self) -> World | None:
        with self._conn() as c:
            row = c.execute("SELECT data FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        w = from_snapshot(json.loads(zlib.decompress(row[0])))
        # recent events for live views
        for e in reversed(self.events(limit=200)):
            w.recent_events.append(e)
        return w

    def events(self, *, cat: str | None = None, kind: str | None = None, region: int | None = None, agent: str | None = None,
               before: int | None = None, after: int | None = None, limit: int = 100, public_only: bool = False) -> list[dict]:
        q = "SELECT e.* FROM events e"
        args: list = []
        where = []
        if agent:
            q += " JOIN event_actors ea ON ea.event_id = e.id"
            where.append("ea.agent_id = ?")
            args.append(agent)
        for col, val in (("cat", cat), ("kind", kind), ("region", region)):
            if val is not None:
                if col == "kind" and "," in str(val):
                    kinds = str(val).split(",")
                    where.append(f"e.kind IN ({','.join('?' * len(kinds))})")
                    args += kinds
                else:
                    where.append(f"e.{col} = ?")
                    args.append(val)
        if before is not None:
            where.append("e.id < ?")
            args.append(before)
        if after is not None:
            where.append("e.id > ?")
            args.append(after)
        if public_only:
            where.append("e.public = 1")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY e.id DESC LIMIT ?"
        args.append(min(int(limit), 1000))
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"id": r[0], "tick": r[1], "cat": r[2], "kind": r[3], "region": r[4], "x": r[5], "y": r[6],
                 "actors": json.loads(r[7]), "data": json.loads(r[8]), "cause": r[9], "text": r[10], "public": bool(r[11])}
                for r in rows]

    def event(self, eid: int) -> dict | None:
        r = self.events(before=eid + 1, after=eid - 1, limit=1)
        return r[0] if r else None

    def stats(self, limit: int = 400) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT data FROM stats ORDER BY day DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def decisions(self, agent: str | None = None, limit: int = 50, model: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM decisions", []
        conds = []
        if agent:
            conds.append("agent_id = ?")
            args.append(agent)
        if model:
            conds.append("model = ?")
            args.append(model)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [{"id": r[0], "t": r[1], "agent": r[2], "kind": r[3], "by": r[4], "model": r[5], "options": json.loads(r[6]),
                 "chosen": r[7], "why": r[8]} for r in rows]

    def model_usage(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT COALESCE(model,'regeln'), by, COUNT(*), MIN(tick), MAX(tick) FROM decisions "
                             "GROUP BY model, by ORDER BY 3 DESC").fetchall()
        return [{"model": r[0], "by": r[1], "count": r[2], "first_tick": r[3], "last_tick": r[4]} for r in rows]

    def archived_memories(self, agent: str, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT tick, kind, text, importance, reason FROM memory_archive WHERE agent_id = ? "
                             "ORDER BY importance DESC, tick DESC LIMIT ?", (agent, limit)).fetchall()
        return [{"t": r[0], "k": r[1], "x": r[2], "imp": r[3], "reason": r[4]} for r in rows]

    def counts(self) -> dict:
        with self._conn() as c:
            return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("events", "memory_archive", "decisions", "stats", "snapshots")}

    def backup(self, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            src = sqlite3.connect(self.path)
            out = sqlite3.connect(dst)
            try:
                src.backup(out)
            finally:
                out.close()
                src.close()
        return dst


def _default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))
