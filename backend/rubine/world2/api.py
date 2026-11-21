"""HTTP API for Rubine World 2.0 (/api/world2). All endpoints require login."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..security.auth import require_auth
from . import env
from . import rules as R
from .economy import coin_value, gini, wealth
from .life import health_status
from .mapgen import TERRAIN_CODES
from .service import WorldService, _model_for, get_service
from .society import government_of

router = APIRouter(prefix="/api/world2", dependencies=[Depends(require_auth)])
TERRAIN_CHARS = "WRMHFGAstC"  # one char per terrain code (see mapgen.TERRAIN_CODES)
MAJOR_KINDS = ["welt_erstellt", "regierung_gegruendet", "regierung_aufgeloest", "gesetz", "gesetz_aufgehoben", "wahl", "institution",
               "waehrung", "siedlung", "siedlung_aufgegeben", "geburt", "tod", "entdeckung", "tradition", "hochwasser", "gruendung",
               "urteil", "erbfolge", "vakanz", "partnerschaft", "gewalt", "einsturz", "modellrichtlinie", "benennung"]


def svc() -> WorldService:
    if not get_settings().world2_enabled:
        raise HTTPException(503, "Rubine World 2.0 ist deaktiviert (RUBINE_WORLD2_ENABLED=false)")
    s = get_service()
    if s.world is None:
        raise HTTPException(503, "Welt wird geladen")
    return s


def _name(w, aid: str | None) -> str | None:
    if not aid:
        return None
    a = w.agents.get(aid)
    if a:
        return a["name"]
    inst = w.institutions.get(aid)
    return inst["name"] if inst else aid


def agent_brief(w, a: dict) -> dict:
    act = a.get("action") or {}
    if a.get("pending"):
        label = "überlegt …"
    elif a.get("asleep"):
        label = "schläft"
    else:
        label = act.get("label") or "—"
    return {"id": a["id"], "name": a["name"], "family": a["family"], "x": a["x"], "y": a["y"], "alive": a["alive"],
            "age": int(w.age(a)), "activity": label, "cat": act.get("type"), "asleep": bool(a.get("asleep")),
            "ill": bool(a.get("illness")), "origin": a["origin"], "child": w.age(a) < R.ADULT_AGE,
            "thinking": bool(a.get("pending")), "health": round(a["health"], 2)}


def live_state(w, s: WorldService) -> dict:
    cal = w.calendar()
    wx = w.weather
    return {"tick": w.tick, "calendar": cal, "running": s.running, "speed": s.speed, "tick_rate": s.tick_rate,
            "version": w.version, "map_version": w.config.get("map_version", 0),
            "weather": {k: {"type": v["type"], "label": env.WEATHER_LABEL.get(v["type"], v["type"]), "temp": v["temp"]} for k, v in wx.items()},
            "daylight": _daylight(cal["hour"], cal["minute"]), "river_level": w.river_level,
            "agents": [agent_brief(w, a) for a in w.agents.values() if a["alive"]],
            "population": sum(1 for a in w.agents.values() if a["alive"]),
            "paused_reason": s.paused_reason}


def structures(w) -> dict:
    return {"buildings": [{"id": b["id"], "type": b["type"], "label": R.BUILDINGS[b["type"]]["label"], "x": b["x"], "y": b["y"],
                           "condition": round(b["condition"], 2), "owner": _name(w, b.get("owner")), "name": b.get("name")}
                          for b in w.buildings.values()],
            "sites": [{"id": s["id"], "type": s["type"], "label": R.BUILDINGS[s["type"]]["label"], "x": s["x"], "y": s["y"],
                       "progress": round(s["labor_done"] / s["labor_needed"], 2), "missing": _missing(s), "owner": _name(w, s["owner"])}
                      for s in w.sites.values()],
            "settlements": [{"id": t["id"], "name": t["name"], "x": t["x"], "y": t["y"], "active": t["active"]}
                            for t in w.settlements.values()]}


def _missing(site: dict) -> dict:
    return {it: n - int(site["inv"].get(it, 0)) for it, n in site["need"].items() if int(site["inv"].get(it, 0)) < n}


def _daylight(h: int, m: int) -> float:
    t = h + m / 60
    if 7 <= t <= 19:
        return 1.0
    if 5 <= t < 7:
        return (t - 5) / 2
    if 19 < t <= 21:
        return (21 - t) / 2
    return 0.0


@router.get("/map")
def world_map() -> dict:
    s = svc()
    with s.lock:
        w = s.world
        m = w.map
        rows = ["".join(TERRAIN_CHARS[int(c)] for c in row) for row in m["terrain"]]
        wood = ["".join(str(min(3, int(v) // 12)) for v in row) for row in m["wood"]]
        region = ["".join(chr(65 + int(v)) for v in row) for row in m["region"]]
        roads = [[int(x), int(y)] for y, x in zip(*m["road"].nonzero())]
        bridges = [[int(x), int(y)] for y, x in zip(*m["bridge"].nonzero())]
        flooded = [[int(x), int(y)] for y, x in zip(*m["flooded"].nonzero())]
        return {"w": w.w, "h": w.h, "terrain": rows, "terrain_legend": dict(zip(TERRAIN_CHARS, [R.TERRAINS[t][0] for t in TERRAIN_CODES])),
                "wood": wood, "region": region, "regions": w.region_names, "roads": roads, "bridges": bridges, "flooded": flooded,
                "map_version": w.config.get("map_version", 0), **structures(w)}


@router.get("/state")
def state() -> dict:
    s = svc()
    with s.lock:
        return {**live_state(s.world, s), **structures(s.world), "events": list(s.world.recent_events)[-40:][::-1]}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    s = svc()

    async def gen():
        last_v, last_ev, last_struct, idle = -1, 0, None, 0
        while not await request.is_disconnected():
            w = s.world
            if w is not None and w.version != last_v:
                with s.lock:
                    last_v = w.version
                    payload = live_state(w, s)
                    evs = [e for e in w.recent_events if e["id"] > last_ev]
                    if evs:
                        last_ev = evs[-1]["id"]
                    payload["events"] = evs[-30:]
                    st = structures(w)
                sig = json.dumps(st, sort_keys=True)
                if sig != last_struct:
                    last_struct = sig
                    payload.update(st)
                yield f"event: state\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            else:
                idle += 1
                if idle % 20 == 0:
                    yield ": ping\n\n"
            await asyncio.sleep(0.5 if s.speed >= 20 else 1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/agents")
def agents(include_dead: bool = False) -> list[dict]:
    s = svc()
    with s.lock:
        w = s.world
        out = []
        for a in w.agents.values():
            if not a["alive"] and not include_dead:
                continue
            out.append({**agent_brief(w, a), "wealth": wealth(w, a), "status": health_status(w, a),
                        "death_cause": a.get("death_cause"), "generation": a.get("generation", 0)})
        return out


@router.get("/agents/{aid}")
def agent_detail(aid: str) -> dict:
    s = svc()
    with s.lock:
        w = s.world
        a = w.agents.get(aid)
        if not a:
            raise HTTPException(404, "Bewohner nicht gefunden")
        rels = []
        for key, r in w.relations.items():
            if key.startswith(aid + ">"):
                other = key.split(">", 1)[1]
                rels.append({"id": other, "name": _name(w, other) or w.config.get("_dead_names", {}).get(other, other),
                             "trust": round(r["trust"], 2), "affection": round(r["affection"], 2), "respect": round(r["respect"], 2),
                             "familiarity": round(r["familiarity"], 2), "history": r["hist"][-5:],
                             "partner": a.get("partner") == other, "family": other in a["children"] or other in a["parents"]})
        rels.sort(key=lambda r: -(r["familiarity"] + abs(r["affection"] - 0.5)))
        home = w.buildings.get(a.get("home") or "")
        owned = [{"id": b["id"], "label": R.BUILDINGS[b["type"]]["label"], "condition": round(b["condition"], 2)}
                 for b in w.buildings.values() if b.get("owner") == aid]
        contracts = [c for c in w.contracts.values() if aid in (c.get("worker"), c.get("employer"), c.get("lender"), c.get("borrower"))]
        ltm = sorted(a["ltm"], key=lambda m: -m["s"])[:15]
        facts = sorted(a["facts"].values(), key=lambda f: (-f["conf"], -f["t"]))[:14]
        region = w.home_region(a)
        cur = next((c for c in w.currencies.values() if c["region"] == region and c["active"]), None)
        return {
            "simulated": True,
            "notice": "Simulierter Agent. Innenzustände, Pläne und Begründungen sind Modell- bzw. Regelausgaben, keine nachweisbaren Gedanken oder Gefühle.",
            "id": a["id"], "name": a["name"], "family": a["family"], "age": round(w.age(a), 1), "origin": a["origin"],
            "generation": a.get("generation", 0), "alive": a["alive"], "death_cause": a.get("death_cause"),
            "death_calendar": w.calendar(a["death_tick"])["label"] if a.get("death_tick") is not None else None,
            "partner": _name(w, a.get("partner")), "parents": [{"id": p, "name": _name(w, p)} for p in a["parents"]],
            "children": [{"id": c, "name": _name(w, c)} for c in a["children"]],
            "occupation": _occupation(w, a), "personality": a["personality"], "values": a["values"], "interests": a["interests"],
            "skills": dict(sorted(a["skills"].items(), key=lambda kv: -kv[1])), "techs": [R.TECHS[t]["label"] for t in a["techs"]],
            "research": {R.TECHS[t]["label"]: round(v / R.TECHS[t]["cost"], 2) for t, v in a["research"].items()},
            "needs": {k: round(v, 2) for k, v in a["needs"].items()}, "health": round(a["health"], 2),
            "exposure": round(a["exposure"], 2), "status": health_status(w, a), "illness": a.get("illness"),
            "satisfaction": a.get("satisfaction"), "inventory": a.get("inv", {}), "wealth": wealth(w, a),
            "currency": {"name": cur["name"], "value_in_food": round(coin_value(w, region, cur["id"]), 2)} if cur else None,
            "home": {"id": home["id"], "label": R.BUILDINGS[home["type"]]["label"], "condition": round(home["condition"], 2),
                     "storage": home.get("inv", {})} if home else None,
            "owned": owned, "contracts": contracts, "debts": a.get("debts", 0),
            "goals": a["goals"], "intention": a.get("intention"), "plans": a["plans"],
            "action": (a.get("action") or {}).get("label"), "thinking": a.get("pending"),
            "relations": rels[:10], "memories": ltm, "recent": a["stm"][-8:][::-1], "knowledge": facts,
            "bio": a["bio"][-20:], "decisions": a["decisions"][::-1][:10],
            "model": {"assigned": _model_for(w, a), "last_used": a.get("model")},
            "stats": a["stats"], "banned": a.get("banned"), "arrest_until": a.get("arrest_until"),
        }


def _occupation(w, a: dict) -> str:
    if w.age(a) < 6:
        return "Kleinkind"
    if w.age(a) < R.ADULT_AGE:
        return "Schulkind" if a["stats"].get("schultage") else "Kind"
    c = w.contracts.get(a.get("employer") or "")
    if c and c["status"] == "aktiv":
        return f"angestellt bei {_name(w, c['employer'])}"
    for inst in w.institutions.values():
        if inst["active"] and a["id"] in inst.get("leaders", []):
            return f"Amt in {inst['name']}"
    owned = {b["type"] for b in w.buildings.values() if b.get("owner") == a["id"]}
    if "bauernhof" in owned:
        return "Landwirt/in (eigener Hof)"
    if "werkstatt" in owned:
        return "Handwerker/in (eigene Werkstatt)"
    top = max(a["skills"], key=a["skills"].get)
    return f"selbstständig ({R.SKILL_LABEL[top]})"


@router.get("/buildings/{bid}")
def building(bid: str) -> dict:
    s = svc()
    with s.lock:
        w = s.world
        b = w.buildings.get(bid)
        if not b:
            site = w.sites.get(bid)
            if not site:
                raise HTTPException(404, "Nicht gefunden")
            return {"site": True, **{k: site[k] for k in ("id", "type", "x", "y", "need", "inv", "labor_needed", "labor_done", "started")},
                    "label": R.BUILDINGS[site["type"]]["label"], "owner": _name(w, site["owner"]),
                    "workers": [_name(w, x) for x in site["workers"]], "cause_event": site.get("cause")}
        residents = [a["name"] for a in w.living() if a.get("home") == bid]
        return {"id": b["id"], "type": b["type"], "label": R.BUILDINGS[b["type"]]["label"], "x": b["x"], "y": b["y"],
                "owner": _name(w, b.get("owner")), "condition": round(b["condition"], 2), "storage": b.get("inv", {}),
                "built": w.calendar(b["built"])["label"], "builders": [_name(w, x) for x in b.get("builders", [])],
                "residents": residents, "region": w.region_name(b["region"]), "heated": b.get("heated"),
                "documents": [d["title"] for d in w.documents.values() if d["building"] == bid]}


@router.get("/events")
def events(cat: str | None = None, kind: str | None = None, region: int | None = None, agent: str | None = None,
           before: int | None = None, limit: int = 80) -> list[dict]:
    s = svc()
    with s.lock:
        buf = [e for e in s.world.event_buffer if (cat is None or e["cat"] == cat) and (kind is None or e["kind"] in kind.split(","))
               and (region is None or e["region"] == region) and (agent is None or agent in e["actors"])
               and (before is None or e["id"] < before)]
        store = s.store
    out = buf[::-1][:limit]
    if len(out) < limit:
        b = min([e["id"] for e in out], default=before)
        out += store.events(cat=cat, kind=kind, region=region, agent=agent, before=b, limit=limit - len(out))
    w = s.world
    for e in out:
        e["calendar"] = w.calendar(e["tick"])["label"]
    return out


@router.get("/society")
def society() -> dict:
    s = svc()
    with s.lock:
        w = s.world
        govs, insts = [], []
        for i in w.institutions.values():
            base = {"id": i["id"], "type": i["type"], "name": i["name"], "region": w.region_name(i["region"]), "active": i["active"],
                    "founded": w.calendar(i["founded"])["label"], "founder": _name(w, i.get("founder")),
                    "members": len(i.get("members", [])), "leaders": [_name(w, l) for l in i.get("leaders", [])],
                    "treasury": i.get("inv", {})}
            if i["type"] == "regierung":
                govs.append({**base, "form": i["form"], "form_label": R.GOVERNMENT_FORMS[i["form"]], "legitimacy": i.get("legitimacy"),
                             "protests": i.get("protests", 0), "history": i.get("history", [])[-10:],
                             "dissolved": w.calendar(i["dissolved"])["label"] if i.get("dissolved") else None,
                             "vacant": i.get("vacant", False)})
            else:
                insts.append(base)
        laws = [{"id": l["id"], "title": l["title"], "text": l["text"], "region": w.region_name(l["region"]), "status": l["status"],
                 "effect": R.LAW_EFFECTS[l["effect"]["type"]]["label"], "params": l["effect"].get("params", {}),
                 "adopted": w.calendar(l["adopted"])["label"], "repealed": w.calendar(l["repealed"])["label"] if l.get("repealed") else None,
                 "proposer": _name(w, l.get("proposer"))} for l in w.laws.values()]
        props = sorted(w.proposals.values(), key=lambda p: -p["created"])[:40]
        proposals = [{"id": p["id"], "title": p["title"], "kind": p["kind"], "text": p["text"], "proposer": _name(w, p["proposer"]),
                      "status": p["status"], "rule": p["rule"], "result": p.get("result"), "region": w.region_name(p["region"]),
                      "created": w.calendar(p["created"])["label"], "decided_by": p.get("decided_by"),
                      "votes": {"ja": sum(1 for v in p["votes"].values() if v == "ja"), "nein": sum(1 for v in p["votes"].values() if v == "nein"),
                                "enthaltung": sum(1 for v in p["votes"].values() if v == "enthaltung")}} for p in props]
        cases = [{"id": c["id"], "type": c["type"], "accuser": _name(w, c["accuser"]), "accused": _name(w, c["accused"]),
                  "status": c["status"], "evidence": len(c["evidence"]), "summary": c.get("summary"),
                  "opened": w.calendar(c["opened"])["label"],
                  "developer_truth": {"offender": _name(w, (w.config.get("_eventdata", {}).get(str(c.get("claimed_event"))) or {}).get("offender")),
                                      "verdict_matches_truth": c.get("matches_truth")}}
                 for c in sorted(w.cases.values(), key=lambda c: -c["opened"])[:40]]
        return {"governments": govs, "institutions": insts, "laws": laws, "proposals": proposals, "cases": cases,
                "currencies": [{**c, "region": w.region_name(c["region"])} for c in w.currencies.values()],
                "traditions": list(w.traditions.values()),
                "artworks": [{"title": x["title"], "kind": x["kind"], "author": _name(w, x["author"]), "calendar": w.calendar(x["tick"])["label"],
                              "titled_by": (x.get("named_by") or {}).get("by", "regeln")} for x in list(w.artworks.values())[-20:]][::-1],
                "documents": len(w.documents),
                "regions": [{"index": i, "name": n, "government": (g := government_of(w, i)) and g["name"]} for i, n in enumerate(w.region_names)]}


@router.get("/economy")
def economy() -> dict:
    s = svc()
    with s.lock:
        w = s.world
        adults = [a for a in w.living() if w.age(a) >= R.ADULT_AGE]
        dist = sorted(({"id": a["id"], "name": a["name"], "wealth": wealth(w, a)} for a in adults), key=lambda x: -x["wealth"])
        res = {k: {"remaining": int(w.map[k].sum()), "capacity": int(w.map[f"{k}_cap"].sum()) if f"{k}_cap" in w.map else None}
               for k in ("wood", "stone", "fish", "forage", "herbs")}
        markets = {w.region_name(int(r)): {k: v for k, v in items.items()} for r, items in w.markets.items()}
        return {"wealth": dist, "gini": gini([d["wealth"] for d in dist]), "markets": markets,
                "contracts": [c for c in w.contracts.values() if c["status"] == "aktiv"][:60],
                "contracts_total": len(w.contracts), "ledger": {k: dict(v) for k, v in w.ledger.items()},
                "holdings": dict(w.all_holdings()), "audit": w.audit(), "natural_resources": res,
                "currencies": list(w.currencies.values())}


@router.get("/history")
def history(limit_stats: int = 300) -> dict:
    s = svc()
    stats = s.store.stats(limit_stats)
    major = s.store.events(kind=",".join(MAJOR_KINDS), limit=200)
    with s.lock:
        w = s.world
        buf = [e for e in w.event_buffer if e["kind"] in MAJOR_KINDS]
        timeline = (buf[::-1] + major)[:200]
        for e in timeline:
            e["calendar"] = w.calendar(e["tick"])["label"]
        if w.config.get("stats_last") and (not stats or stats[-1]["day"] != w.config["stats_last"]["day"]):
            stats = stats + [w.config["stats_last"]]
        dead = [{"id": a["id"], "name": f"{a['name']} {a['family']}", "age": int((a["death_tick"] - a["birth_tick"]) / R.TICKS_PER_YEAR),
                 "cause": a["death_cause"], "died": w.calendar(a["death_tick"])["label"], "bio": a["bio"]}
                for a in w.agents.values() if not a["alive"]]
        notable = sorted(w.agents.values(), key=lambda a: -(len(a["bio"]) + a["stats"].get("proposals", 0)))[:8]
        return {"stats": stats, "timeline": timeline, "deceased": dead,
                "notable": [{"id": a["id"], "name": f"{a['name']} {a['family']}", "alive": a["alive"], "bio": a["bio"][-12:]} for a in notable],
                "governments_history": [{"name": i["name"], "form": R.GOVERNMENT_FORMS[i["form"]], "founded": w.calendar(i["founded"])["label"],
                                         "dissolved": w.calendar(i["dissolved"])["label"] if i.get("dissolved") else None,
                                         "history": i.get("history", [])} for i in w.institutions.values() if i["type"] == "regierung"]}


@router.get("/control")
def control_status() -> dict:
    s = svc()
    with s.lock:
        st = s.status()
        st["store"] = s.store.counts()
        st["model_usage"] = s.store.model_usage()
        st["errors_recent"] = list(s.world.errors)[-15:][::-1]
        st["agents"] = [{"id": a["id"], "name": a["name"]} for a in s.world.living() if s.world.age(a) >= R.ADULT_AGE]
        return st


class ControlBody(BaseModel):
    action: str = Field(pattern="^(start|pause|stop|speed|save|backup|new_world|switch_world|limits|model_policy)$")
    speed: int | None = None
    name: str | None = Field(default=None, max_length=60)
    seed: int | None = None
    world_id: str | None = None
    max_population: int | None = None
    max_memories: int | None = None
    calls_per_agent_day: int | None = None
    llm_enabled: bool | None = None
    llm_mode: str | None = None
    timeout_ticks: int | None = None
    default_model: str | None = None
    canary_model: str | None = None
    canary_agents: list[str] = []


@router.post("/control")
def control(body: ControlBody) -> dict:
    s = svc()
    try:
        if body.action == "start":
            s.start()
        elif body.action == "pause":
            s.pause()
        elif body.action == "stop":
            s.stop()
        elif body.action == "speed":
            s.set_speed(int(body.speed if body.speed is not None else 1))
            if body.speed:
                s.start()
        elif body.action == "save":
            return {"saved": s.save()}
        elif body.action == "backup":
            return {"backup": s.backup()}
        elif body.action == "new_world":
            import random
            return {"created": s.new_world(name=(body.name or "Neue Welt").strip() or "Neue Welt",
                                           seed=body.seed if body.seed is not None else random.randint(1, 99999))}
        elif body.action == "switch_world":
            s.switch(body.world_id or "")
        elif body.action == "limits":
            return {"limits": s.set_limits(max_population=body.max_population, max_memories=body.max_memories,
                                           calls_per_agent_day=body.calls_per_agent_day, llm_enabled=body.llm_enabled,
                                           llm_mode=body.llm_mode, timeout_ticks=body.timeout_ticks)}
        elif body.action == "model_policy":
            return {"model": s.set_model_policy(body.default_model or "base", body.canary_model, body.canary_agents)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"ok": True, "running": s.running, "speed": s.speed}
