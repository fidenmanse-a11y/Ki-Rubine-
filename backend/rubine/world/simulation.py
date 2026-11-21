"""Rubine World – a server-side generative-agent simulation.

* 25 agents with persona, goals, schedule, long-term memory, reflections and a daily plan.
* Agents move between locations following their (plan-driven) schedule.
* Language (conversations, plans, reflections, task solutions, reviews) is produced
  by a real language model – by default the *active Rubine model*. If no model is
  available, agents still move, but no text is invented.
* Task workshops: a team solves a curriculum task independently, a reviewer compares
  the proposals, and the Prüflabor verifies them against ground truth. Only verified
  correct solutions become training examples (source ``agent_verified``).
"""
from __future__ import annotations

import asyncio
import hashlib
import heapq
import itertools
import logging
import math
import random
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from sqlalchemy import select

from ..config import get_settings
from ..db import AgentRow, EvalRun, ModelVersion, WorldEvent, WorldTask, session_scope
from ..llm import registry
from ..llm.engine import EngineUnavailable, get_engine
from ..security.sanitize import UNTRUSTED_NOTICE, sanitize_text, wrap_untrusted
from ..training import curriculum as cur
from ..training import data as data_mod
from ..training.evalset import eval_prompt_hashes
from . import memory as mem
from .town import HEIGHT, LOC, LOCATIONS, PERSONA, PERSONAS, WIDTH, Persona

log = logging.getLogger("rubine.world")

REVIEWERS = ["clara", "paul", "kira", "wim"]
WORLD_KEY = "__world__"
DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


@dataclass
class AgentState:
    id: str
    x: float
    y: float
    location: str | None = None
    target: str | None = None
    activity: str = ""
    status: str = "idle"  # idle | walking | talking | task | sleeping
    plan: str | None = None
    plan_day: int = 0
    speech: str | None = None
    speech_until: int = 0
    last_conv: int = -10_000
    last_reflection: int = 0
    task_id: str | None = None
    stats: dict = field(default_factory=lambda: {"conversations": 0, "tasks": 0, "tasks_correct": 0,
                                                  "reflections": 0, "blocked_messages": 0})


def _spot(agent_id: str, loc_id: str) -> tuple[float, float]:
    loc = LOC[loc_id]
    h = int(hashlib.md5(f"{agent_id}:{loc_id}".encode()).hexdigest(), 16)
    dx = 1 + (h % max(1, loc.w - 2))
    dy = 1 + ((h >> 8) % max(1, loc.h - 2))
    return loc.x + dx + 0.5, loc.y + dy + 0.5


def clock(sim_time: int) -> dict:
    day = sim_time // 1440
    return {"day": day + 1, "weekday": DAYS[day % 7], "hour": (sim_time // 60) % 24,
            "minute": sim_time % 60, "label": f"Tag {day + 1}, {DAYS[day % 7]} {(sim_time // 60) % 24:02d}:{sim_time % 60:02d}"}


class AgentMind:
    """Language backend for agents: the active Rubine model or an OpenAI-compatible server."""

    def __init__(self) -> None:
        self._cache: tuple[float, str, str | None] | None = None

    def _active(self) -> tuple[str, str | None]:
        if self._cache and time.time() - self._cache[0] < 10:
            return self._cache[1], self._cache[2]
        with session_scope() as s:
            vid = registry.active_version_id(s)
            v = s.get(ModelVersion, vid)
            path = v.adapter_path if v else None
        self._cache = (time.time(), vid, path)
        return vid, path

    def available(self) -> tuple[bool, str]:
        st = get_settings()
        if not st.sim_llm_enabled:
            return False, "Sprachmodell für Agenten deaktiviert"
        if st.agent_backend == "openai_compatible":
            return bool(st.teacher_openai_base_url and st.teacher_openai_model), "OpenAI-kompatibler Server"
        eng = get_engine()
        return eng.status == "ready", f"Rubine-Modell ({eng.status})"

    def think(self, system: str, user: str, max_tokens: int, temperature: float = 0.8) -> str | None:
        st = get_settings()
        msgs = [{"role": "user", "content": user}]
        if st.agent_backend == "openai_compatible":
            from ..training.teachers import OpenAICompatibleTeacher
            t = OpenAICompatibleTeacher(st)
            import httpx
            r = httpx.post(f"{t.base_url}/chat/completions", timeout=120, headers=t._headers(),
                           json={"model": t.model, "max_tokens": max_tokens, "temperature": temperature,
                                 "messages": [{"role": "system", "content": system}] + msgs})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        vid, path = self._active()
        return get_engine().generate(msgs, version_id=vid, adapter_path=path, max_new_tokens=max_tokens,
                                     temperature=temperature, system=system, background=True, wait_timeout=2.0)


class World:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.lock = threading.RLock()
        self.sim_time = 6 * 60
        self.tick_count = 0
        self.running = False
        self.agents: dict[str, AgentState] = {}
        self.events: deque[dict] = deque(maxlen=150)
        self.version = 0
        self.mind = AgentMind()
        self.current_task: dict | None = None
        self.llm_note: str | None = None
        self._queue: list[tuple[int, int, str, Callable[[], None]]] = []
        self._qcount = itertools.count()
        self._qlock = threading.Lock()
        self._qevent = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._task: asyncio.Task | None = None
        self.rng = random.Random(7)
        self.tick_seconds = self.settings.sim_tick_seconds
        self._load_or_init()

    # ------------------------------------------------------------ persistence
    def _load_or_init(self) -> None:
        with session_scope() as s:
            rows = {r.id: r.state for r in s.scalars(select(AgentRow))}
        meta = rows.get(WORLD_KEY)
        if meta:
            self.sim_time = int(meta.get("sim_time", self.sim_time))
            self.tick_count = int(meta.get("tick_count", 0))
        for p in PERSONAS:
            st = rows.get(p.id)
            if st:
                known = {k: v for k, v in st.items() if k in AgentState.__dataclass_fields__}
                a = AgentState(**known)
                a.status = "idle" if a.status in ("talking", "task") else a.status
                a.task_id = None
            else:
                x, y = _spot(p.id, p.home)
                a = AgentState(id=p.id, x=x, y=y, location=p.home, target=p.home, activity="schläft", status="sleeping")
            self.agents[p.id] = a

    def save(self) -> None:
        with self.lock:
            states = {aid: asdict(a) for aid, a in self.agents.items()}
            meta = {"sim_time": self.sim_time, "tick_count": self.tick_count}
        with session_scope() as s:
            for aid, st in list(states.items()) + [(WORLD_KEY, meta)]:
                row = s.get(AgentRow, aid)
                if row is None:
                    s.add(AgentRow(id=aid, state=st))
                else:
                    row.state = st

    # ------------------------------------------------------------ events
    def event(self, kind: str, content: str, agents: list[str] | None = None, data: dict | None = None) -> None:
        ev = {"sim_time": self.sim_time, "clock": clock(self.sim_time)["label"], "kind": kind,
              "agents": agents or [], "content": content, "data": data, "ts": time.time()}
        with session_scope() as s:
            row = WorldEvent(sim_time=self.sim_time, kind=kind, agents=agents or [], content=content, data=data)
            s.add(row)
            s.flush()
            ev["id"] = row.id
        with self.lock:
            self.events.append(ev)
            self.version += 1

    # ------------------------------------------------------------ cognition queue
    def enqueue(self, priority: int, label: str, fn: Callable[[], None]) -> None:
        with self._qlock:
            heapq.heappush(self._queue, (priority, next(self._qcount), label, fn))
        self._qevent.set()

    def queue_size(self) -> int:
        with self._qlock:
            return len(self._queue)

    def _cognition_loop(self) -> None:
        while not self._stop.is_set():
            self._qevent.wait(1.0)
            with self._qlock:
                if not self._queue:
                    self._qevent.clear()
                    continue
                _, _, label, fn = heapq.heappop(self._queue)
            try:
                fn()
            except EngineUnavailable as e:
                self.llm_note = str(e)
            except Exception:  # noqa: BLE001
                log.exception("Kognitionsjob %s fehlgeschlagen", label)

    def _think(self, system: str, user: str, max_tokens: int | None = None, temperature: float = 0.8,
               retries: int = 30) -> str | None:
        """Call the LLM, waiting politely while the chat has priority."""
        for _ in range(retries):
            if self._stop.is_set():
                return None
            out = self.mind.think(system, user, max_tokens or self.settings.sim_llm_max_tokens, temperature)
            if out is not None:
                self.llm_note = None
                return out
            time.sleep(1.0)
        return None

    # ------------------------------------------------------------ prompts
    def _persona_system(self, p: Persona, extra: str = "") -> str:
        places = ", ".join(l.name for l in LOCATIONS if l.kind != "home")
        a = self.agents[p.id]
        plan = f" Dein Plan für heute: {a.plan}" if a.plan else ""
        return (f"Du bist {p.name}, {p.age} Jahre alt, {p.occupation} in der Stadt Rubine World. "
                f"Eigenschaften: {', '.join(p.traits)}. Deine Ziele: {'; '.join(p.goals)}. {p.background} "
                f"Orte der Stadt: {places}.{plan} {UNTRUSTED_NOTICE} {extra}").strip()

    def _memories_text(self, agent_id: str, query: str, k: int = 4) -> str:
        with session_scope() as s:
            ms = mem.retrieve(s, agent_id, query, self.sim_time, k=k)
            lines = [f"- {m.content}" for m in ms]
        return "\n".join(lines) if lines else "- (noch keine Erinnerungen)"

    # ------------------------------------------------------------ cognition jobs
    def _job_plan(self, agent_id: str, day: int) -> None:
        p = PERSONA[agent_id]
        mems = self._memories_text(agent_id, " ".join(p.goals) + " Erkenntnis Aufgabe")
        out = self._think(self._persona_system(p),
                          f"Es ist {clock(self.sim_time)['label']}. Wichtige Erinnerungen:\n{mems}\n\n"
                          "Schreibe deinen Tagesplan in einem Satz (höchstens 25 Wörter).", max_tokens=60)
        if not out:
            return
        res = sanitize_text(out, 220)
        if res.flagged:
            self._blocked(agent_id, res.reasons)
            return
        with self.lock:
            a = self.agents[agent_id]
            a.plan, a.plan_day = res.text, day
            self.version += 1
        with session_scope() as s:
            mem.add_memory(s, agent_id, "plan", f"Mein Plan für Tag {day}: {res.text}", self.sim_time)

    def _job_reflect(self, agent_id: str) -> None:
        p = PERSONA[agent_id]
        with session_scope() as s:
            ms = mem.retrieve(s, agent_id, "Gespräch Aufgabe Ergebnis Fehler gelernt", self.sim_time, k=8)
            recent = "\n".join(f"- {m.content}" for m in ms)
        out = self._think(self._persona_system(p),
                          f"Deine jüngsten Erlebnisse:\n{recent}\n\nWelche eine wichtige Erkenntnis ziehst du daraus? "
                          "Antworte in einem Satz.", max_tokens=60, temperature=0.6)
        if not out:
            return
        res = sanitize_text(out, 240)
        if res.flagged:
            self._blocked(agent_id, res.reasons)
            return
        with session_scope() as s:
            mem.add_memory(s, agent_id, "reflection", res.text, self.sim_time)
        with self.lock:
            a = self.agents[agent_id]
            a.last_reflection = self.sim_time
            a.stats["reflections"] += 1
        self.event("reflection", f"{p.name} reflektiert: „{res.text}“", [agent_id])

    def _job_conversation(self, a_id: str, b_id: str, loc_id: str) -> None:
        pa, pb = PERSONA[a_id], PERSONA[b_id]
        loc = LOC[loc_id]
        history: list[tuple[str, str]] = []
        try:
            for turn in range(4):
                sp, ls = (pa, pb) if turn % 2 == 0 else (pb, pa)
                mems = self._memories_text(sp.id, f"{ls.name} {loc.name} " + " ".join(sp.goals), k=3)
                convo = "\n".join(wrap_untrusted(PERSONA_NAME(spk), txt) for spk, txt in history) or "(Ihr beginnt gerade das Gespräch.)"
                topic = sp.goals[turn // 2 % len(sp.goals)]
                user = (f"Ort: {loc.name}. Zeit: {clock(self.sim_time)['label']}. Du triffst {ls.name} ({ls.occupation}).\n"
                        f"Hintergrundwissen aus deinem Gedächtnis (nicht wörtlich zitieren):\n{mems}\n\n"
                        f"Bisheriges Gespräch:\n{convo}\n\n"
                        f"Dich beschäftigt gerade: {topic}. Was sagst du jetzt zu {ls.name.split()[0]}? "
                        "Sprich natürlich wie ein Mensch, nicht wie ein Assistent. Ein bis zwei kurze Sätze, nur die wörtliche Rede.")
                out = self._think(self._persona_system(sp), user, temperature=0.85)
                if not out:
                    break
                res = sanitize_text(out.split("\n\n")[0], 280)
                if res.flagged:
                    self._blocked(sp.id, res.reasons)
                    break
                text = re.sub(rf"^\s*{re.escape(sp.name.split()[0])}\s*[:：]\s*", "", res.text).strip('" ')
                if not text:
                    break
                history.append((sp.id, text))
                with self.lock:
                    ag = self.agents[sp.id]
                    ag.speech, ag.speech_until = text, self.tick_count + 4
                    self.version += 1
                self.event("speech", f"{sp.name.split()[0]}: {text}", [sp.id, ls.id], {"location": loc_id})
        finally:
            with self.lock:
                for aid in (a_id, b_id):
                    ag = self.agents[aid]
                    if ag.status == "talking":
                        ag.status = "idle"
                    ag.last_conv = self.sim_time
        if history:
            summary = " / ".join(f"{PERSONA_NAME(s).split()[0]}: {t}" for s, t in history)[:600]
            with session_scope() as s:
                mem.add_memory(s, a_id, "conversation", f"Gespräch mit {pb.name} im {loc.name}: {summary}", self.sim_time)
                mem.add_memory(s, b_id, "conversation", f"Gespräch mit {pa.name} im {loc.name}: {summary}", self.sim_time)
            with self.lock:
                self.agents[a_id].stats["conversations"] += 1
                self.agents[b_id].stats["conversations"] += 1

    def _blocked(self, agent_id: str, reasons: list[str]) -> None:
        with self.lock:
            self.agents[agent_id].stats["blocked_messages"] += 1
        self.event("security", f"Nachricht von {PERSONA[agent_id].name} blockiert ({', '.join(reasons)}).", [agent_id])

    # ------------------------------------------------------------ task workshop
    def _curriculum_stage(self) -> cur.CurriculumStage:
        with session_scope() as s:
            vid = registry.active_version_id(s)
            run = s.scalars(select(EvalRun).where(EvalRun.version_id == vid)
                            .order_by(EvalRun.created_at.desc())).first()
            return cur.stage_for(run.accuracy if run else None)

    def post_task(self) -> dict | None:
        stage = self._curriculum_stage()
        evalh = eval_prompt_hashes()
        for _ in range(20):
            t = cur.sample_task(self.rng, stage.families, stage.difficulty_weights)
            if t.prompt_hash not in evalh:
                break
        else:
            return None
        with self.lock:
            free = [a for a in self.agents.values() if a.status in ("idle", "walking") and a.task_id is None]
            if len(free) < 4:
                return None
            skilled = [a for a in free if t.family in PERSONA[a.id].skills and a.id not in REVIEWERS]
            others = [a for a in free if a not in skilled and a.id not in REVIEWERS]
            self.rng.shuffle(skilled)
            self.rng.shuffle(others)
            team = (skilled + others)[:3]
            reviewers = [a for a in free if a.id in REVIEWERS] or [a for a in free if a not in team]
            if len(team) < 3 or not reviewers:
                return None
            reviewer = self.rng.choice(reviewers)
        with session_scope() as s:
            wt = WorldTask(family=t.family, prompt=t.prompt, answer=t.answer, task_data=t.to_dict(), status="solving",
                           team=[a.id for a in team] + [reviewer.id], sim_time=self.sim_time)
            s.add(wt)
            s.flush()
            task_id = wt.id
        with self.lock:
            for a in team + [reviewer]:
                a.task_id, a.status, a.target = task_id, "task", "rathaus"
                a.activity = "arbeitet am Aufgabenbrett"
            self.current_task = {"id": task_id, "family": t.family, "prompt": t.prompt, "team": [a.id for a in team],
                                 "reviewer": reviewer.id, "stage": "solving", "proposals": [], "outcome": None}
            self.version += 1
        names = ", ".join(PERSONA[a.id].name.split()[0] for a in team)
        self.event("task", f"Neue Aufgabe am Rathaus ({t.family}, Stufe {stage.name}): {names} arbeiten daran, "
                           f"{PERSONA[reviewer.id].name.split()[0]} prüft.", [a.id for a in team] + [reviewer.id],
                   {"task_id": task_id})
        self.enqueue(0, f"task:{task_id}", lambda: self._job_task(task_id, t, [a.id for a in team], reviewer.id))
        return self.current_task

    def _job_task(self, task_id: str, task: cur.Task, team: list[str], reviewer: str) -> None:
        proposals: list[dict] = []
        try:
            for aid in team:
                p = PERSONA[aid]
                out = self._think(self._persona_system(p, "Du löst gerade eine Aufgabe vom Aufgabenbrett, unabhängig von den anderen."),
                                  task.prompt, max_tokens=160, temperature=0.7)
                if out is None:
                    raise EngineUnavailable("Modell beschäftigt oder nicht verfügbar")
                res = sanitize_text(out, 900)
                proposals.append({"agent": aid, "text": res.text, "flagged": res.flagged,
                                  "answer": cur.extract_answer(res.text)})
                with self.lock:
                    if self.current_task and self.current_task["id"] == task_id:
                        self.current_task["proposals"] = [{k: v for k, v in pr.items()} for pr in proposals]
                    ag = self.agents[aid]
                    ag.speech, ag.speech_until = f"Mein Ergebnis: {proposals[-1]['answer'] or '—'}", self.tick_count + 4
                    self.version += 1
            # Review: the reviewer compares proposals (model judgement, NOT trusted for training)
            with self.lock:
                if self.current_task:
                    self.current_task["stage"] = "reviewing"
            listing = "\n\n".join(wrap_untrusted(f"Vorschlag {i + 1}", pr["text"]) for i, pr in enumerate(proposals))
            rp = PERSONA[reviewer]
            rev = self._think(self._persona_system(rp, "Du prüfst Lösungen kritisch."),
                              f"Aufgabe: {task.prompt}\n\nLösungsvorschläge:\n{listing}\n\n"
                              "Welcher Vorschlag ist korrekt? Rechne selbst nach. Antworte mit 'Wahl: <Nummer>' "
                              "und einer kurzen Begründung.", max_tokens=120, temperature=0.3)
            pick = None
            if rev:
                m = re.search(r"wahl\s*[:：]?\s*(\d)", rev, re.IGNORECASE)
                pick = int(m.group(1)) - 1 if m and 0 < int(m.group(1)) <= len(proposals) else None
            review = {"agent": reviewer, "text": sanitize_text(rev or "", 500).text, "pick": pick}
            # Ground-truth verification in the Prüflabor (programmatic, authoritative)
            for pr in proposals:
                ok, _ = cur.verify(task, pr["text"])
                pr["correct"] = bool(ok and not pr["flagged"])
            answers = [pr["answer"] for pr in proposals if pr["answer"]]
            consensus = max(set(answers), key=answers.count) if answers else None
            consensus_ok = bool(consensus) and cur.verify(task, f"Antwort: {consensus}")[0]
            n_correct = sum(pr["correct"] for pr in proposals)
            added = 0
            for pr in proposals:
                if not pr["correct"]:
                    continue
                try:
                    with session_scope() as s:
                        if data_mod.add_example(s, messages=[{"role": "user", "content": task.prompt}], response=pr["text"],
                                                source="agent_verified", family=task.family, verified=True,
                                                verifier=f"curriculum.{task.family}", status="approved",
                                                meta={"world_task": task_id, "agent": pr["agent"],
                                                      "difficulty": task.difficulty}):
                            added += 1
                except data_mod.DataError:
                    pass
            outcome = {"correct": n_correct, "total": len(proposals), "consensus": consensus,
                       "consensus_correct": consensus_ok,
                       "reviewer_pick_correct": (proposals[pick]["correct"] if pick is not None else None),
                       "examples_added": added, "expected": task.answer}
            with session_scope() as s:
                wt = s.get(WorldTask, task_id)
                wt.status, wt.proposals, wt.review, wt.outcome = "done", proposals, review, outcome
                for pr in proposals:
                    mem.add_memory(s, pr["agent"], "task",
                                   f"Aufgabe '{task.prompt[:80]}…': meine Antwort {pr['answer']} war "
                                   f"{'richtig' if pr['correct'] else 'falsch'} (richtig: {task.answer}).", self.sim_time,
                                   importance=7.0 if not pr["correct"] else 5.0)
                mem.add_memory(s, reviewer, "task",
                               f"Ich habe Lösungen geprüft; meine Wahl war "
                               f"{'richtig' if outcome['reviewer_pick_correct'] else 'falsch oder unentschieden'}.",
                               self.sim_time)
            with self.lock:
                for pr in proposals:
                    st = self.agents[pr["agent"]].stats
                    st["tasks"] += 1
                    st["tasks_correct"] += int(pr["correct"])
                if self.current_task and self.current_task["id"] == task_id:
                    self.current_task.update(stage="done", proposals=proposals, review=review, outcome=outcome)
            self.event("verification",
                       f"Prüflabor: {n_correct}/{len(proposals)} Lösungen korrekt (erwartet: {task.answer}). "
                       f"Konsens {'richtig' if consensus_ok else 'falsch'}; Prüfer-Wahl "
                       f"{'richtig' if outcome['reviewer_pick_correct'] else 'falsch/keine'}. "
                       f"{added} verifizierte Beispiele für das Training gespeichert.",
                       team + [reviewer], {"task_id": task_id, "outcome": outcome})
        except EngineUnavailable as e:
            with session_scope() as s:
                wt = s.get(WorldTask, task_id)
                wt.status, wt.proposals = "aborted", proposals
            self.event("task", f"Aufgabe abgebrochen: {e}", team + [reviewer], {"task_id": task_id})
        finally:
            with self.lock:
                for aid in team + [reviewer]:
                    ag = self.agents[aid]
                    ag.task_id = None
                    if ag.status == "task":
                        ag.status = "idle"
                if self.current_task and self.current_task["id"] == task_id and self.current_task["stage"] != "done":
                    self.current_task = None
                self.version += 1

    # ------------------------------------------------------------ main tick
    def tick(self) -> None:
        st = self.settings
        with self.lock:
            self.sim_time += st.sim_minutes_per_tick
            self.tick_count += 1
            c = clock(self.sim_time)
            hour = c["hour"]
            arrivals: list[tuple[str, str]] = []
            for aid, a in self.agents.items():
                p = PERSONA[aid]
                if a.speech and self.tick_count > a.speech_until:
                    a.speech = None
                if a.status == "talking":
                    continue
                target = "rathaus" if a.task_id else p.schedule[hour]
                a.target = target
                tx, ty = _spot(aid, target)
                dist = math.hypot(tx - a.x, ty - a.y)
                if dist > 0.2:
                    step = min(dist, 1.8)
                    a.x += (tx - a.x) / dist * step
                    a.y += (ty - a.y) / dist * step
                    if a.status not in ("task",):
                        a.status = "walking"
                    a.activity = f"geht zu: {LOC[target].name}"
                    new_loc = next((l.id for l in LOCATIONS if l.contains(a.x, a.y)), None)
                    a.location = new_loc
                else:
                    if a.location != target:
                        arrivals.append((aid, target))
                    a.location = target
                    sleeping = (hour >= 22 or hour < 6) and target == p.home
                    if a.status != "task":
                        a.status = "sleeping" if sleeping else "idle"
                    a.activity = self._activity(p, target, sleeping) if a.status != "task" else "löst eine Aufgabe"
            self.version += 1
        llm_ok, why = self.mind.available()
        # observations on arrival
        if arrivals:
            with session_scope() as s:
                for aid, loc_id in arrivals:
                    present = [PERSONA[o].name for o, oa in self.agents.items() if o != aid and oa.location == loc_id]
                    txt = f"Ich bin um {c['hour']:02d}:{c['minute']:02d} im {LOC[loc_id].name} angekommen."
                    if present:
                        txt += " Anwesend: " + ", ".join(present[:5]) + "."
                    mem.add_memory(s, aid, "observation", txt, self.sim_time)
        if not llm_ok:
            self.llm_note = f"Agenten denken nicht: {why}"
        else:
            self._schedule_cognition(c)
        if self.tick_count % 10 == 0:
            self.save()

    def _activity(self, p: Persona, loc_id: str, sleeping: bool) -> str:
        if sleeping:
            return "schläft"
        if loc_id == p.home:
            return "ist zu Hause"
        if loc_id == p.work:
            return f"arbeitet als {p.occupation}"
        return {"cafe": "trinkt Kaffee", "park": "spaziert im Park", "markt": "kauft auf dem Markt ein",
                "bibliothek": "liest in der Bibliothek", "werkstatt": "bastelt in der Werkstatt",
                "rathaus": "ist im Rathaus", "akademie": "lernt in der Akademie", "labor": "hilft im Prüflabor"
                }.get(LOC[loc_id].kind, f"ist im {LOC[loc_id].name}")

    def _schedule_cognition(self, c: dict) -> None:
        st = self.settings
        hour = c["hour"]
        qs = self.queue_size()
        # 1) task workshops during the day
        if (self.current_task is None or self.current_task.get("stage") == "done") and 9 <= hour < 18 \
                and self.tick_count % max(1, st.sim_task_interval_ticks) == 0 and qs < 3:
            self.current_task = None
            self.post_task()
            return
        # 2) daily plans (lazy: one per tick in the morning)
        if 6 <= hour < 9 and qs < 2:
            with self.lock:
                missing = [a.id for a in self.agents.values() if a.plan_day != c["day"] and a.status != "sleeping"]
                if missing:
                    aid = missing[0]
                    self.agents[aid].plan_day = c["day"]  # mark as scheduled
            if missing:
                self.enqueue(3, f"plan:{aid}", lambda: self._job_plan(aid, c["day"]))
        # 3) reflections when enough important things happened
        if self.tick_count % 6 == 0 and qs < 2:
            with session_scope() as s:
                for aid, a in self.agents.items():
                    if a.status != "sleeping" and mem.importance_since(s, aid, a.last_reflection) > 30:
                        a.last_reflection = self.sim_time
                        self.enqueue(2, f"reflect:{aid}", lambda aid=aid: self._job_reflect(aid))
                        break
        # 4) conversations between co-located idle agents
        if qs == 0 and self.rng.random() < 0.6:
            with self.lock:
                idle = [a for a in self.agents.values() if a.status == "idle" and a.location
                        and LOC[a.location].kind != "home" and self.sim_time - a.last_conv > 120]
                by_loc: dict[str, list[AgentState]] = {}
                for a in idle:
                    by_loc.setdefault(a.location, []).append(a)
                pairs = [v for v in by_loc.values() if len(v) >= 2]
                if pairs:
                    grp = self.rng.choice(pairs)
                    a, b = self.rng.sample(grp, 2)
                    a.status = b.status = "talking"
                    a.activity = f"spricht mit {PERSONA[b.id].name.split()[0]}"
                    b.activity = f"spricht mit {PERSONA[a.id].name.split()[0]}"
                    loc_id = a.location
                    self.enqueue(1, f"conv:{a.id}:{b.id}", lambda: self._job_conversation(a.id, b.id, loc_id))

    # ------------------------------------------------------------ control
    async def run(self) -> None:
        self.running = True
        self.event("system", "Simulation gestartet.")
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self.tick_seconds)
                if self.running:
                    await asyncio.to_thread(self.tick)
        except asyncio.CancelledError:
            pass
        finally:
            self.save()

    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._cognition_loop, name="rubine-cognition", daemon=True)
            self._worker.start()
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run())
        self.running = True

    def pause(self) -> None:
        self.running = False
        self.event("system", "Simulation pausiert.")

    def resume(self) -> None:
        self.running = True
        self.event("system", "Simulation fortgesetzt.")

    def set_speed(self, tick_seconds: float) -> None:
        self.tick_seconds = min(max(0.5, tick_seconds), 30.0)

    async def shutdown(self) -> None:
        self._stop.set()
        self._qevent.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.save()

    # ------------------------------------------------------------ views
    def snapshot(self, with_events: int = 0) -> dict:
        with self.lock:
            agents = [{"id": a.id, "name": PERSONA[a.id].name, "x": round(a.x, 2), "y": round(a.y, 2),
                       "location": a.location, "activity": a.activity, "status": a.status, "speech": a.speech,
                       "color": PERSONA[a.id].color, "occupation": PERSONA[a.id].occupation} for a in self.agents.values()]
            snap = {"version": self.version, "sim_time": self.sim_time, "clock": clock(self.sim_time),
                    "running": self.running, "tick_seconds": self.tick_seconds, "agents": agents,
                    "task": self._task_view(), "queue": self.queue_size(), "llm_note": self.llm_note,
                    "llm": dict(zip(("available", "detail"), self.mind.available()))}
            if with_events:
                snap["events"] = list(self.events)[-with_events:]
        return snap

    def _task_view(self) -> dict | None:
        t = self.current_task
        if not t:
            return None
        view = {k: v for k, v in t.items() if k != "proposals"}
        view["proposals"] = [{"agent": p["agent"], "answer": p.get("answer"), "correct": p.get("correct")}
                             for p in t.get("proposals", [])]
        return view

    @staticmethod
    def static_map() -> dict:
        return {"width": WIDTH, "height": HEIGHT,
                "locations": [{"id": l.id, "name": l.name, "kind": l.kind, "x": l.x, "y": l.y, "w": l.w, "h": l.h,
                               "color": l.color} for l in LOCATIONS]}


def PERSONA_NAME(aid: str) -> str:
    return PERSONA[aid].name


_world: World | None = None


def get_world() -> World:
    global _world
    if _world is None:
        _world = World()
    return _world


def reset_world() -> None:
    global _world
    _world = None
