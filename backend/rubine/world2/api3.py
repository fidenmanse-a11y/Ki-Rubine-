"""World 3.0 API additions (/api/world2/...): inner model state of residents, people list, society 3.0 views,
building interiors, follow list and a chat with a resident. All endpoints require login (router dependency).

Everything returned here is read from the live simulation state. Nothing is generated for display only."""
from __future__ import annotations

import asyncio
import json
import threading
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..security.auth import require_auth
from . import cognition as C
from . import rules as R
from .api import _name, agent_brief, svc
from .economy import wealth
from .life import health_status

router = APIRouter(prefix="/api/world2", dependencies=[Depends(require_auth)])

SEPARATION = {
    "memory": "Erinnerungen: gespeicherte Ereignisse in der Simulation (keine Modelländerung).",
    "lessons": "Lektionen/Fähigkeiten: Zahlen im Simulationszustand, die sich durch Erfahrung ändern (keine Modelländerung).",
    "model": "Modell-Feintuning: nur über das AI Lab (LoRA-Training mit Prüfung). Betrifft alle Bewohner mit dieser Modellversion.",
}
GOAL_STATUS = {"aktiv": "aktiv", "zurueckgestellt": "zurückgestellt", "erreicht": "erreicht", "aufgegeben": "aufgegeben",
               "hinfaellig": "hinfällig"}


def _cal(w, t: int | None) -> str | None:
    return w.calendar(t)["label"] if t is not None else None


def _goal_view(w, g: dict) -> dict:
    plan = g.get("plan") or {}
    steps = plan.get("steps", [])
    return {"id": g["id"], "type": g["type"], "text": g["text"], "why": g["why"], "prio": round(g["prio"], 2),
            "status": GOAL_STATUS.get(g["status"], g["status"]), "created": _cal(w, g["created"]),
            "chosen_by": g.get("by", "regeln"), "motivation": g.get("motivation"), "replans": g.get("replans", 0),
            "plan_log": [[_cal(w, t), r] for t, r in g.get("plan_log", [])[-4:]],
            "plan": {"current": plan.get("current", 0), "visible": plan.get("visible", len(steps)), "horizon": plan.get("horizon"),
                     "revisions": plan.get("revisions", 0),
                     "steps": [{"text": s["text"], "expect": s.get("expect"), "done": bool(s.get("done")),
                                "known": i < plan.get("visible", len(steps))} for i, s in enumerate(steps)]}}


def mind_view(w, a: dict) -> dict:
    """The resident's internal model state, as stored in the simulation."""
    if "emo" not in a:
        return {"available": False}
    ops = []
    for oid, o in a["opinions"].items():
        est, unc = C.honesty_estimate(a, oid)
        ops.append({"id": oid, "name": _name(w, oid) or oid, "honesty_estimate": round(est, 2), "uncertainty": round(unc, 2),
                    "suspicion": o["verdacht"], "notes": [[_cal(w, t), n] for t, n in o["notiz"][-3:]],
                    "anger": a["emo_targets"].get(oid, {}).get("aerger", 0), "gratitude": a["emo_targets"].get(oid, {}).get("dankbarkeit", 0)})
    ops.sort(key=lambda o: -(abs(o["honesty_estimate"] - 0.5) + o["suspicion"] + o["anger"] + o["gratitude"]))
    beliefs = [{"key": k, "text": C.BELIEFS.get(k, (k, None))[0], "confidence": b.get("conf", 0), "evidence": b["n"],
                "developer_truth": C.BELIEFS.get(k, (k, None))[1]} for k, b in a["beliefs"].items()]
    beliefs.sort(key=lambda b: -b["confidence"])
    alliances = [{"id": al["id"], "name": al["name"], "purpose": al["purpose"]} for al in w.alliances.values()
                 if al["active"] and a["id"] in al["members"]]
    feuds = [{"with": _name(w, f["b"] if f["a"] == a["id"] else f["a"]), "since": _cal(w, f["since"]), "intensity": f["intensity"]}
             for f in w.feuds.values() if f["active"] and a["id"] in (f["a"], f["b"])]
    promises = [{"id": p["id"], "from": _name(w, p["from"]), "to": _name(w, p["to"]), "text": p["text"], "status": p["status"],
                 "due": _cal(w, p["due"])} for p in w.promises.values() if a["id"] in (p["from"], p["to"])][-10:]
    pr = a.get("prison")
    prison = None
    if pr:
        b = w.buildings.get(pr["building"])
        prison = {"building": b and b.get("name") or "Gefängnis", "since": _cal(w, pr["since"]), "until": _cal(w, pr["until"]),
                  "case": pr.get("case")}
    return {
        "available": True,
        "notice": "Modellzustände einer Simulation (z. B. Emotionen als Zahlen), keine nachgewiesenen Gefühle oder Bewusstsein.",
        "reasoning": a["reasoning"], "morals": a["morals"],
        "emotions": a["emo"], "mood": C.mood(a),
        "agenda": [_goal_view(w, g) for g in sorted(a["agenda"], key=lambda g: (g["status"] != "aktiv", -g["prio"]))],
        "goal_history": [{"type": h["type"], "text": h.get("text"), "status": GOAL_STATUS.get(h["status"], h["status"]),
                          "when": _cal(w, h.get("ended")), "replans": h.get("replans", 0), "chosen_by": h.get("by"),
                          "why": h.get("why")} for h in a["goal_history"][-15:][::-1]],
        "beliefs": beliefs[:12], "opinions": ops[:12],
        "lessons": dict(sorted(a["lessons"].items(), key=lambda kv: -abs(kv[1]))),
        "lesson_log": [[_cal(w, t), act, d, txt] for t, act, d, txt in a["lesson_log"][-10:][::-1]],
        "development": [{"when": _cal(w, d["t"]), "morals": d["morals"], "skills": d["skills"], "mood": d["mood"]}
                        for d in a["dev_log"][-12:]],
        "friends": [{"id": f, "name": _name(w, f)} for f in a["friends"]],
        "alliances": alliances, "feuds": feuds, "promises": promises,
        "secrets": {"developer_only": True, "items": [[_cal(w, s["t"]), s["x"]] for s in a["secrets"][-8:]]},
        "prison": prison, "convictions": a.get("convictions", 0),
        "probation_until": _cal(w, a["probation_until"]) if a.get("probation_until", 0) > w.tick else None,
        "replan_pending": a.get("replan"),
        "decision_sources": _decision_sources(a),
        "separation": SEPARATION,
    }


def _decision_sources(a: dict) -> dict:
    out: dict[str, int] = {}
    for d in a.get("decisions", []):
        out[d["by"]] = out.get(d["by"], 0) + 1
    return out


@router.get("/agents/{aid}/mind")
def agent_mind(aid: str) -> dict:
    s = svc()
    with s.lock:
        a = s.world.agents.get(aid)
        if not a:
            raise HTTPException(404, "Bewohner nicht gefunden")
        return mind_view(s.world, a)


# ------------------------------------------------------------------ people
@router.get("/people")
def people(q: str | None = None, filter: str | None = None, sort: str = "name", include_dead: bool = False) -> dict:
    """Searchable list of residents. filter: gefangen|krank|kind|amt|obdachlos|verfolgt|verstorben."""
    s = svc()
    with s.lock:
        w = s.world
        follow = set(w.config.get("follow", []))
        leaders = {l for i in w.institutions.values() if i["active"] for l in i.get("leaders", [])}
        out = []
        for a in w.agents.values():
            if not a["alive"] and not include_dead and filter != "verstorben":
                continue
            if q and q.lower() not in f"{a['name']} {a['family']}".lower():
                continue
            row = {**agent_brief(w, a), "wealth": wealth(w, a), "status": health_status(w, a),
                   "prisoner": bool(a.get("prison")), "official": a["id"] in leaders, "homeless": not a.get("home"),
                   "followed": a["id"] in follow, "mood": C.mood(a) if "emo" in a else None,
                   "top_goal": next((g["text"] for g in sorted(a.get("agenda", []), key=lambda g: -g["prio"]) if g["status"] == "aktiv"), None),
                   "friends": len(a.get("friends", [])), "convictions": a.get("convictions", 0), "generation": a.get("generation", 0)}
            ok = {"gefangen": row["prisoner"], "krank": row["ill"], "kind": row["child"], "amt": row["official"],
                  "obdachlos": row["homeless"] and not row["child"], "verfolgt": row["followed"],
                  "verstorben": not a["alive"]}.get(filter or "", True)
            if ok:
                out.append(row)
        key = {"name": lambda r: r["name"], "age": lambda r: -r["age"], "wealth": lambda r: -r["wealth"],
               "friends": lambda r: -r["friends"]}.get(sort, lambda r: r["name"])
        out.sort(key=key)
        return {"people": out, "count": len(out), "followed": sorted(follow)}


class FollowBody(BaseModel):
    agent_id: str = Field(max_length=16)
    follow: bool = True


@router.get("/follow")
def follow_list() -> dict:
    s = svc()
    with s.lock:
        w = s.world
        return {"follow": [{"id": f, "name": _name(w, f), "alive": w.agents[f]["alive"]} for f in w.config.get("follow", []) if f in w.agents]}


@router.post("/follow")
def set_follow(body: FollowBody) -> dict:
    s = svc()
    with s.lock:
        w = s.world
        if body.agent_id not in w.agents:
            raise HTTPException(404, "Bewohner nicht gefunden")
        lst = [f for f in w.config.get("follow", []) if f != body.agent_id]
        if body.follow:
            lst.append(body.agent_id)
        w.config["follow"] = lst[-30:]  # UI preference stored with the world; does not influence the simulation
        return {"follow": w.config["follow"]}


# ------------------------------------------------------------------ society 3.0
@router.get("/society3")
def society3() -> dict:
    s = svc()
    with s.lock:
        w = s.world
        cases = []
        for c in sorted(w.cases.values(), key=lambda c: -c["opened"])[:60]:
            ap = c.get("appeal")
            cases.append({"id": c["id"], "type": c["type"], "accuser": _name(w, c["accuser"]), "accused": _name(w, c["accused"]),
                          "accused_id": c["accused"], "phase": c["status"], "opened": _cal(w, c["opened"]),
                          "witnesses": len(c["evidence"]), "exculpatory": len(c.get("exculpatory", [])),
                          "statement": c.get("statement"), "score": c.get("score"), "threshold": c.get("threshold"),
                          "sanction": c.get("sanction"), "summary": c.get("summary"),
                          "log": [[_cal(w, t), x] for t, x in c.get("log", [])],
                          "appeal": {"status": ap["status"], "filed": _cal(w, ap["filed"]), "judge": _name(w, ap.get("judge")),
                                     "exposed_false_witnesses": len(ap.get("exposed_false_witnesses", []))} if ap else None,
                          "developer_truth": {"true_offender": _name(w, c.get("true_offender")), "verdict_matches_truth": c.get("matches_truth"),
                                              "false_testimony": len(c.get("false_testimony", []))}})
        phases: dict[str, int] = {}
        for c in w.cases.values():
            phases[c["status"]] = phases.get(c["status"], 0) + 1
        prisons = []
        for b in w.buildings.values():
            if b["type"] != "gefaengnis":
                continue
            inmates = [{"id": a["id"], "name": a["name"], "until": _cal(w, a["prison"]["until"]), "case": a["prison"].get("case")}
                       for a in w.living() if a.get("prison") and a["prison"]["building"] == b["id"]]
            prisons.append({"id": b["id"], "name": b.get("name") or "Gefängnis", "region": w.region_name(b["region"]),
                            "condition": round(b["condition"], 2), "inmates": inmates})
        schools = []
        for b in w.buildings.values():
            if b["type"] == "schule":
                schools.append({"id": b["id"], "name": b.get("name") or "Schule", "region": w.region_name(b["region"]),
                                "taught_today": b.get("teacher_day") == w.day, "last_lesson_day": b.get("teacher_day")})
        children = [a for a in w.living() if w.age(a) < R.ADULT_AGE]
        settle = []
        for t in w.settlements.values():
            bt: dict[str, int] = {}
            for b in w.buildings.values():
                if abs(b["x"] - t["x"]) + abs(b["y"] - t["y"]) <= 7:
                    bt[R.BUILDINGS[b["type"]]["label"]] = bt.get(R.BUILDINGS[b["type"]]["label"], 0) + 1
            settle.append({"id": t["id"], "name": t["name"], "active": t["active"], "founded": _cal(w, t["founded"]),
                           "founder": _name(w, t.get("founder")), "population": t.get("pop", 0), "peak": t.get("peak_pop", 0),
                           "homes": len(t["buildings"]), "buildings": bt, "region": w.region_name(t["region"])})
        promises = {"offen": 0, "gehalten": 0, "gebrochen": 0}
        for p in w.promises.values():
            promises[p["status"]] = promises.get(p["status"], 0) + 1
        return {
            "justice": {"cases": cases, "phases": phases, "prisons": prisons,
                        "totals": {"verdicts": w.totals.get("verdicts", 0), "wrongful_convictions": w.totals.get("wrongful_convictions", 0),
                                   "overturned_wrongful": w.totals.get("overturned_wrongful", 0),
                                   "imprisonments": w.totals.get("imprisonments", 0),
                                   "appeals": sum(1 for c in w.cases.values() if c.get("appeal"))}},
            "alliances": [{"id": al["id"], "name": al["name"], "purpose": al["purpose"], "active": al["active"],
                           "members": [_name(w, m) for m in al["members"]], "founded": _cal(w, al["created"])}
                          for al in w.alliances.values()],
            "feuds": [{"a": _name(w, f["a"]), "b": _name(w, f["b"]), "since": _cal(w, f["since"]), "active": f["active"],
                       "intensity": f["intensity"], "causes": f.get("causes", [])} for f in w.feuds.values()],
            "promises": promises,
            "rumors": {"total": len(w.rumors), "exposed": sum(1 for r in w.rumors.values() if r.get("exposed")),
                       "developer_view": [{"origin": _name(w, r["origin"]), "about": _name(w, r["about"]), "text": r["text"],
                                           "reach": len(r["reach"]), "exposed": bool(r.get("exposed")), "false": r["false"]}
                                          for r in list(w.rumors.values())[-15:]]},
            "friendships": sum(len(a.get("friends", [])) for a in w.living()) // 2,
            "education": {"schools": schools, "children": len(children),
                          "school_children": sum(1 for a in children if a["stats"].get("schultage")),
                          "literate_adults": sum(1 for a in w.living() if w.age(a) >= R.ADULT_AGE and "schrift" in a["techs"])},
            "settlements": settle,
        }


# ------------------------------------------------------------------ interiors
ROOMS = {
    "huette": ["Wohn- und Schlafraum"],
    "haus": ["Wohnraum", "Schlafraum", "Vorratskammer"], "steinhaus": ["Wohnraum", "Schlafraum", "Vorratskammer", "Werkecke"],
    "laden": ["Verkaufsraum", "Lager"], "werkstatt": ["Werkraum", "Lager"], "bauernhof": ["Feld", "Scheune"],
    "schule": ["Klassenraum"], "gericht": ["Gerichtssaal", "Beratungszimmer"], "gefaengnis": ["Zellen", "Wachstube"],
    "wachhaus": ["Wachstube"], "heilhaus": ["Behandlungsraum", "Krankenlager"], "krankenhaus": ["Behandlungsraum", "Krankenstation"],
    "versammlungshalle": ["Saal"], "bibliothek": ["Lesesaal", "Archiv"], "lagerhaus": ["Lager"], "markt": ["Marktstände"],
}
ROOM_BY_ACTION = {"sleep": 1, "rest": 1, "eat": 0, "drink": 0, "craft": -1, "work": 0, "shopkeep": 0, "shop": 0, "duty": -1,
                  "seek_care": 1, "heal": 0}


@router.get("/buildings/{bid}/interior")
def interior(bid: str) -> dict:
    """Rooms of a building and who is inside right now (agents standing on the building tile)."""
    s = svc()
    with s.lock:
        w = s.world
        b = w.buildings.get(bid)
        if not b:
            raise HTTPException(404, "Gebäude nicht gefunden")
        names = ROOMS.get(b["type"], ["Innenraum"])
        rooms = [{"name": n, "people": []} for n in names]
        for a in w.living():
            if (a["x"], a["y"]) != (b["x"], b["y"]) or a.get("path"):
                continue
            act = a.get("action") or {}
            if b["type"] == "gefaengnis":
                idx = 0 if a.get("prison") else len(rooms) - 1
            else:
                idx = ROOM_BY_ACTION.get(act.get("type"), 0)
                idx = min(len(rooms) - 1, idx if idx >= 0 else len(rooms) - 1)
            rooms[idx]["people"].append({"id": a["id"], "name": a["name"], "activity": agent_brief(w, a)["activity"],
                                         "prisoner": bool(a.get("prison"))})
        extra: dict = {}
        if b["type"] == "gericht":
            extra["open_cases"] = [{"id": c["id"], "type": c["type"], "accused": _name(w, c["accused"]), "phase": c["status"]}
                                   for c in w.cases.values() if c["region"] == b["region"] and c["status"] in ("ermittlung", "anklage")]
        if b["type"] == "schule":
            extra["taught_today"] = b.get("teacher_day") == w.day
        storage = b.get("inv", {})
        return {"id": b["id"], "label": R.BUILDINGS[b["type"]]["label"], "name": b.get("name"), "owner": _name(w, b.get("owner")),
                "condition": round(b["condition"], 2), "rooms": rooms, "storage": storage, **extra,
                "note": "Räume sind eine Darstellung des Gebäudetyps; Personen und Vorräte entsprechen dem Simulationszustand."}


# ------------------------------------------------------------------ chat with a resident
class AgentChat(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list, max_length=12)
    remember: bool = False  # explicit developer intervention: the resident keeps a memory of the conversation
    max_new_tokens: int = Field(default=200, ge=16, le=400)


def _persona(w, a: dict) -> str:
    from .mind import persona_block
    goals = "; ".join(g["text"] for g in sorted(a.get("agenda", []), key=lambda g: -g["prio"]) if g["status"] == "aktiv")[:300]
    mems = "; ".join(m["x"] for m in sorted(a["ltm"], key=lambda m: -m["s"])[:5])[:600]
    friends = ", ".join(_name(w, f) or f for f in a.get("friends", [])) or "niemand Besonderes"
    return (persona_block(w, a) +
            f" Aktuelle Ziele: {goals or 'keine'}. Stimmung: {C.mood(a) if 'emo' in a else 'ruhig'}. Freunde: {friends}. "
            f"Wichtige Erinnerungen: {mems or 'keine'}. "
            "Du bist eine Figur in einer Simulation und sprichst mit einer Person außerhalb deiner Welt. Antworte in 1–4 Sätzen auf "
            "Deutsch aus deiner Sicht. Erfinde keine Ereignisse, die nicht in deinen Erinnerungen stehen; sag ehrlich, wenn du etwas "
            "nicht weißt. Du musst nicht alles über dich preisgeben. Behaupte nicht, ein echter Mensch oder bewusst zu sein.")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/agents/{aid}/chat")
async def agent_chat(aid: str, body: AgentChat, request: Request) -> StreamingResponse:
    """Talk to a resident through the language model. Does not change the world unless `remember` is set,
    in which case the resident stores a memory marked as a developer intervention."""
    from ..db import ModelVersion, session_scope
    from ..llm.engine import EngineUnavailable, get_engine
    from .service import _model_for
    s = svc()
    eng = get_engine()
    with s.lock:
        w = s.world
        a = w.agents.get(aid)
        if not a or not a["alive"]:
            raise HTTPException(404, "Bewohner nicht gefunden oder verstorben")
        system = _persona(w, a)
        version = _model_for(w, a)
    if not version.startswith("hf:") and eng.status != "ready":
        raise HTTPException(503, f"Sprachmodell nicht bereit ({eng.status})")
    with session_scope() as db:
        v = db.get(ModelVersion, version)
        adapter = v.adapter_path if v else None
    msgs = [{"role": m.get("role"), "content": str(m.get("content", ""))[:1000]} for m in body.history
            if m.get("role") in ("user", "assistant")][-10:]
    msgs.append({"role": "user", "content": body.message})
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    stop = threading.Event()

    def worker() -> None:
        if version.startswith("hf:"):
            # the larger resident model answers itself (no streaming); never silently fall back to another model
            from .service import _hf_agent
            try:
                out = _hf_agent.generate(version[3:], system, body.message, max_tokens=body.max_new_tokens, history=msgs[:-1])
                if out is None:
                    msg = _hf_agent.error or f"{version[3:]} wird noch geladen – bitte gleich erneut versuchen."
                    loop.call_soon_threadsafe(queue.put_nowait, ("error", msg))
                else:
                    loop.call_soon_threadsafe(queue.put_nowait, ("token", out))
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
            except Exception as e:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, ("error", f"{type(e).__name__}: {e}"))
            return
        try:
            for chunk in eng.stream(msgs, version_id=version, adapter_path=adapter, max_new_tokens=body.max_new_tokens,
                                    temperature=0.7, system=system, stop_event=stop):
                loop.call_soon_threadsafe(queue.put_nowait, ("token", chunk))
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
        except EngineUnavailable as e:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", str(e)))
        except Exception as e:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, ("error", f"{type(e).__name__}: {e}"))

    async def gen() -> AsyncIterator[str]:
        threading.Thread(target=worker, daemon=True, name="rubine-agent-chat").start()
        text, status = "", "streaming"
        yield _sse("meta", {"agent": aid, "model_version": version, "remember": body.remember})
        try:
            while True:
                try:
                    kind, val = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    if await request.is_disconnected():
                        status = "stopped"
                        break
                    continue
                if kind == "token":
                    text += str(val)
                    yield _sse("token", {"t": val})
                elif kind == "done":
                    status = "complete"
                    break
                else:
                    yield _sse("error", {"message": str(val)})
                    status = "error"
                    break
        finally:
            stop.set()
        if status == "complete" and body.remember:
            with s.lock:
                w2 = s.world
                a2 = w2.agents.get(aid)
                if a2 and a2["alive"]:
                    w2.remember(a2, "gespraech", f"Eine Stimme von außerhalb fragte: „{body.message[:120]}“ – ich antwortete: „{text[:160]}“",
                                4, tags=["entwickler_eingriff"])
                    w2.emit("system", "entwickler_gespraech", f"Entwickler-Eingriff: Gespräch mit {a2['name']} wurde als Erinnerung gespeichert.",
                            actors=[aid], public=False, witnesses=False, data={"intervention": True})
        if status != "error":
            yield _sse("done", {"status": status, "remembered": bool(body.remember and status == "complete")})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
