"""The world engine: one deterministic tick = 15 simulated minutes.

Order per tick: language-model results → bodies & needs → actions/decisions → institutions.
Daily routines run at the start of each simulated day (06:00). Ticks are never skipped:
at high speed the engine simply runs as fast as it can (time dilation is reported).
"""
from __future__ import annotations

from . import actions as A
from . import cognition, social3
from . import env, life
from . import rules as R
from . import society as S
from .construction import detect_settlements
from .economy import check_loans, gini, pay_wages, wealth
from .mind import _log_decision, _okey
from .perception import perceive
from .state import World, clamp


def step(w: World) -> None:
    w.tick += 1
    tod = w.tick % R.TICKS_PER_DAY
    if tod == 0:
        _daily(w)
    if w.mind is not None:
        w.mind.poll(w)
    order = [a for a in w.agents.values() if a["alive"]]
    w.rng.shuffle(order)
    for a in order:
        if not a["alive"]:
            continue
        try:
            _agent_tick(w, a)
        except Exception as e:  # noqa: BLE001 – one faulty agent must not stop the world
            w.error(f"agent {a['id']}", e)
            a["action"], a["path"], a["pending"] = None, [], None
    if w.tick % R.TICKS_PER_HOUR == 0:
        S.close_proposals(w)
        for a in w.living():
            try:
                cognition.hourly(w, a)
            except Exception as e:  # noqa: BLE001
                w.error(f"cognition {a['id']}", e)
    if tod == 48:  # 18:00
        pay_wages(w)
    if tod == 64:  # 22:00
        env.nightly_heating(w)
        if w.mind is not None:
            _evening_reflections(w)
    w.version += 1


def _agent_tick(w: World, a: dict) -> None:
    life.update_needs(w, a)
    if w.age(a) < 12:
        life.child_care(w, a)
    if a["health"] <= 0:
        life.kill(w, a, life._cause_from_state(a))
        return
    if w.tick % 4 == 0:
        S.check_discoveries(w, a)
    act = a.get("action")
    # interrupt for urgent needs (people do drop what they are doing when parched)
    if act and act["type"] not in ("eat", "drink", "sleep") and (a["needs"]["thirst"] > 0.88 or a["needs"]["hunger"] > 0.92):
        a["action"], a["path"], a["asleep"] = None, [], False
        act = None
    if act and act["type"] == "sleep" and (a["needs"]["thirst"] > 0.9):
        a["action"], a["asleep"] = None, False
        act = None
    if act:
        A.tick_action(w, a)
        return
    decide(w, a)


def decide(w: World, a: dict) -> None:
    pend = a.get("pending")
    if pend:
        res = pend.get("result")
        if res is None and w.tick < pend["until"]:
            return  # still deliberating (shown as "überlegt")
        options = A.generate_options(w, a)
        chosen, by, model, why = None, "regeln", None, ""
        if res and not res.get("invalid"):
            chosen = next((o for o in options if _okey(o) == res["key"]), None)
            if chosen:
                by, model, why = f"Sprachmodell {res['model']}", res["model"], res.get("why", "")
            else:
                why = "Gewählte Option war nicht mehr gültig → Regelentscheidung"
        elif res:
            why = f"Modellantwort ungültig ({res.get('reason')}) → Regelentscheidung"
        else:
            if w.mind is not None:
                w.mind.stats["timeouts"] += 1
            why = "Keine rechtzeitige Modellantwort → Regelentscheidung"
        a["pending"] = None
        if chosen is None and options:
            chosen = A.choose(w, a, options)
            why = why + (f" (Nutzen {chosen['u']})" if chosen else "")
        if chosen:
            d = _log_decision(w, a, "handlung", by, model, sorted(options, key=lambda o: -o["u"]), chosen["label"], why)
            A.start(w, a, chosen, d)
        return
    options = A.generate_options(w, a)
    if not options:
        A.start(w, a, A.opt("rest", "Ausruhen", 0.1, dur=2))
        return
    ranked = sorted(options, key=lambda o: -o["u"])
    top = ranked[:5]
    mind = w.mind
    close_call = [o for o in top[:3] if o["sig"] and o["u"] >= top[0]["u"] - 0.35]
    if mind is not None and close_call and w.age(a) >= R.ADULT_AGE and w.config.get("llm", {}).get("enabled", True) \
            and mind.available():
        a["pending"] = {"req_tick": w.tick, "until": w.tick + int(w.config.get("llm", {}).get("timeout_ticks", 4)),
                        "result": None, "options": [o["label"] for o in top]}
        req = mind.request_decision(w, a, top)
        if req is None:
            a["pending"] = None
        else:
            if a["pending"].get("result") is not None:  # blocking mode: already answered
                decide(w, a)
            return
    chosen = A.choose(w, a, options)
    if chosen["sig"] or chosen is not ranked[0]:
        why = _policy_reason(a, chosen, ranked)
        d = _log_decision(w, a, "handlung", "regeln", None, ranked, chosen["label"], why)
    else:
        d = None
    A.start(w, a, chosen, d)


def _policy_reason(a: dict, chosen: dict, ranked: list[dict]) -> str:
    n = a["needs"]
    top_need = max(("hunger", "thirst", "social", "stress"), key=lambda k: n[k])
    rank = ranked.index(chosen) + 1
    return (f"Regelbasierte Abwägung: Option {rank} von {len(ranked)} (Nutzen {chosen['u']}); stärkster Druck: "
            f"{ {'hunger': 'Hunger', 'thirst': 'Durst', 'social': 'Einsamkeit', 'stress': 'Stress'}[top_need]} {n[top_need]:.0%}.")


def _daily(w: World) -> None:
    env.daily_weather(w)
    env.daily_environment(w)
    life.daily_health(w)
    life.process_births(w)
    life.daily_growth(w)
    S.daily_politics(w)
    S.daily_justice(w)
    S.festivals_today(w)
    social3.daily(w)
    check_loans(w)
    detect_settlements(w)
    for a in w.living():
        w.decay_memories(a)
        a["satisfaction"] = S.satisfaction(w, a)
        _personality_drift(w, a)
        perceive(w, a, 5)
        cognition.daily(w, a)
        _morning_intention(w, a)
    _record_stats(w)
    w.daily.clear()


def _morning_intention(w: World, a: dict) -> None:
    if w.age(a) < R.ADULT_AGE:
        return
    if w.mind is not None and w.mind.available() and w.mind.q.qsize() < 4 and w.rng.random() < 0.25:
        if w.mind.request_dayplan(w, a):
            return
    from .economy import food_days
    goals = {g["type"] for g in a["goals"]}
    weights = {"vorraete": 1.2 - food_days(w, a) / 5, "bauen": 0.9 if not a.get("home") else 0.2 + 0.3 * ("haus" in goals),
               "handel": 0.3 + 0.3 * a["values"]["wealth"], "politik": S.civic_drive(a) * 0.6,
               "wissen": 0.2 + 0.4 * a["personality"]["curiosity"], "familie": 0.2 + 0.3 * ("familie" in goals),
               "erholung": a["needs"]["stress"], "gemeinschaft": 0.2 + 0.3 * a["values"]["community"]}
    focus = max(weights, key=lambda k: weights[k] + w.rng.random() * 0.3)
    a["intention"] = {"focus": focus, "text": "", "by": "regeln", "tick": w.tick}


def _evening_reflections(w: World) -> None:
    cands = [a for a in w.living() if w.age(a) >= R.ADULT_AGE and len(a["stm"]) >= 3]
    w.rng.shuffle(cands)
    for a in cands[: max(1, len(cands) // 5)]:
        w.mind.request_reflection(w, a)


def _personality_drift(w: World, a: dict) -> None:
    """Slow, experience-driven change (max ±0.01 per day per trait)."""
    tags = S.recent_tags(w, a, 1)
    p = a["personality"]
    if tags.get("diebstahl", 0) or tags.get("betrug", 0) or tags.get("gewalt", 0):
        p["trust"] = round(clamp(p["trust"] - 0.01, 0.02, 0.98), 3)
    if tags.get("hilfe", 0):
        p["trust"] = round(clamp(p["trust"] + 0.005, 0.02, 0.98), 3)
    if a["needs"]["stress"] > 0.7:
        p["patience"] = round(clamp(p["patience"] - 0.004, 0.02, 0.98), 3)


def _record_stats(w: World) -> None:
    living = w.living()
    adults = [a for a in living if w.age(a) >= R.ADULT_AGE]
    wealths = [wealth(w, a) for a in adults]
    food_total = sum(int((o.get("inv") or {}).get("food", 0)) for coll in (w.agents, w.buildings, w.institutions)
                     for o in coll.values())
    mk = {}
    for r, items in w.markets.items():
        for it, info in items.items():
            mk.setdefault(it, []).append(info["price"])
    prices = {k: round(sum(v) / len(v), 3) for k, v in mk.items() if "@" not in k}
    gov = [i for i in w.institutions.values() if i["type"] == "regierung" and i["active"]]
    st = {"day": w.day, "tick": w.tick, "year": w.calendar()["year"], "season": w.season,
          "population": len(living), "adults": len(adults), "children": len(living) - len(adults),
          "births_total": w.totals["births"], "deaths_total": w.totals["deaths"],
          "avg_health": round(sum(a["health"] for a in living) / max(1, len(living)), 3),
          "avg_stress": round(sum(a["needs"]["stress"] for a in living) / max(1, len(living)), 3),
          "avg_hunger": round(sum(a["needs"]["hunger"] for a in living) / max(1, len(living)), 3),
          "avg_satisfaction": round(sum(a.get("satisfaction", 0.5) for a in adults) / max(1, len(adults)), 3),
          "sick": sum(1 for a in living if a.get("illness")), "homeless": sum(1 for a in adults if not a.get("home")),
          "food_total": food_total, "wealth_total": round(sum(wealths), 1), "gini": gini(wealths),
          "buildings": len(w.buildings), "sites": len(w.sites),
          "settlements": sum(1 for s in w.settlements.values() if s["active"]),
          "institutions": sum(1 for i in w.institutions.values() if i["active"]),
          "governments": [{"region": w.region_name(g["region"]), "form": g["form"], "legitimacy": g["legitimacy"]} for g in gov],
          "laws": sum(1 for l in w.laws.values() if l["status"] == "aktiv"),
          "thefts_total": w.totals["thefts"], "cases_total": w.totals["cases"], "violence_total": w.totals["violence"],
          "trades_day": w.daily["trades"], "prices": prices,
          "employed": sum(1 for c in w.contracts.values() if c["type"] == "arbeit" and c["status"] == "aktiv"),
          "techs_known": len({t for a in living for t in a["techs"]}),
          "avg_techs": round(sum(len(a["techs"]) for a in living) / max(1, len(living)), 2),
          "money_supply": {c["id"]: c["minted"] for c in w.currencies.values()},
          "forest_tiles": int((w.map["wood"] > 0).sum()), "deforested_day": w.daily["deforested"],
          "river_level": w.river_level, "max_generation": max((a.get("generation", 0) for a in living), default=0)}
    w.stats_buffer.append(st)
    w.config["stats_last"] = st


def run_ticks(w: World, n: int) -> None:
    for _ in range(n):
        step(w)
