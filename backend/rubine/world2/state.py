"""World state container, ID generation, conserved ledger, event log, memory and knowledge primitives.

Invariants enforced here:
  * Items only change through `produce` (from a documented natural source or process),
    `consume` (documented sink) or `transfer` (between holders). Quantities are integers
    and can never become negative.  `audit()` checks conservation.
  * Every event gets a stable, monotonically increasing integer id and may point to its cause.
"""
from __future__ import annotations

import base64
import io
import math
import random
from collections import Counter, deque
from typing import Any

import numpy as np

from . import rules as R

MAP_ARRAYS = ["terrain", "elev", "moist", "wood", "stone", "fish", "forage", "herbs", "fertility", "region",
              "wood_cap", "fish_cap", "forage_cap", "herbs_cap", "clearing_age", "flooded", "road", "bridge"]


class LedgerError(ValueError):
    pass


class World:
    def __init__(self) -> None:
        self.world_id = ""
        self.name = ""
        self.seed = 0
        self.tick = 0
        self.rng = random.Random(0)
        self.counters: Counter = Counter()
        self.map: dict[str, np.ndarray] = {}
        self.w = self.h = 0
        self.region_names: list[str] = []
        self.agents: dict[str, dict] = {}
        self.buildings: dict[str, dict] = {}
        self.sites: dict[str, dict] = {}
        self.institutions: dict[str, dict] = {}
        self.laws: dict[str, dict] = {}
        self.proposals: dict[str, dict] = {}
        self.contracts: dict[str, dict] = {}
        self.currencies: dict[str, dict] = {}
        self.cases: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        self.artworks: dict[str, dict] = {}
        self.settlements: dict[str, dict] = {}
        self.traditions: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.markets: dict[str, dict] = {}       # region index (str) -> item -> price info
        self.weather: dict[str, dict] = {}       # region index (str) -> weather
        self.river_level = 0.3
        self.ledger = {"produced": Counter(), "consumed": Counter(), "initial": Counter()}
        self.config: dict[str, Any] = {}
        self.daily: Counter = Counter()          # per-day counters for statistics
        self.totals: Counter = Counter()         # cumulative counters (births, deaths, crimes ...)
        # buffers flushed to the store at checkpoints
        self.event_buffer: list[dict] = []
        self.archive_buffer: list[dict] = []
        self.decision_buffer: list[dict] = []
        self.stats_buffer: list[dict] = []
        self.recent_events: deque[dict] = deque(maxlen=400)
        self.errors: deque[dict] = deque(maxlen=100)
        self.version = 0  # bumps on every tick for live views
        self.mind = None  # set by the service (language model access); None = rules only

    # ------------------------------------------------------------ ids & time
    def new_id(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}{self.counters[prefix]:04d}"

    @property
    def day(self) -> int:
        return self.tick // R.TICKS_PER_DAY

    @property
    def hour(self) -> int:
        return (R.START_HOUR + (self.tick % R.TICKS_PER_DAY) // R.TICKS_PER_HOUR) % 24

    @property
    def minute(self) -> int:
        return (self.tick % R.TICKS_PER_HOUR) * R.TICK_MINUTES

    def calendar(self, tick: int | None = None) -> dict:
        t = self.tick if tick is None else tick
        day = t // R.TICKS_PER_DAY
        year = day // R.DAYS_PER_YEAR + 1
        doy = day % R.DAYS_PER_YEAR
        season = doy // R.DAYS_PER_SEASON
        hour = (R.START_HOUR + (t % R.TICKS_PER_DAY) // R.TICKS_PER_HOUR) % 24
        minute = (t % R.TICKS_PER_HOUR) * R.TICK_MINUTES
        return {"year": year, "season": season, "season_name": R.SEASONS[season], "day_of_season": doy % R.DAYS_PER_SEASON + 1,
                "day": day, "hour": hour, "minute": minute,
                "label": f"Jahr {year}, {R.SEASONS[season]} Tag {doy % R.DAYS_PER_SEASON + 1}, {hour:02d}:{minute:02d}"}

    @property
    def season(self) -> int:
        return (self.day % R.DAYS_PER_YEAR) // R.DAYS_PER_SEASON

    def is_night(self) -> bool:
        return self.hour >= 22 or self.hour < 6

    def age(self, a: dict) -> float:
        return (self.tick - a["birth_tick"]) / R.TICKS_PER_YEAR

    # ------------------------------------------------------------ map helpers
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def terrain(self, x: int, y: int) -> str:
        from .mapgen import TERRAIN_CODES
        return TERRAIN_CODES[int(self.map["terrain"][y, x])]

    def region_of(self, x: int, y: int) -> int:
        return int(self.map["region"][y, x])

    def region_name(self, r: int | None) -> str:
        return self.region_names[r] if r is not None and 0 <= r < len(self.region_names) else "—"

    def passable(self, x: int, y: int) -> bool:
        from .mapgen import T
        t = int(self.map["terrain"][y, x])
        if t in (T["water"], T["river"]):
            return bool(self.map["bridge"][y, x])
        return True

    def near_water(self, x: int, y: int, r: int = 1) -> bool:
        from .mapgen import T
        x0, x1, y0, y1 = max(0, x - r), min(self.w, x + r + 1), max(0, y - r), min(self.h, y + r + 1)
        sub = self.map["terrain"][y0:y1, x0:x1]
        if ((sub == T["water"]) | (sub == T["river"])).any():
            return True
        return any(b["type"] == "brunnen" and b["condition"] > 0.2 and abs(b["x"] - x) <= r and abs(b["y"] - y) <= r
                   for b in self.buildings.values())

    # ------------------------------------------------------------ ledger (conservation)
    def _holder(self, ref: tuple[str, str]) -> dict:
        kind, hid = ref
        obj = {"agent": self.agents, "building": self.buildings, "site": self.sites, "inst": self.institutions}[kind][hid]
        return obj.setdefault("inv", {})

    def qty(self, ref: tuple[str, str], item: str) -> int:
        return int(self._holder(ref).get(item, 0))

    def produce(self, ref: tuple[str, str], item: str, n: int, source: str) -> int:
        """Create items from a documented source (tile stock, crafting process, minting rule)."""
        if n <= 0:
            return 0
        inv = self._holder(ref)
        inv[item] = int(inv.get(item, 0)) + int(n)
        self.ledger["produced"][item] += int(n)
        self.daily[f"prod:{item}"] += int(n)
        return n

    def consume(self, ref: tuple[str, str], item: str, n: int, reason: str) -> None:
        inv = self._holder(ref)
        have = int(inv.get(item, 0))
        if n < 0 or have < n:
            raise LedgerError(f"Verbrauch von {n} {item} nicht möglich (vorhanden {have}, Grund {reason})")
        inv[item] = have - n
        if inv[item] == 0:
            inv.pop(item)
        self.ledger["consumed"][item] += int(n)
        self.daily[f"cons:{item}"] += int(n)

    def transfer(self, src: tuple[str, str], dst: tuple[str, str], item: str, n: int) -> None:
        if n <= 0:
            return
        a, b = self._holder(src), self._holder(dst)
        have = int(a.get(item, 0))
        if have < n:
            raise LedgerError(f"Übertragung von {n} {item} nicht möglich (vorhanden {have})")
        a[item] = have - n
        if a[item] == 0:
            a.pop(item)
        b[item] = int(b.get(item, 0)) + n

    def all_holdings(self) -> Counter:
        total: Counter = Counter()
        for coll in (self.agents, self.buildings, self.sites, self.institutions):
            for obj in coll.values():
                for k, v in (obj.get("inv") or {}).items():
                    total[k] += int(v)
        return total

    def audit(self) -> dict:
        hold = self.all_holdings()
        items = set(hold) | set(self.ledger["produced"]) | set(self.ledger["consumed"]) | set(self.ledger["initial"])
        bad = {}
        for it in items:
            expect = self.ledger["initial"][it] + self.ledger["produced"][it] - self.ledger["consumed"][it]
            if expect != hold[it]:
                bad[it] = {"expected": expect, "actual": hold[it]}
        neg = [(k, i, v) for coll in (self.agents, self.buildings, self.sites, self.institutions)
               for k, obj in coll.items() for i, v in (obj.get("inv") or {}).items() if v < 0]
        return {"ok": not bad and not neg, "mismatch": bad, "negative": neg}

    # ------------------------------------------------------------ events
    def emit(self, cat: str, kind: str, text: str, *, actors: list[str] | None = None, x: int | None = None,
             y: int | None = None, data: dict | None = None, cause: int | None = None, public: bool = True,
             witnesses: bool = True) -> int:
        self.counters["event"] += 1
        eid = self.counters["event"]
        region = self.region_of(x, y) if x is not None and y is not None else None
        ev = {"id": eid, "tick": self.tick, "cat": cat, "kind": kind, "text": text, "actors": actors or [],
              "x": x, "y": y, "region": region, "data": data or {}, "cause": cause, "public": public}
        self.event_buffer.append(ev)
        self.recent_events.append(ev)
        if data and "offender" in data:
            self.config.setdefault("_eventdata", {})[str(eid)] = data
        self.daily[f"ev:{kind}"] += 1
        if witnesses and x is not None and public:
            for a in self.agents_near(x, y, 6):
                if a["id"] in (actors or []) or a.get("asleep"):
                    continue
                self.learn(a, f"ev:{eid}", "event", text, "beobachtet", 1.0, ref=eid)
        return eid

    # ------------------------------------------------------------ agents
    def living(self) -> list[dict]:
        return [a for a in self.agents.values() if a["alive"]]

    def adults(self, region: int | None = None) -> list[dict]:
        out = [a for a in self.living() if self.age(a) >= R.ADULT_AGE]
        if region is not None:
            out = [a for a in out if self.home_region(a) == region]
        return out

    def home_region(self, a: dict) -> int:
        h = self.buildings.get(a.get("home") or "")
        if h:
            return self.region_of(h["x"], h["y"])
        return self.region_of(a["x"], a["y"])

    def agents_near(self, x: int, y: int, r: int) -> list[dict]:
        return [a for a in self.agents.values() if a["alive"] and abs(a["x"] - x) <= r and abs(a["y"] - y) <= r]

    # ------------------------------------------------------------ memory (forgetting via strength)
    def remember(self, a: dict, kind: str, text: str, importance: float, *, event: int | None = None,
                 subjects: list[str] | None = None, tags: list[str] | None = None) -> None:
        m = {"t": self.tick, "k": kind, "x": text[:400], "imp": round(float(importance), 2), "s": float(importance),
             "e": event, "who": subjects or [], "tags": tags or []}
        a["stm"].append(m)
        if len(a["stm"]) > 15:
            a["stm"].pop(0)
        if importance >= 3 or kind in ("reflexion", "biografie"):
            a["ltm"].append(dict(m, tags=list(m["tags"]), who=list(m["who"])))
            cap = int(self.config.get("max_memories", 250))
            if len(a["ltm"]) > cap:
                a["ltm"].sort(key=lambda z: z["s"])
                for old in a["ltm"][: len(a["ltm"]) - cap]:
                    self._archive(a, old, "kapazitaet")
                a["ltm"] = a["ltm"][len(a["ltm"]) - cap:]
                a["ltm"].sort(key=lambda z: z["t"])

    def _archive(self, a: dict, m: dict, why: str) -> None:
        self.archive_buffer.append({"agent_id": a["id"], "tick": m["t"], "kind": m["k"], "text": m["x"],
                                    "importance": m["imp"], "reason": why})

    def decay_memories(self, a: dict) -> None:
        """Daily forgetting: strength decays slower for important memories; faded ones are archived."""
        keep = []
        for m in a["ltm"]:
            rate = 0.90 + 0.095 * min(1.0, m["imp"] / 10)
            m["s"] = round(m["s"] * rate, 4)
            if m["s"] < 0.6 and m["k"] not in ("biografie",):
                self._archive(a, m, "vergessen")
            else:
                keep.append(m)
        a["ltm"] = keep

    def recall(self, a: dict, query_words: set[str], k: int = 5) -> list[dict]:
        scored = []
        for m in a["ltm"]:
            hours = (self.tick - m["t"]) / R.TICKS_PER_HOUR
            rec = 0.995 ** hours
            words = set(m["x"].lower().split())
            rel = len(words & query_words) / (1 + len(query_words))
            scored.append((rec + m["s"] / 10 + 2 * rel, m))
        scored.sort(key=lambda z: z[0], reverse=True)
        out = [m for _, m in scored[:k]]
        for m in out:
            m["s"] = min(m["imp"] * 1.2 + 1, m["s"] + 0.3)  # retrieval strengthens
        return out

    # ------------------------------------------------------------ knowledge (who knows what, from where)
    def learn(self, a: dict, key: str, kind: str, text: str, source: str, conf: float, *, ref: Any = None,
              frm: str | None = None) -> bool:
        f = a["facts"].get(key)
        if f and f["conf"] >= conf:
            return False
        a["facts"][key] = {"k": kind, "x": text[:300], "src": source, "conf": round(conf, 2), "t": self.tick,
                           "ref": ref, "from": frm}
        if len(a["facts"]) > 160:
            oldest = sorted(a["facts"].items(), key=lambda kv: (kv[1]["k"] == "law", kv[1]["conf"], kv[1]["t"]))[:20]
            for k2, _ in oldest:
                a["facts"].pop(k2, None)
        return True

    def knows(self, a: dict, key: str) -> bool:
        return key in a["facts"]

    # ------------------------------------------------------------ relations (directed: a's view of b)
    def rel(self, a_id: str, b_id: str) -> dict:
        key = f"{a_id}>{b_id}"
        r = self.relations.get(key)
        if r is None:
            r = {"trust": 0.5, "affection": 0.5, "respect": 0.5, "familiarity": 0.0, "hist": [], "last": self.tick}
            self.relations[key] = r
        return r

    def adjust_rel(self, a_id: str, b_id: str, *, trust: float = 0, affection: float = 0, respect: float = 0,
                   familiarity: float = 0, note: str | None = None, event: int | None = None) -> None:
        """Bounded change: a single interaction moves a dimension by at most 0.12.
        Changes shrink with familiarity, so long histories weigh more than single moments."""
        r = self.rel(a_id, b_id)
        inertia = 1.0 / (1.0 + 2.0 * r["familiarity"])
        for k, v in (("trust", trust), ("affection", affection), ("respect", respect)):
            r[k] = float(min(1.0, max(0.0, r[k] + max(-0.12, min(0.12, v)) * inertia)))
        r["familiarity"] = float(min(1.0, r["familiarity"] + familiarity))
        r["last"] = self.tick
        if note:
            r["hist"].append([self.tick, note, event])
            r["hist"] = r["hist"][-12:]

    # ------------------------------------------------------------ helpers
    def chance(self, p: float) -> bool:
        return self.rng.random() < max(0.0, min(1.0, p))

    def error(self, where: str, exc: BaseException) -> None:
        import traceback
        self.errors.append({"tick": self.tick, "where": where, "error": f"{type(exc).__name__}: {exc}",
                            "trace": traceback.format_exc()[-2000:]})


# ------------------------------------------------------------------ serialization
def _arr_to_b64(a: np.ndarray) -> str:
    buf = io.BytesIO()
    np.save(buf, a, allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode()


def _b64_to_arr(s: str) -> np.ndarray:
    return np.load(io.BytesIO(base64.b64decode(s)), allow_pickle=False)


SIMPLE_FIELDS = ["world_id", "name", "seed", "tick", "w", "h", "region_names", "agents", "buildings", "sites",
                 "institutions", "laws", "proposals", "contracts", "currencies", "cases", "documents", "artworks",
                 "settlements", "traditions", "relations", "markets", "weather", "river_level", "config"]


def to_snapshot(w: World) -> dict:
    d = {k: getattr(w, k) for k in SIMPLE_FIELDS}
    d["counters"] = dict(w.counters)
    d["ledger"] = {k: dict(v) for k, v in w.ledger.items()}
    d["totals"] = dict(w.totals)
    d["daily"] = dict(w.daily)
    d["rng"] = repr(w.rng.getstate())
    d["map"] = {k: _arr_to_b64(v) for k, v in w.map.items()}
    return d


def from_snapshot(d: dict) -> World:
    import ast
    w = World()
    for k in SIMPLE_FIELDS:
        setattr(w, k, d[k])
    w.counters = Counter(d["counters"])
    w.ledger = {k: Counter(v) for k, v in d["ledger"].items()}
    w.totals = Counter(d.get("totals", {}))
    w.daily = Counter(d.get("daily", {}))
    w.rng.setstate(ast.literal_eval(d["rng"]))
    w.map = {k: _b64_to_arr(v) for k, v in d["map"].items()}
    return w


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def dist(ax: int, ay: int, bx: int, by: int) -> int:
    return abs(ax - bx) + abs(ay - by)


__all__ = ["World", "LedgerError", "to_snapshot", "from_snapshot", "clamp", "dist", "math"]
