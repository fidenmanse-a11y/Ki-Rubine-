"""Runs the active world in a background thread and exposes developer controls.

Controls always win over anything inside the simulation: simulated laws or institutions
cannot affect start/pause/stop, speed, saving, backups, limits or model selection.
Residents have no access to real-world actions (no network, files, payments, commands).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from ..config import get_settings
from . import engine
from . import rules as R
from .genesis import create_world
from .mind import Mind
from .state import World
from .store import WorldStore

log = logging.getLogger("rubine.world2")


def _registry_path() -> Path:
    return get_settings().data_dir / "worlds" / "registry.json"


def load_registry() -> dict:
    p = _registry_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"worlds": [], "active": None}


def save_registry(reg: dict) -> None:
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def world_dir(world_id: str) -> Path:
    return get_settings().data_dir / "worlds" / world_id


class WorldService:
    def __init__(self, *, use_llm: bool = True) -> None:
        self.lock = threading.RLock()
        self.world: World | None = None
        self.store: WorldStore | None = None
        self.running = False
        self.speed = 5
        self.stopped = True
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()
        self.last_checkpoint = time.time()
        self.last_checkpoint_info: dict | None = None
        self.tick_rate = 0.0
        self.use_llm = use_llm
        self.mind: Mind | None = None
        self.paused_reason: str | None = None

    # ------------------------------------------------------------ lifecycle
    def boot(self) -> None:
        reg = load_registry()
        if not reg["active"]:
            self.new_world(name="Rubine World", seed=int(time.time()) % 100000, activate=True)
            self.stopped = False  # a brand-new world may autostart
        else:
            self._open(reg["active"])
        self._thread = threading.Thread(target=self._loop, name="rubine-world2", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.save()
        if self.mind:
            self.mind.stop()

    def _open(self, world_id: str) -> None:
        store = WorldStore(world_dir(world_id) / "world.db")
        w = store.load_latest()
        if w is None:
            raise RuntimeError(f"Welt {world_id} hat keinen Speicherstand")
        with self.lock:
            self.world, self.store = w, store
            self._attach_mind(w)
            self.speed = int(w.config.get("speed", 5))
            self.running = bool(w.config.get("running", True))
            self.stopped = not self.running

    def _attach_mind(self, w: World) -> None:
        if not self.use_llm:
            w.mind = None
            return
        if self.mind is None:
            self.mind = Mind(_make_generate(), model_for=_model_for)
            self.mind.start()
        w.mind = self.mind
        m = w.config.get("model") or {}
        for vid in [m.get("default") or ""] + [((m.get("canary") or {}).get("version")) or ""]:
            if vid.startswith("hf:") and benchmarked_hf_model(vid[3:]):
                _hf_agent.ensure(vid[3:])

    # ------------------------------------------------------------ main loop
    def _loop(self) -> None:
        last = time.time()
        count = 0
        while not self._halt.is_set():
            interval = R.SPEEDS.get(self.speed)
            if not self.running or interval is None or self.world is None:
                time.sleep(0.2)
                last, count = time.time(), 0
                continue
            t0 = time.time()
            with self.lock:
                try:
                    engine.step(self.world)
                except Exception as e:  # noqa: BLE001
                    self.world.error("engine.step", e)
                    log.exception("Fehler im Weltschritt")
                    recent = [x for x in self.world.errors if x["tick"] >= self.world.tick - 50]
                    if len(recent) >= 20:
                        self.running = False
                        self.paused_reason = "Automatisch pausiert: zu viele Fehler in kurzer Zeit (siehe Fehlerprotokoll)."
                count += 1
                if self.world.tick % 200 == 0 or time.time() - self.last_checkpoint > 30:
                    self._checkpoint()
            if time.time() - last >= 2:
                self.tick_rate = round(count / (time.time() - last), 2)
                last, count = time.time(), 0
            spent = time.time() - t0
            if interval - spent > 0:
                self._halt.wait(interval - spent)

    def _checkpoint(self) -> None:
        if self.world and self.store:
            self.world.config["speed"] = self.speed
            self.world.config["running"] = self.running
            self.last_checkpoint_info = self.store.checkpoint(self.world)
            self.last_checkpoint = time.time()

    # ------------------------------------------------------------ controls
    def save(self) -> dict | None:
        with self.lock:
            self._checkpoint()
            return self.last_checkpoint_info

    def start(self) -> None:
        self.running, self.stopped, self.paused_reason = True, False, None

    def pause(self) -> None:
        self.running = False
        self.save()

    def stop(self) -> None:
        self.running, self.stopped = False, True
        self.save()

    def set_speed(self, speed: int) -> None:
        if speed not in R.SPEEDS:
            raise ValueError("Ungültige Geschwindigkeit")
        self.speed = speed
        if speed == 0:
            self.pause()

    def backup(self) -> str:
        with self.lock:
            self._checkpoint()
            dst = world_dir(self.world.world_id) / "backups" / f"backup-{time.strftime('%Y%m%d-%H%M%S')}-t{self.world.tick}.db"
            self.store.backup(dst)
        backups = sorted(dst.parent.glob("backup-*.db"))
        for old in backups[:-10]:
            old.unlink(missing_ok=True)
        return str(dst)

    def new_world(self, *, name: str, seed: int, activate: bool = True, population: int = 25) -> dict:
        with self.lock:
            if self.world is not None:
                self._checkpoint()
            reg = load_registry()
            wid = f"w{len(reg['worlds']) + 1:03d}-{seed}"
            w = create_world(wid, name, seed, population)
            store = WorldStore(world_dir(wid) / "world.db")
            store.checkpoint(w)
            reg["worlds"].append({"id": wid, "name": name, "seed": seed, "created": time.time()})
            if activate:
                reg["active"] = wid
                self.world, self.store = w, store
                self._attach_mind(w)
                self.running, self.stopped = False, True
            save_registry(reg)
            return {"id": wid, "name": name, "seed": seed}

    def switch(self, world_id: str) -> None:
        reg = load_registry()
        if world_id not in {x["id"] for x in reg["worlds"]}:
            raise ValueError("Unbekannte Welt")
        with self.lock:
            self._checkpoint()
            self._open(world_id)
            self.running, self.stopped = False, True
            reg["active"] = world_id
            save_registry(reg)

    def set_limits(self, *, max_population: int | None = None, max_memories: int | None = None,
                   calls_per_agent_day: int | None = None, llm_enabled: bool | None = None, llm_mode: str | None = None,
                   timeout_ticks: int | None = None) -> dict:
        with self.lock:
            cfg = self.world.config
            if max_population is not None:
                cfg["max_population"] = max(10, min(500, int(max_population)))
            if max_memories is not None:
                cfg["max_memories"] = max(50, min(2000, int(max_memories)))
            llm = cfg.setdefault("llm", {})
            if calls_per_agent_day is not None:
                llm["calls_per_agent_day"] = max(0, min(50, int(calls_per_agent_day)))
            if llm_enabled is not None:
                llm["enabled"] = bool(llm_enabled)
            if llm_mode in ("async", "blocking"):
                llm["mode"] = llm_mode
            if timeout_ticks is not None:
                llm["timeout_ticks"] = max(1, min(48, int(timeout_ticks)))
            return {k: cfg[k] for k in ("max_population", "max_memories", "llm")}

    def set_model_policy(self, default: str, canary_version: str | None, canary_agents: list[str]) -> dict:
        """Only tested versions (base or 'passed') may think for residents; a canary group limits rollout."""
        from ..db import ModelVersion, session_scope
        from ..llm.registry import CHAT_STATUSES
        with session_scope() as s:
            for vid in [default] + ([canary_version] if canary_version else []):
                if vid.startswith("hf:"):
                    # a larger open-weight base model for residents: allowed only if listed and benchmarked
                    if not benchmarked_hf_model(vid[3:]):
                        raise ValueError(f"{vid[3:]} ist nicht freigegeben oder hat noch keinen Bewohner-Test bestanden.")
                    continue
                v = s.get(ModelVersion, vid)
                if v is None or v.status not in CHAT_STATUSES:
                    raise ValueError(f"Version {vid} ist nicht getestet/freigegeben und darf Agenten nicht steuern.")
        with self.lock:
            w = self.world
            agents = [a for a in canary_agents if a in w.agents][:8]
            for vid in [default] + ([canary_version] if canary_version else []):
                if vid.startswith("hf:"):
                    _hf_agent.ensure(vid[3:])  # start loading in the background now
            w.config["model"] = {"default": default,
                                 "canary": {"version": canary_version, "agents": agents} if canary_version and agents else None}
            w.emit("system", "modellrichtlinie", f"Entwickler: Agenten-Modell {default}" +
                   (f", Testgruppe {len(agents)} Agenten mit {canary_version}" if canary_version and agents else "") + ".",
                   witnesses=False)
            return w.config["model"]

    def status(self) -> dict:
        w = self.world
        reg = load_registry()
        return {"world": {"id": w.world_id, "name": w.name, "seed": w.seed, "tick": w.tick, "calendar": w.calendar()} if w else None,
                "running": self.running, "stopped": self.stopped, "speed": self.speed, "speeds": list(R.SPEEDS),
                "target_tick_rate": round(1 / R.SPEEDS[self.speed], 2) if R.SPEEDS.get(self.speed) else 0,
                "tick_rate": self.tick_rate, "paused_reason": self.paused_reason,
                "last_checkpoint": self.last_checkpoint_info, "last_checkpoint_age_s": round(time.time() - self.last_checkpoint, 1),
                "worlds": reg["worlds"], "active": reg["active"],
                "mind": ({**self.mind.stats, "available": self.mind.available(), "queue": self.mind.q.qsize(),
                          "last_error": self.mind.last_error} if self.mind else {"available": False}),
                "config": {k: w.config.get(k) for k in ("max_population", "max_memories", "llm", "model")} if w else None,
                "errors": len(w.errors) if w else 0}


def _model_for(w: World, a: dict) -> str:
    m = w.config.get("model") or {}
    can = m.get("canary")
    if can and a["id"] in can.get("agents", []):
        return can["version"]
    return m.get("default", "base")


def benchmarked_hf_model(name: str) -> dict | None:
    """Return the stored resident-benchmark result for an allowed larger model if it beats chance clearly."""
    settings = get_settings()
    if name not in settings.agent_bench_models:
        return None
    d = settings.eval_dir / "agent_bench"
    best = None
    for f in d.glob(f"{name.replace('/', '_')}-*.json") if d.exists() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if r.get("accuracy", 0) >= r.get("chance", 1) + 0.15 and (best is None or r["accuracy"] > best["accuracy"]):
            best = r
    return best


class _HFAgentModel:
    """Separately loaded larger base model for residents (CPU/GPU memory permitting). Loaded lazily, one at a time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.gen = None
        self.error: str | None = None
        self.loading = False

    def ensure(self, name: str) -> bool:
        if self.name == name and self.gen is not None:
            return True
        if self.loading:
            return False
        self.loading = True

        def load() -> None:
            try:
                from .benchmark import hf_generator
                gen, _ = hf_generator(name, revision=get_settings().agent_bench_models.get(name), max_new_tokens=60)
                self.gen, self.name, self.error = gen, name, None
            except Exception as e:  # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"
                log.warning("Agentenmodell %s konnte nicht geladen werden: %s", name, e)
            finally:
                self.loading = False
        threading.Thread(target=load, daemon=True, name="rubine-agent-model").start()
        return False

    def generate(self, name: str, system: str, user: str, max_tokens: int | None = None,
                 history: list[dict] | None = None) -> str | None:
        if not self.ensure(name):
            return None  # still loading -> the rules decide meanwhile
        with self.lock:
            return self.gen(system, user, max_tokens, history)


_hf_agent = _HFAgentModel()


def _make_generate():
    """Language access for residents through the shared Rubine engine (chat keeps priority)."""
    from ..db import ModelVersion, session_scope
    from ..llm.engine import get_engine
    cache: dict[str, tuple[float, str | None]] = {}

    def adapter(version: str) -> str | None:
        hit = cache.get(version)
        if hit and time.time() - hit[0] < 30:
            return hit[1]
        with session_scope() as s:
            v = s.get(ModelVersion, version)
            path = v.adapter_path if v else None
        cache[version] = (time.time(), path)
        return path

    def generate(version: str, system: str, user: str, max_tokens: int, temp: float) -> str | None:
        if version.startswith("hf:"):
            return _hf_agent.generate(version[3:], system, user)
        eng = get_engine()
        if eng.status != "ready":
            raise RuntimeError(f"Sprachmodell nicht bereit ({eng.status})")
        return eng.generate([{"role": "user", "content": user}], version_id=version, adapter_path=adapter(version),
                            max_new_tokens=max_tokens, temperature=temp, system=system, background=True, wait_timeout=1.0)

    def ready() -> bool:
        # the chat engine, or a separately loaded larger resident model, can answer
        return get_engine().status == "ready" or _hf_agent.gen is not None

    generate.ready = ready  # type: ignore[attr-defined]
    return generate


_service: WorldService | None = None


def get_service() -> WorldService:
    global _service
    if _service is None:
        _service = WorldService()
    return _service


def set_service(s: WorldService | None) -> None:
    global _service
    _service = s
