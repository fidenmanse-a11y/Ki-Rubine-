"""Language-model layer for residents (event-driven, budgeted, validated).

The model is asked only at meaningful moments (significant choices, morning plans,
conversations, naming, evening reflection). It receives the resident's *simulated*
situation and a numbered list of options that the world engine has already validated.
Its answer can only select one of those options; free text (speech, names, reasons)
is stored as text and never changes the world state.

Every decision is logged with the deciding mechanism and the model version, so it is
always visible whether a choice came from rules or from a language model.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Callable

from ..security.sanitize import sanitize_text
from . import rules as R
from .state import World

log = logging.getLogger("rubine.world2.mind")

GenerateFn = Callable[[str, str, str, int, float], "str | None"]  # (version, system, user, max_tokens, temp)


def describe_level(v: float, words=("gering", "mäßig", "hoch", "sehr hoch")) -> str:
    return words[min(3, int(v * 4))]


def persona_block(w: World, a: dict) -> str:
    p, v = a["personality"], a["values"]
    traits = sorted(p.items(), key=lambda kv: -abs(kv[1] - 0.5))[:4]
    trait_txt = ", ".join(f"{R.PERSONALITY_LABEL[k]} {'hoch' if val > 0.5 else 'niedrig'}" for k, val in traits)
    vals = ", ".join(R.VALUE_LABEL[k] for k, _ in sorted(v.items(), key=lambda kv: -kv[1])[:3])
    home = w.buildings.get(a.get("home") or "")
    inv = ", ".join(f"{n} {R.ITEM_LABEL.get(k, 'Münzen')}" for k, n in (a.get("inv") or {}).items()) or "nichts"
    n = a["needs"]
    agenda = sorted((g for g in a.get("agenda", []) if g["status"] == "aktiv"), key=lambda g: -g["prio"])
    goals = "; ".join(g["text"] for g in agenda[:3]) or "; ".join(g["text"] for g in a["goals"])
    return (f"Du bist {a['name']} {a['family']}, {int(w.age(a))} Jahre alt, aus der Gruppe der {a['origin']}. "
            f"Persönlichkeit: {trait_txt}. Dir wichtig: {vals}. Ziele: {goals}. "
            f"Lage: Hunger {describe_level(n['hunger'])}, Durst {describe_level(n['thirst'])}, Energie {describe_level(n['energy'])}, "
            f"Stress {describe_level(n['stress'])}, Gesundheit {describe_level(a['health'])}. Besitz: {inv}. "
            f"Zuhause: {R.BUILDINGS[home['type']]['label'] if home else 'keines'}. Ort: {w.region_name(w.region_of(a['x'], a['y']))}, "
            f"{w.calendar()['label']}.")


def known_context(w: World, a: dict, k: int = 4) -> str:
    words = {g["type"] for g in a["goals"]} | {"hunger", "streit", "gesetz", "haus"}
    mems = w.recall(a, words, k=k)
    laws = [f["x"] for f in a["facts"].values() if f["k"] == "law"][:3]
    lines = [f"- {m['x']}" for m in mems]
    if laws:
        lines.append("Bekannte Regeln: " + "; ".join(laws))
    return "\n".join(lines) or "- (keine besonderen Erinnerungen)"


class Mind:
    def __init__(self, generate: GenerateFn | None, *, model_for: Callable[[World, dict], str]) -> None:
        self.generate = generate
        self.model_for = model_for
        self.q: "queue.Queue[dict]" = queue.Queue(maxsize=64)
        self.results: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {"requests": 0, "answered": 0, "invalid": 0, "timeouts": 0, "dropped": 0, "stale": 0, "errors": 0}
        self.current_tick = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread is None and self.generate is not None:
            self._thread = threading.Thread(target=self._loop, name="rubine-world2-mind", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def available(self) -> bool:
        if self.generate is None:
            return False
        ready = getattr(self.generate, "ready", None)
        return bool(ready()) if ready else True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                req = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if req.get("deadline") is not None and req["deadline"] < self.current_tick:
                self.stats["stale"] += 1  # the resident already had to act without it
                req["answer"] = None
                self.results.put(req)
                continue
            try:
                req["answer"] = self._call(req)
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                self.last_error = f"{type(e).__name__}: {e}"
                req["answer"] = None
            self.results.put(req)

    def _call(self, req: dict) -> str | None:
        for _ in range(20):
            if self._stop.is_set():
                return None
            out = self.generate(req["model"], req["system"], req["user"], req["max_tokens"], req.get("temp", 0.7))
            if out is not None:
                return out
            time.sleep(0.5)  # model busy with chat (chat has priority)
        return None

    # ------------------------------------------------------------ budget
    def _budget_ok(self, w: World, a: dict) -> bool:
        cfg = w.config.get("llm", {})
        if not cfg.get("enabled", True) or not self.available():
            return False
        if a.get("llm_day") != w.day:
            a["llm_day"], a["llm_calls"] = w.day, 0
        if a["llm_calls"] >= int(cfg.get("calls_per_agent_day", 4)):
            return False
        if self.q.qsize() >= 48:
            self.stats["dropped"] += 1
            return False
        return True

    DEADLINES = {"decision": None, "dialog": 8, "dayplan": 24, "naming": None, "reflection": 48}

    def _submit(self, w: World, a: dict, kind: str, system: str, user: str, max_tokens: int, payload: dict,
                temp: float = 0.7) -> dict | None:
        if not self._budget_ok(w, a):
            return None
        model = self.model_for(w, a)
        dl = self.DEADLINES.get(kind)
        if kind == "decision":
            dl = int(w.config.get("llm", {}).get("timeout_ticks", 4))
            if self.q.qsize() >= 6 and w.config.get("llm", {}).get("mode") != "blocking":
                self.stats["dropped"] += 1
                return None
        req = {"kind": kind, "agent": a["id"], "system": system, "user": user, "max_tokens": max_tokens, "temp": temp,
               "model": model, "tick": w.tick, "payload": payload, "deadline": (w.tick + dl) if dl else None}
        a["llm_calls"] += 1
        self.stats["requests"] += 1
        if w.config.get("llm", {}).get("mode") == "blocking":
            req["answer"] = self._call(req) if self.generate else None
            self._apply(w, req)
            return req
        try:
            self.q.put_nowait(req)
        except queue.Full:
            self.stats["dropped"] += 1
            return None
        return req

    # ------------------------------------------------------------ requests
    def request_decision(self, w: World, a: dict, options: list[dict]) -> dict | None:
        menu = "\n".join(f"{i + 1}. {o['label']}" for i, o in enumerate(options))
        user = (f"Was du weißt:\n{known_context(w, a)}\n\nWas tust du jetzt? Möglichkeiten:\n{menu}\n\n"
                "Antworte genau in diesem Format:\nWahl: <Nummer>\nGrund: <ein kurzer Satz>")
        return self._submit(w, a, "decision", persona_block(w, a), user, 60,
                            {"options": [{"type": o["type"], "target": o["target"], "label": o["label"],
                                          "key": _okey(o)} for o in options]}, temp=0.6)

    def request_dayplan(self, w: World, a: dict) -> dict | None:
        from .actions import FOCUS
        keys = list(FOCUS)
        menu = "\n".join(f"{i + 1}. {FOCUS[k]}" for i, k in enumerate(keys))
        user = (f"Ein neuer Tag beginnt. Was du weißt:\n{known_context(w, a)}\n\nWorauf konzentrierst du dich heute?\n{menu}\n\n"
                "Antworte genau so:\nWahl: <Nummer>\nPlan: <ein Satz>")
        return self._submit(w, a, "dayplan", persona_block(w, a), user, 50, {"keys": keys}, temp=0.7)

    def request_dialog(self, w: World, a: dict, b: dict, topic: str, event: int) -> dict | None:
        rel = w.rel(a["id"], b["id"])
        user = (f"Du triffst {b['name']} ({int(w.age(b))} Jahre). Dein Verhältnis: Vertrauen {describe_level(rel['trust'])}, "
                f"Zuneigung {describe_level(rel['affection'])}. Gesprächsthema: {topic}.\n"
                "Was sagst du zu ihr/ihm? Ein bis zwei Sätze wörtliche Rede, ohne Namen davor.")
        return self._submit(w, a, "dialog", persona_block(w, a), user, 50, {"other": b["id"], "event": event}, temp=0.85)

    def request_naming(self, w: World, agent_id: str, kind: str, ref: str) -> dict | None:
        a = w.agents.get(agent_id)
        if not a or not a["alive"]:
            return None
        what = {"siedlung": "die neue Siedlung, in der du lebst", "waehrung": "die neue gemeinsame Währung",
                "institution": "deine neu gegründete Organisation", "kunstwerk": "dein neues Werk",
                "buendnis": "das Bündnis, das du mit Freunden gegründet hast"}[kind]
        user = f"Gib {what} einen kurzen Namen (höchstens 4 Wörter). Antworte nur mit dem Namen."
        return self._submit(w, a, "naming", persona_block(w, a), user, 16, {"kind": kind, "ref": ref}, temp=0.9)

    def request_goal(self, w: World, a: dict, goal: dict) -> dict | None:
        """The model weighs the agent's active goals and phrases why the new one matters (planning summary)."""
        active = [g for g in a["agenda"] if g["status"] == "aktiv"][:4]
        if goal not in active:
            active.append(goal)
        menu = "\n".join(f"{i + 1}. {g['text']} – {g['why']}" for i, g in enumerate(active))
        user = (f"Was du weißt:\n{known_context(w, a, 3)}\n\nDeine aktuellen Ziele:\n{menu}\n\nWelches Ziel ist dir jetzt am wichtigsten? "
                "Antworte genau so:\nWahl: <Nummer>\nWarum: <ein Satz in Ich-Form>")
        return self._submit(w, a, "goal", persona_block(w, a), user, 60, {"goals": [g["id"] for g in active]}, temp=0.6)

    def request_reflection(self, w: World, a: dict) -> dict | None:
        recent = "\n".join(f"- {m['x']}" for m in a["stm"][-8:]) or "- (ruhiger Tag)"
        user = (f"Der Tag geht zu Ende. Was heute geschah:\n{recent}\n\nWelche Erkenntnis ziehst du für deine Zukunft? "
                "Ein Satz.")
        return self._submit(w, a, "reflection", persona_block(w, a), user, 50, {}, temp=0.6)

    # ------------------------------------------------------------ results
    def poll(self, w: World) -> None:
        self.current_tick = w.tick
        while True:
            try:
                req = self.results.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply(w, req)
            except Exception as e:  # noqa: BLE001
                w.error("mind.apply", e)

    def _apply(self, w: World, req: dict) -> None:
        a = w.agents.get(req["agent"])
        ans = req.get("answer")
        if a is None or not a["alive"]:
            return
        if ans is None:
            if req["kind"] == "decision" and a.get("pending") and a["pending"].get("req_tick") == req["tick"]:
                a["pending"]["result"] = {"invalid": True, "reason": "keine Antwort vom Modell"}
            return
        self.stats["answered"] += 1
        clean = sanitize_text(ans, 400)
        label = f"Sprachmodell {req['model']}"
        if req["kind"] == "decision":
            m = re.search(r"wahl\s*[:：]?\s*(\d+)", ans, re.IGNORECASE) or re.match(r"\s*(\d+)", ans)
            why = re.search(r"grund\s*[:：]\s*(.+)", ans, re.IGNORECASE)
            opts = req["payload"]["options"]
            idx = int(m.group(1)) - 1 if m else -1
            if not (0 <= idx < len(opts)) or clean.flagged:
                self.stats["invalid"] += 1
                result = {"invalid": True, "reason": "Antwort nicht auswertbar", "raw": clean.text[:200], "model": req["model"]}
            else:
                result = {"key": opts[idx]["key"], "label": opts[idx]["label"], "model": req["model"],
                          "why": sanitize_text(why.group(1), 200).text if why else ""}
            if a.get("pending") and a["pending"].get("req_tick") == req["tick"]:
                a["pending"]["result"] = result
        elif req["kind"] == "dayplan":
            m = re.search(r"wahl\s*[:：]?\s*(\d+)", ans, re.IGNORECASE)
            plan = re.search(r"plan\s*[:：]\s*(.+)", ans, re.IGNORECASE)
            keys = req["payload"]["keys"]
            idx = int(m.group(1)) - 1 if m else -1
            if 0 <= idx < len(keys) and not clean.flagged:
                a["intention"] = {"focus": keys[idx], "text": sanitize_text(plan.group(1), 200).text if plan else "",
                                  "by": label, "tick": w.tick}
                _log_decision(w, a, "tagesplan", label, req["model"], [], keys[idx], a["intention"]["text"])
            else:
                self.stats["invalid"] += 1
        elif req["kind"] == "dialog":
            if clean.flagged:
                w.emit("sozial", "nachricht_blockiert", f"Eine Äußerung von {a['name']} wurde vom Sicherheitsfilter blockiert.",
                       actors=[a["id"]], witnesses=False)
                return
            line = clean.text.split("\n")[0].strip('" ')[:240]
            if line:
                other = w.agents.get(req["payload"]["other"])
                w.emit("sozial", "dialog", f"{a['name']} zu {other['name'] if other else '…'}: „{line}“",
                       actors=[a["id"]] + ([other["id"]] if other else []), x=a["x"], y=a["y"], cause=req["payload"]["event"],
                       data={"generated_by": label}, witnesses=False)
        elif req["kind"] == "naming":
            name = re.sub(r"[^\wÄÖÜäöüß \-']", "", clean.text.split("\n")[0]).strip()[:40]
            if not name or clean.flagged:
                return
            kind, ref = req["payload"]["kind"], req["payload"]["ref"]
            coll = {"siedlung": w.settlements, "waehrung": w.currencies, "institution": w.institutions, "kunstwerk": w.artworks,
                    "buendnis": w.alliances}[kind]
            obj = coll.get(ref)
            if obj:
                key = "title" if kind == "kunstwerk" else "name"
                old = obj.get(key)
                obj[key] = name
                obj["named_by"] = {"agent": a["id"], "by": label}
                w.emit("wissen" if kind == "kunstwerk" else "bau" if kind == "siedlung" else "wirtschaft", "benennung",
                       f"{a['name']} nennt {old} fortan „{name}“.", actors=[a["id"]], data={"kind": kind, "ref": ref,
                       "generated_by": label}, witnesses=False)
        elif req["kind"] == "goal":
            m = re.search(r"wahl\s*[:：]?\s*(\d+)", ans, re.IGNORECASE)
            why = re.search(r"warum\s*[:：]\s*(.+)", ans, re.IGNORECASE)
            ids = req["payload"]["goals"]
            idx = int(m.group(1)) - 1 if m else -1
            if 0 <= idx < len(ids) and not clean.flagged:
                g = next((x for x in a["agenda"] if x["id"] == ids[idx]), None)
                if g:
                    g["prio"] = round(min(1.0, g["prio"] + 0.15), 3)
                    g["by"] = label
                    g["motivation"] = sanitize_text(why.group(1), 200).text if why else None
                    _log_decision(w, a, "ziel", label, req["model"], [], g["text"], g.get("motivation") or "")
            else:
                self.stats["invalid"] += 1
        elif req["kind"] == "reflection":
            if clean.flagged or not clean.text:
                return
            w.remember(a, "reflexion", clean.text[:300], 7, tags=["reflexion"])
            a["plans"] = ([clean.text[:200]] + a["plans"])[:3]
            a["stats"]["reflections"] = a["stats"].get("reflections", 0) + 1


def _okey(o: dict) -> str:
    return f"{o['type']}|{o['target']}|{o['data'].get('btype', '')}|{(o['data'].get('idea') or {}).get('key', '')}"


def _log_decision(w: World, a: dict, kind: str, by: str, model: str | None, options: list[dict], chosen: str, why: str) -> dict:
    w.counters["decision"] += 1
    d = {"id": w.counters["decision"], "t": w.tick, "agent": a["id"], "kind": kind, "by": by, "model": model,
         "options": [{"label": o["label"], "u": o["u"]} for o in options[:6]], "chosen": chosen, "why": why[:300]}
    a["decisions"].append(d)
    a["decisions"] = a["decisions"][-15:]
    w.decision_buffer.append(d)
    if model:
        a["model"] = model
    return d


__all__ = ["Mind", "persona_block", "known_context", "_okey", "_log_decision"]
