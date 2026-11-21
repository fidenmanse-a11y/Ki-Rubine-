"""World 3.0 cognition: goals, multi-step plans, emotions, beliefs, opinions, morals and learning.

All of these are *internal model states* of simulated agents (numbers and texts). They drive
behaviour through the utility system; they are not claims about consciousness or feelings.

Three kinds of change are kept strictly apart (and shown separately in the inspector):
  1. Memory            – what happened (memories, facts, beliefs)                 → this module + state.py
  2. Skill development – how good an agent is at things / learned action values   → skills + `lessons`
  3. Model fine-tuning – weights of the language model (LoRA)                     → AI Lab only
"""
from __future__ import annotations

from . import rules as R
from .state import World, clamp, dist

EMOTIONS = ["freude", "aerger", "angst", "trauer", "stolz", "scham", "dankbarkeit"]
EMO_LABEL = {"freude": "Freude", "aerger": "Ärger", "angst": "Angst", "trauer": "Trauer", "stolz": "Stolz",
             "scham": "Scham", "dankbarkeit": "Dankbarkeit"}
MORALS = ["fuersorge", "fairness", "loyalitaet", "autoritaet", "freiheit", "ehrlichkeit"]
MORAL_LABEL = {"fuersorge": "Fürsorge", "fairness": "Fairness", "loyalitaet": "Loyalität", "autoritaet": "Respekt vor Regeln",
               "freiheit": "Freiheit", "ehrlichkeit": "Ehrlichkeit"}

# Causal beliefs: key -> (text, actually true in this world's rules?)
BELIEFS = {
    "hunger_krank": ("Wer hungert, wird leichter krank.", True),
    "kaelte_krank": ("Kälte ohne warmes Haus macht krank.", True),
    "wasser_krank": ("Fern vom Wasser wird man leichter krank.", True),
    "stress_krank": ("Sorgen und Stress machen krank.", True),
    "ansteckung": ("Kranke in der Nähe stecken an.", True),
    "fremde_krank": ("Fremde aus anderen Gruppen bringen Krankheiten.", False),
    "pech_krank": ("Krankheit ist einfach Pech.", False),
    "holz_winter": ("Ohne Brennholz friert man im Winter.", True),
    "vorrat_diebstahl": ("Unbewachte Vorräte werden gestohlen.", True),
    "fluss_hochwasser": ("Häuser direkt am Fluss sind bei Hochwasser in Gefahr.", True),
    "ackerbau_lohnt": ("Ackerbau bringt mehr Nahrung als Sammeln.", True),
    "handel_lohnt": ("Tauschen hilft beiden Seiten.", True),
    "regeln_nutzen": ("Gemeinsame Regeln verhindern Streit.", None),   # value judgement – not checkable
    "verbrechen_lohnt": ("Wer sich nimmt, was er braucht, kommt durch.", None),
}


# ------------------------------------------------------------------ setup / migration
def init_agent(w: World, a: dict) -> None:
    """Add World 3.0 state to an agent (idempotent; used for new agents and old snapshots)."""
    rng = w.rng
    p, v = a["personality"], a["values"]
    if "emo" not in a:
        a["emo"] = {e: 0.05 for e in EMOTIONS}
    a.setdefault("emo_targets", {})
    if "reasoning" not in a:
        base = 0.5 * p["curiosity"] + 0.3 * p["openness"] + 0.2 * rng.random()
        a["reasoning"] = round(clamp(base + rng.gauss(0, 0.1), 0.05, 0.98), 3)
    if "morals" not in a:
        a["morals"] = {
            "fuersorge": round(clamp(0.6 * p["agreeableness"] + 0.4 * v["community"] + rng.gauss(0, 0.08)), 3),
            "fairness": round(clamp(0.7 * v["fairness"] + 0.3 * p["agreeableness"] + rng.gauss(0, 0.08)), 3),
            "loyalitaet": round(clamp(0.5 * v["community"] + 0.5 * v["tradition"] + rng.gauss(0, 0.08)), 3),
            "autoritaet": round(clamp(0.5 * v["tradition"] + 0.3 * v["security"] + 0.2 * p["conscientiousness"] + rng.gauss(0, 0.08)), 3),
            "freiheit": round(clamp(0.7 * v["freedom"] + 0.3 * p["risk"] + rng.gauss(0, 0.08)), 3),
            "ehrlichkeit": round(clamp(0.4 * p["conscientiousness"] + 0.4 * p["agreeableness"] + 0.2 * p["self_control"] + rng.gauss(0, 0.1)), 3),
        }
    a.setdefault("beliefs", {})
    a.setdefault("opinions", {})
    a.setdefault("agenda", [])
    a.setdefault("goal_history", [])
    a.setdefault("lessons", {})
    a.setdefault("lesson_log", [])
    a.setdefault("dev_log", [])
    a.setdefault("friends", [])
    a.setdefault("prison", None)
    a.setdefault("convictions", 0)
    a.setdefault("replan", None)
    a.setdefault("secrets", [])


# ------------------------------------------------------------------ emotions
def feel(w: World, a: dict, emo: str, amount: float, *, target: str | None = None) -> None:
    sens = 1.2 - 0.5 * a["personality"]["self_control"] if emo in ("aerger", "angst") else 1.0
    a["emo"][emo] = round(clamp(a["emo"][emo] + amount * sens), 3)
    if target and emo in ("aerger", "dankbarkeit"):
        t = a["emo_targets"].setdefault(target, {})
        t[emo] = round(clamp(t.get(emo, 0) + amount * sens), 3)


def decay_emotions(w: World, a: dict) -> None:
    """Hourly: emotions fade toward a low baseline; sadness lingers longer."""
    for e in EMOTIONS:
        rate = 0.985 if e == "trauer" else 0.96
        a["emo"][e] = round(max(0.02, a["emo"][e] * rate), 3)
    for tid in list(a["emo_targets"]):
        t = a["emo_targets"][tid]
        for k in list(t):
            t[k] = round(t[k] * 0.993, 3)
            if t[k] < 0.03:
                t.pop(k)
        if not t:
            a["emo_targets"].pop(tid)


def mood(a: dict) -> str:
    e = a["emo"]
    top = max(e, key=e.get)
    return EMO_LABEL[top] if e[top] > 0.2 else "ausgeglichen"


# ------------------------------------------------------------------ beliefs (with uncertainty)
def believe(w: World, a: dict, key: str, evidence: float = 1.0) -> None:
    b = a["beliefs"].setdefault(key, {"n": 0.0, "since": w.tick})
    b["n"] = round(b["n"] + evidence, 2)
    b["conf"] = round(b["n"] / (b["n"] + 2.0), 3)  # more evidence -> more certain, never 1
    b["t"] = w.tick


def belief_conf(a: dict, key: str) -> float:
    return a["beliefs"].get(key, {}).get("conf", 0.0)


def attribute_illness(w: World, a: dict, factors: dict[str, float]) -> str:
    """Causal attribution after falling ill. Better reasoning -> more likely to name the real main cause;
    otherwise people fall back to a salient but wrong explanation (strangers, bad luck)."""
    real = max(factors, key=factors.get) if factors and max(factors.values()) > 0 else None
    if real and w.rng.random() < 0.35 + 0.6 * a["reasoning"]:
        key = {"hunger": "hunger_krank", "kaelte": "kaelte_krank", "wasser": "wasser_krank", "stress": "stress_krank",
               "ansteckung": "ansteckung"}[real]
    else:
        strangers = [x for x in w.agents_near(a["x"], a["y"], 5) if x["id"] != a["id"] and x["origin"] != a["origin"]]
        key = "fremde_krank" if strangers and a["personality"]["trust"] < 0.55 else "pech_krank"
    believe(w, a, key)
    return key


# ------------------------------------------------------------------ opinions about other agents
def opinion(a: dict, other: str) -> dict:
    return a["opinions"].setdefault(other, {"h_a": 1.0, "h_b": 1.0, "verdacht": 0.0, "notiz": []})


def judge_person(w: World, a: dict, other: str, honest: bool, weight: float = 1.0, note: str | None = None) -> None:
    o = opinion(a, other)
    if honest:
        o["h_a"] = round(o["h_a"] + weight, 2)
    else:
        o["h_b"] = round(o["h_b"] + weight, 2)
        o["verdacht"] = round(clamp(o["verdacht"] + 0.25 * weight), 3)
    if note:
        o["notiz"] = (o["notiz"] + [[w.tick, note]])[-6:]


def honesty_estimate(a: dict, other: str) -> tuple[float, float]:
    o = a["opinions"].get(other)
    if not o:
        return 0.5, 1.0
    n = o["h_a"] + o["h_b"]
    return round(o["h_a"] / n, 3), round(2.0 / n, 3)  # (estimate, uncertainty 0..1)


# ------------------------------------------------------------------ lessons (learning from consequences)
def learn_lesson(w: World, a: dict, action: str, delta: float, text: str) -> None:
    """Experience-based adjustment of how attractive an action type seems (bounded, slowly forgetting)."""
    old = a["lessons"].get(action, 0.0)
    a["lessons"][action] = round(max(-0.8, min(0.6, old + delta)), 3)
    a["lesson_log"] = (a["lesson_log"] + [[w.tick, action, round(delta, 3), text]])[-20:]
    w.remember(a, "lektion", text, 5 + 3 * abs(delta), tags=["lektion"])


# ------------------------------------------------------------------ goals
GOAL_TEXT = {
    "zuhause": "Ein eigenes Zuhause bauen", "vorrat": "Genug Vorräte anlegen", "heilung": "Wieder gesund werden",
    "hof": "Einen eigenen Bauernhof aufbauen", "werkstatt": "Eine eigene Werkstatt aufbauen", "laden": "Einen eigenen Laden eröffnen",
    "besseres_zuhause": "Ein besseres Haus bauen", "familie": "Eine Partnerschaft finden", "kind": "Ein Kind großziehen",
    "wissen": "Neues Wissen erwerben", "amt": "Ein öffentliches Amt übernehmen", "gemeinschaft": "Etwas für die Gemeinschaft tun",
    "wohlstand": "Wohlstand aufbauen", "gerechtigkeit": "Gerechtigkeit erreichen", "berufung": "Das Urteil anfechten",
    "versoehnung": "Sich versöhnen", "fehde": "Sich gegen jemanden behaupten", "auswandern": "Woanders neu anfangen",
    "ruf": "Den eigenen Ruf wiederherstellen", "freiheit": "Die Haft überstehen",
}


def _owns(w: World, a: dict, btype: str) -> bool:
    return any(b.get("owner") == a["id"] and b["type"] == btype for b in w.buildings.values())


def goal_candidates(w: World, a: dict) -> list[dict]:
    """Which goals would make sense for this agent now, and how important are they to them (priority)."""
    from .economy import food_days, wealth
    from .society import government_of
    p, v = a["personality"], a["values"]
    motives = {g["type"] for g in a.get("goals", [])}
    out: list[dict] = []

    def add(gtype: str, prio: float, why: str, target: str | None = None, extra: dict | None = None) -> None:
        out.append({"type": gtype, "prio": round(clamp(prio), 3), "why": why, "target": target, **(extra or {})})

    if a.get("prison"):
        add("freiheit", 1.0, "Ich bin in Haft.")
        return out
    fd = food_days(w, a)
    home = w.buildings.get(a.get("home") or "")
    winter_soon = w.season >= 2
    if not home:
        add("zuhause", 0.75 + 0.2 * winter_soon + 0.2 * a["exposure"] + 0.1 * ("haus" in motives), "Ich habe kein Dach über dem Kopf.")
    if fd < 3:
        add("vorrat", 0.55 + 0.3 * v["security"] + 0.3 * a["emo"]["angst"] + 0.2 * (fd < 1), f"Meine Vorräte reichen nur {fd:.1f} Tage.",
            extra={"days": round(3 + 4 * v["security"], 1)})
    if a.get("illness") and a["illness"]["severity"] > 0.25:
        add("heilung", 0.8, f"Ich bin an {a['illness']['name']} erkrankt.")
    if home:
        if "ackerbau" in a["techs"] and not _owns(w, a, "bauernhof"):
            add("hof", 0.3 + 0.4 * a["skills"]["farming"] + 0.2 * v["wealth"] + 0.2 * belief_conf(a, "ackerbau_lohnt"), "Ein Hof sichert Nahrung.")
        if "werkzeugbau" in a["techs"] and not _owns(w, a, "werkstatt") and p["ambition"] > 0.55:
            add("werkstatt", 0.2 + 0.4 * p["ambition"] + 0.2 * a["skills"]["crafting"], "Mit einer Werkstatt kann ich Werkzeug herstellen.")
        if not _owns(w, a, "laden") and a["skills"]["trading"] > 0.35 and p["ambition"] > 0.5 and a["stats"].get("trades", 0) > 5:
            add("laden", 0.25 + 0.4 * a["skills"]["trading"], "Ich handle gern – ein Laden wäre ein fester Ort dafür.")
        if home["type"] == "huette" and "holzbau" in a["techs"]:
            add("besseres_zuhause", 0.25 + 0.3 * v["security"], "Meine Hütte ist klein und zugig.")
    age = w.age(a)
    if not a.get("partner") and 20 <= age <= 50 and ("familie" in motives or v["tradition"] > 0.6):
        add("familie", 0.3 + 0.3 * ("familie" in motives) + 0.2 * a["needs"]["social"], "Ich möchte nicht allein bleiben.")
    if a.get("partner") and home and age <= 44 and ("familie" in motives) and len(a["children"]) < 3:
        add("kind", 0.3 + 0.2 * v["tradition"], "Wir wünschen uns Nachwuchs.")
    research = [t for t, s in R.TECHS.items() if t not in a["techs"] and s["cost"] > 0 and all(x in a["techs"] for x in s["prereq"])]
    if research and p["curiosity"] > 0.45:
        t = max(research, key=lambda t: a["research"].get(t, 0) + (0.5 if any(t == d["tech"] for d in w.documents.values()) else 0))
        add("wissen", 0.15 + 0.5 * p["curiosity"] + 0.15 * ("wissen" in motives), f"Ich will {R.TECHS[t]['label']} verstehen.",
            extra={"tech": t})
    gov = government_of(w, w.home_region(a))
    if gov and p["ambition"] > 0.6 and a["skills"]["leadership"] > 0.15 and a["id"] not in gov.get("leaders", []):
        add("amt", 0.25 + 0.4 * p["ambition"] + 0.2 * ("ansehen" in motives), "Ich könnte die Gemeinschaft führen.")
    if v["community"] > 0.6:
        add("gemeinschaft", 0.2 + 0.4 * v["community"] + 0.1 * a["morals"]["fuersorge"], "Die Gemeinschaft ist mir wichtig.")
    if v["wealth"] > 0.55:
        target = round(wealth(w, a) * 1.6 + 20)
        add("wohlstand", 0.2 + 0.4 * v["wealth"] + 0.1 * p["ambition"], "Ich will mehr besitzen.", extra={"amount": target})
    for c in w.cases.values():
        if c["accuser"] == a["id"] and c["status"] in ("behauptung", "ermittlung", "anklage"):
            add("gerechtigkeit", 0.35 + 0.4 * a["emo"]["aerger"] + 0.2 * a["morals"]["fairness"], "Mein Vorwurf ist noch nicht geklärt.",
                target=c["accused"], extra={"case": c["id"]})
            break
    for c in w.cases.values():
        if c["accused"] == a["id"] and c["status"] == "schuldig" and not c.get("appeal") and \
                w.tick - (c.get("verdict") or {}).get("tick", w.tick) < 4 * R.TICKS_PER_DAY:
            innocent = c.get("true_offender") != a["id"]
            add("berufung", (0.85 if innocent else 0.2 + 0.3 * (1 - a["morals"]["ehrlichkeit"])),
                "Ich wurde verurteilt" + (", obwohl ich es nicht war." if innocent else "."), extra={"case": c["id"]})
            break
    for tid, t in a["emo_targets"].items():
        other = w.agents.get(tid)
        if not other or not other["alive"]:
            continue
        r = w.rel(a["id"], tid)
        if t.get("aerger", 0) > 0.45:
            if p["agreeableness"] > 0.55 and r["familiarity"] > 0.3:
                add("versoehnung", 0.25 + 0.3 * p["agreeableness"], f"Der Streit mit {other['name']} belastet mich.", target=tid)
            elif p["agreeableness"] < 0.45:
                add("fehde", 0.2 + 0.4 * t["aerger"] * (1 - p["self_control"]), f"{other['name']} hat mir geschadet.", target=tid)
    crowd = len(w.agents_near(a["x"], a["y"], 6))
    if home and (crowd > 14 or a["stats"].get("depleted_seen", 0) > 3) and v["freedom"] + p["risk"] > 1.15 and age < 50:
        add("auswandern", 0.15 + 0.3 * v["freedom"] + 0.2 * p["risk"], "Hier ist es eng geworden – anderswo gibt es Platz.")
    if a.get("convictions", 0) and not a.get("prison"):
        add("ruf", 0.35 + 0.3 * (1 - a["personality"]["conflict_avoidance"]) * 0.5 + 0.3 * a["emo"]["scham"],
            "Nach meiner Verurteilung misstrauen mir viele.")
    return out


def _new_goal(w: World, a: dict, cand: dict) -> dict:
    w.counters["G"] += 1
    gid = f"G{w.counters['G']:05d}"
    text = GOAL_TEXT[cand["type"]]
    if cand.get("target") and cand["target"] in w.agents:
        text += f" ({w.agents[cand['target']]['name']})"
    if cand.get("tech"):
        text = f"{R.TECHS[cand['tech']]['label']} lernen"
    g = {"id": gid, "type": cand["type"], "text": text, "why": cand["why"], "prio": cand["prio"], "status": "aktiv",
         "created": w.tick, "target": cand.get("target"), "params": {k: v for k, v in cand.items()
                                                                    if k in ("days", "tech", "amount", "case")},
         "plan": None, "progress_t": w.tick, "attempts": 0, "replans": 0, "by": "regeln", "motivation": None,
         "start_stats": {"donations": a["stats"].get("donated", 0), "public_builds": a["stats"].get("public_builds", 0)}}
    g["plan"] = make_plan(w, a, g)
    return g


def manage_goals(w: World, a: dict, reason: str | None = None) -> None:
    """Re-evaluate the agenda: adopt, keep, suspend, complete or abandon goals."""
    if w.age(a) < 14:
        return
    cands = {c["type"] + "|" + str(c.get("target")): c for c in goal_candidates(w, a)}
    capacity = 2 + int(round(2 * a["reasoning"]))
    changed = []
    for g in a["agenda"]:
        if g["status"] not in ("aktiv", "zurueckgestellt"):
            continue
        if goal_done(w, a, g):
            finish_goal(w, a, g, "erreicht", "Ziel erreicht.")
            changed.append(f"„{g['text']}“ erreicht")
            continue
        key = g["type"] + "|" + str(g.get("target"))
        c = cands.pop(key, None)
        if c is None and g["type"] not in ("wohlstand", "wissen", "gemeinschaft", "familie", "kind", "amt"):
            finish_goal(w, a, g, "hinfaellig", "Der Anlass besteht nicht mehr.")
            changed.append(f"„{g['text']}“ ist hinfällig")
            continue
        if c:
            g["prio"] = round(0.7 * g["prio"] + 0.3 * c["prio"], 3)
            g["why"] = c["why"]
        if a.get("building_plan") and g["plan"] and (current_step(g) or {}).get("acts", [None])[0] == "build_start":
            g["progress_t"] = max(g["progress_t"], w.tick - R.TICKS_PER_DAY)  # waiting for another project is not stalling
        stalled_days = (w.tick - g["progress_t"]) / R.TICKS_PER_DAY
        patience = 3 + 8 * a["personality"]["patience"]
        if stalled_days > patience and g["attempts"] > 6:
            finish_goal(w, a, g, "aufgegeben", f"Seit {stalled_days:.0f} Tagen kein Fortschritt.")
            learn_lesson(w, a, f"ziel:{g['type']}", -0.1, f"Mein Ziel „{g['text']}“ war zu schwer zu erreichen.")
            changed.append(f"„{g['text']}“ aufgegeben (kein Fortschritt)")
    for c in cands.values():
        if c["prio"] > 0.3:
            g = _new_goal(w, a, c)
            g["status"] = "zurueckgestellt"
            a["agenda"].append(g)
    live = [g for g in a["agenda"] if g["status"] in ("aktiv", "zurueckgestellt")]
    # commitment: active goals get a bonus, so agents do not flip-flop every day
    live.sort(key=lambda g: g["prio"] + (0.15 if g["status"] == "aktiv" else 0), reverse=True)
    for i, g in enumerate(live):
        new_status = "aktiv" if i < capacity else "zurueckgestellt"
        if g["status"] != new_status:
            if new_status == "aktiv":
                changed.append(f"verfolgt jetzt „{g['text']}“")
                if w.mind is not None and w.mind.available():
                    w.mind.request_goal(w, a, g)
            else:
                changed.append(f"stellt „{g['text']}“ zurück")
            g["status"] = new_status
    a["agenda"] = [g for g in a["agenda"] if g["status"] in ("aktiv", "zurueckgestellt")][:10]
    if changed and reason:
        w.emit("sozial", "planaenderung", f"{a['name']} passt Ziele an ({reason}): {'; '.join(changed[:3])}.", actors=[a["id"]],
               x=a["x"], y=a["y"], public=False, witnesses=False, data={"reason": reason})


def finish_goal(w: World, a: dict, g: dict, status: str, why: str) -> None:
    g["status"] = status
    g["ended"] = w.tick
    g["end_reason"] = why
    a["goal_history"] = (a["goal_history"] + [{"text": g["text"], "type": g["type"], "status": status, "why": why,
                                                "created": g["created"], "ended": w.tick, "replans": g["replans"], "by": g["by"]}])[-30:]
    if status == "erreicht":
        feel(w, a, "freude", 0.35)
        feel(w, a, "stolz", 0.3)
        a["bio"].append([w.tick, f"Ziel erreicht: {g['text']}."])
        w.remember(a, "biografie", f"Ich habe mein Ziel erreicht: {g['text']}.", 7, tags=["ziel"])
        a["stats"]["goals_reached"] = a["stats"].get("goals_reached", 0) + 1
    elif status == "aufgegeben":
        feel(w, a, "trauer", 0.15)
        a["stats"]["goals_abandoned"] = a["stats"].get("goals_abandoned", 0) + 1


def goal_done(w: World, a: dict, g: dict) -> bool:
    from .economy import food_days, wealth
    t, prm = g["type"], g["params"]
    if t == "zuhause":
        return bool(a.get("home"))
    if t == "vorrat":
        return food_days(w, a) >= prm.get("days", 4)
    if t == "heilung":
        return not a.get("illness")
    if t in ("hof", "werkstatt", "laden"):
        return _owns(w, a, {"hof": "bauernhof"}.get(t, t))
    if t == "besseres_zuhause":
        h = w.buildings.get(a.get("home") or "")
        return bool(h and h["type"] in ("haus", "steinhaus"))
    if t == "familie":
        return bool(a.get("partner"))
    if t == "kind":
        return bool(a.get("expecting")) or any(w.agents[c]["birth_tick"] > g["created"] for c in a["children"] if c in w.agents)
    if t == "wissen":
        return prm.get("tech") in a["techs"]
    if t == "amt":
        return any(a["id"] in i.get("leaders", []) for i in w.institutions.values() if i["active"])
    if t == "gemeinschaft":
        s0 = g.get("start_stats", {})
        return a["stats"].get("donated", 0) - s0.get("donations", 0) + 2 * (a["stats"].get("public_builds", 0) - s0.get("public_builds", 0)) >= 6
    if t == "wohlstand":
        return wealth(w, a) >= prm.get("amount", 1e9)
    if t == "gerechtigkeit":
        c = w.cases.get(prm.get("case") or "")
        return not c or c["status"] not in ("behauptung", "ermittlung", "anklage")
    if t == "berufung":
        c = w.cases.get(prm.get("case") or "")
        return not c or c.get("appeal") is not None
    if t == "versoehnung":
        return a["emo_targets"].get(g["target"], {}).get("aerger", 0) < 0.15 and w.rel(a["id"], g["target"])["affection"] >= 0.5
    if t == "fehde":
        other = w.agents.get(g["target"] or "")
        return not other or not other["alive"] or a["emo_targets"].get(g["target"], {}).get("aerger", 0) < 0.15
    if t == "auswandern":
        h = w.buildings.get(a.get("home") or "")
        return bool(h and h.get("built", 0) > g["created"] and w.region_of(h["x"], h["y"]) != g.get("from_region", -1))
    if t == "ruf":
        known = [r for k, r in w.relations.items() if k.endswith(">" + a["id"]) and r["familiarity"] > 0.2]
        return bool(known) and sum(r["trust"] for r in known) / len(known) > 0.55
    if t == "freiheit":
        return not a.get("prison")
    return False


# ------------------------------------------------------------------ planning
def _mat_need(w: World, a: dict, btype: str) -> dict:
    from .economy import stock
    return {it: n - stock(w, a, it) for it, n in R.BUILDINGS[btype]["mat"].items() if stock(w, a, it) < n}


def _build_plan(w: World, a: dict, btype: str) -> list[dict]:
    steps = []
    for it, n in R.BUILDINGS[btype]["mat"].items():
        act = {"wood": "chop", "stone": "quarry"}.get(it, "forage")
        steps.append({"text": f"{n} {R.ITEM_LABEL[it]} beschaffen", "cond": {"have": it, "n": n, "for": btype}, "acts": [act, "trade"],
                      "expect": f"Dann habe ich genug {R.ITEM_LABEL[it]} für den Bau."})
    steps.append({"text": f"Bauplatz wählen und {R.BUILDINGS[btype]['label']} beginnen", "cond": {"site": btype},
                  "acts": ["build_start"], "data": {"btype": btype}, "expect": "Eine Baustelle entsteht."})
    steps.append({"text": "Material zur Baustelle bringen", "cond": {"site_supplied": btype}, "acts": ["deliver"],
                  "expect": "Die Baustelle hat alles Material."})
    steps.append({"text": f"{R.BUILDINGS[btype]['label']} fertig bauen", "cond": {"owns": btype}, "acts": ["build"],
                  "expect": f"Ich besitze ein(e) {R.BUILDINGS[btype]['label']}."})
    first = _other_site_step(w, a, btype)
    return ([first] if first else []) + steps


def _other_site_step(w: World, a: dict, btype: str) -> dict | None:
    """A person can run only one own construction site. If another one is unfinished, the planner either
    finishes it first (little missing) or puts it on hold to resume later. Both are plan decisions, not rules."""
    from .construction import missing_materials
    s = w.sites.get(a.get("building_plan") or "")
    if not s or s["type"] == btype:
        return None
    missing = sum(missing_materials(s).values())
    labor_left = 1 - s["labor_done"] / max(1e-6, s["labor_needed"])
    urgent = btype in R.SHELTER_TYPES and not a.get("home")
    label = R.BUILDINGS[s["type"]]["label"]
    if missing <= 2 and (labor_left < 0.6 or not urgent):
        return {"text": f"Begonnene Baustelle ({label}) zuerst fertigstellen", "cond": {"no_other_site": btype},
                "acts": ["deliver", "build", "quarry", "chop", "trade"], "expect": "Dann ist der Weg frei für das nächste Bauprojekt."}
    a.setdefault("paused_sites", [])
    if s["id"] not in a["paused_sites"]:
        a["paused_sites"].append(s["id"])
    a["building_plan"] = None
    w.remember(a, "entscheidung", f"Ich stelle die Baustelle ({label}) zurück, {R.BUILDINGS[btype]['label']} ist jetzt wichtiger.", 4)
    return None


def make_plan(w: World, a: dict, g: dict) -> dict:
    """Hierarchical plan for a goal. Planning depth depends on the agent's reasoning ability:
    myopic agents plan only the next steps and extend the plan later."""
    t, prm = g["type"], g["params"]
    tgt = g.get("target")
    steps: list[dict]
    if t == "zuhause":
        btype = "haus" if "holzbau" in a["techs"] and w.rng.random() < 0.3 + 0.5 * a["reasoning"] else "huette"
        steps = _build_plan(w, a, btype)
        steps[-1]["cond"] = {"home": True}
    elif t in ("hof", "werkstatt", "laden"):
        steps = _build_plan(w, a, {"hof": "bauernhof"}.get(t, t))
    elif t == "besseres_zuhause":
        steps = _build_plan(w, a, "steinhaus" if "steinbau" in a["techs"] else "haus")
    elif t == "vorrat":
        steps = [{"text": f"Vorräte für {prm.get('days', 4)} Tage sammeln", "cond": {"food_days": prm.get("days", 4)},
                  "acts": ["forage", "fish", "farm", "trade", "work"], "expect": "Ich muss mir keine Sorgen ums Essen machen."}]
    elif t == "heilung":
        steps = [{"text": "Behandlung suchen und ausruhen", "cond": {"healthy": True}, "acts": ["seek_care", "rest", "medicine", "sleep"],
                  "expect": "Die Krankheit klingt ab."}]
    elif t == "familie":
        steps = [{"text": "Menschen näher kennenlernen", "cond": {"close_friend": True}, "acts": ["talk", "help"],
                  "expect": "Jemand ist mir vertraut."},
                 {"text": "Eine Partnerschaft vorschlagen", "cond": {"partner": True}, "acts": ["partner"], "expect": "Wir sind ein Paar."}]
    elif t == "kind":
        steps = [{"text": "Genug Vorräte für eine Familie", "cond": {"food_days": 3}, "acts": ["forage", "fish", "farm"], "expect": "Wir können ein Kind ernähren."},
                 {"text": "Mit dem Partner über ein Kind sprechen", "cond": {"child_planned": True}, "acts": ["child"], "expect": "Ein Kind ist unterwegs."}]
    elif t == "wissen":
        steps = [{"text": f"{R.TECHS[prm['tech']]['label']} erforschen oder lernen", "cond": {"tech": prm["tech"]},
                  "acts": ["research", "read"], "data": {"tech": prm["tech"]}, "expect": "Neues Wissen eröffnet neue Möglichkeiten."}]
    elif t == "amt":
        steps = [{"text": "Ansehen gewinnen (helfen, spenden, Gespräche)", "cond": {"respected": 0.58}, "acts": ["help", "donate", "talk"],
                  "expect": "Andere respektieren mich."},
                 {"text": "Bei der nächsten Wahl kandidieren", "cond": {"in_office": True}, "acts": ["candidate", "propose", "persuade"],
                  "expect": "Ich werde gewählt."}]
    elif t == "gemeinschaft":
        steps = [{"text": "Spenden oder an öffentlichen Bauten helfen", "cond": {"goal_done": True}, "acts": ["donate", "build", "deliver", "help"],
                  "expect": "Die Gemeinschaft profitiert."}]
    elif t == "wohlstand":
        steps = [{"text": f"Vermögen auf {prm.get('amount')} steigern", "cond": {"goal_done": True},
                  "acts": ["trade", "work", "craft", "farm", "forage", "fish", "chop", "hire"], "expect": "Ich bin abgesichert."}]
    elif t == "gerechtigkeit":
        steps = [{"text": "Dafür sorgen, dass der Fall geprüft wird", "cond": {"goal_done": True}, "acts": ["propose", "persuade", "talk"],
                  "expect": "Ein Urteil wird gesprochen."}]
    elif t == "berufung":
        steps = [{"text": "Berufung einlegen", "cond": {"goal_done": True}, "acts": ["appeal"], "expect": "Der Fall wird neu verhandelt."}]
    elif t == "versoehnung":
        steps = [{"text": "Das Gespräch suchen", "cond": {"affection": 0.5}, "acts": ["talk", "help", "apologize"], "target": tgt,
                  "expect": "Wir verstehen uns wieder."}]
    elif t == "fehde":
        steps = [{"text": "Gegen die andere Person auftreten", "cond": {"goal_done": True}, "acts": ["confront", "spread_rumor", "persuade"],
                  "target": tgt, "expect": "Die andere Person verliert an Einfluss."}]
    elif t == "auswandern":
        g["from_region"] = w.home_region(a)
        steps = [{"text": "Ein neues Gebiet erkunden", "cond": {"far_from_home": 12}, "acts": ["explore"], "expect": "Ich kenne einen besseren Ort."},
                 {"text": "Dort ein neues Zuhause bauen", "cond": {"goal_done": True}, "acts": ["build_start", "deliver", "build", "chop"],
                  "data": {"btype": "huette", "far": True}, "expect": "Ich lebe an einem neuen Ort."}]
    elif t == "ruf":
        steps = [{"text": "Anderen helfen und Versprechen halten", "cond": {"goal_done": True}, "acts": ["help", "donate", "keep_promise", "talk"],
                  "expect": "Man vertraut mir wieder."}]
    elif t == "freiheit":
        steps = [{"text": "Die Haft ruhig überstehen", "cond": {"goal_done": True}, "acts": ["rest", "sleep", "talk", "eat"],
                  "expect": "Ich komme frei."}]
    else:
        steps = []
    horizon = 1 + int(round(3 * a["reasoning"]))
    for s in steps:
        s.setdefault("done", False)
        s.setdefault("attempts", 0)
    return {"steps": steps, "current": 0, "created": w.tick, "horizon": horizon, "visible": min(len(steps), horizon),
            "revisions": 0}


def step_done(w: World, a: dict, g: dict, s: dict) -> bool:
    from .economy import food_days, stock
    c = s["cond"]
    if "have" in c:
        site = _site_for(w, a, c.get("for"))
        return stock(w, a, c["have"]) >= c["n"] or site is not None and int(site["inv"].get(c["have"], 0)) >= site["need"].get(c["have"], 0)
    if "no_other_site" in c:
        return _site_for(w, a, None) is None or _site_for(w, a, c["no_other_site"]) is not None
    if "site" in c:
        return _site_for(w, a, c["site"]) is not None or _owns(w, a, c["site"]) or (c["site"] in R.SHELTER_TYPES and _has_home_type(w, a, c["site"]))
    if "site_supplied" in c:
        s2 = _site_for(w, a, c["site_supplied"])
        from .construction import missing_materials
        return (s2 is not None and not missing_materials(s2)) or _owns(w, a, c["site_supplied"])
    if "owns" in c:
        return _owns(w, a, c["owns"])
    if "home" in c:
        return bool(a.get("home"))
    if "food_days" in c:
        return food_days(w, a) >= c["food_days"]
    if "healthy" in c:
        return not a.get("illness")
    if "close_friend" in c:
        return any(w.rel(a["id"], o)["affection"] > 0.66 and w.rel(a["id"], o)["familiarity"] > 0.3 for o in _acquaintances(w, a))
    if "partner" in c:
        return bool(a.get("partner"))
    if "child_planned" in c:
        return goal_done(w, a, g)
    if "tech" in c:
        return c["tech"] in a["techs"]
    if "respected" in c:
        known = [r for k, r in w.relations.items() if k.endswith(">" + a["id"]) and r["familiarity"] > 0.15]
        return bool(known) and sum(r["respect"] for r in known) / len(known) >= c["respected"]
    if "in_office" in c:
        return goal_done(w, a, g)
    if "affection" in c:
        return w.rel(a["id"], g["target"])["affection"] >= c["affection"]
    if "far_from_home" in c:
        h = w.buildings.get(a.get("home") or "")
        return h is None or dist(a["x"], a["y"], h["x"], h["y"]) >= c["far_from_home"]
    if "goal_done" in c:
        return goal_done(w, a, g)
    return False


def _acquaintances(w: World, a: dict) -> list[str]:
    pre = a["id"] + ">"
    return [k[len(pre):] for k, r in w.relations.items() if k.startswith(pre) and r["familiarity"] > 0.1]


def _site_for(w: World, a: dict, btype: str | None) -> dict | None:
    s = w.sites.get(a.get("building_plan") or "")
    if s and (btype is None or s["type"] == btype):
        return s
    return None


def _site_supplied_with(w: World, a: dict, item: str) -> bool:
    s = _site_for(w, a, None)
    return bool(s) and int(s["inv"].get(item, 0)) >= s["need"].get(item, 0)


def _has_home_type(w: World, a: dict, btype: str) -> bool:
    h = w.buildings.get(a.get("home") or "")
    return bool(h and h["type"] == btype)


def advance_plans(w: World, a: dict) -> None:
    """Check plan steps; mark progress; extend myopic plans; replan when blocked."""
    for g in a["agenda"]:
        if g["status"] != "aktiv" or not g["plan"]:
            continue
        plan = g["plan"]
        steps = plan["steps"]
        moved = False
        while plan["current"] < len(steps) and step_done(w, a, g, steps[plan["current"]]):
            steps[plan["current"]]["done"] = True
            plan["current"] += 1
            g["progress_t"] = w.tick
            g["attempts"] = 0
            moved = True
        if moved and plan["current"] >= plan["visible"] and plan["visible"] < len(steps):
            plan["visible"] = min(len(steps), plan["current"] + plan["horizon"])
            plan["revisions"] += 1


def current_step(g: dict) -> dict | None:
    p = g.get("plan")
    if not p or p["current"] >= len(p["steps"]):
        return None
    return p["steps"][p["current"]]


def replan(w: World, a: dict, g: dict, reason: str) -> None:
    old = [s["text"] for s in g["plan"]["steps"]] if g.get("plan") else []
    g["plan"] = make_plan(w, a, g)
    g["replans"] += 1
    g["attempts"] = 0
    g.setdefault("plan_log", []).append([w.tick, reason])
    w.emit("sozial", "planaenderung", f"{a['name']} ändert den Plan für „{g['text']}“: {reason}", actors=[a["id"]], x=a["x"], y=a["y"],
           public=False, witnesses=False, data={"goal": g["id"], "old": old[:4]})


def apply_goal_bonus(w: World, a: dict, options: list[dict]) -> None:
    """Options that advance the current step of an active goal become more attractive (weighted by priority).
    The emotional state and learned lessons tilt the options as well."""
    lessons = a.get("lessons", {})
    emo = a.get("emo", {})
    targets = a.get("emo_targets", {})
    for o in options:
        o["u"] += lessons.get(o["type"], 0.0)
        tg = o.get("target")
        if tg and tg in targets:
            t = targets[tg]
            if o["type"] in ("help", "trade", "lend", "partner"):
                o["u"] += 0.5 * t.get("dankbarkeit", 0) - 0.8 * t.get("aerger", 0)
            if o["type"] in ("confront", "spread_rumor"):
                o["u"] += 0.8 * t.get("aerger", 0)
        if o["type"] in ("rest", "talk") and emo.get("trauer", 0) > 0.3:
            o["u"] += 0.3 * emo["trauer"]
        if o["type"] in ("forage", "fish", "farm") and emo.get("angst", 0) > 0.3:
            o["u"] += 0.3 * emo["angst"]
        if o["type"] in ("talk", "art") and emo.get("freude", 0) > 0.3:
            o["u"] += 0.15 * emo["freude"]
    matched_any = False
    for g in a["agenda"]:
        if g["status"] != "aktiv":
            continue
        s = current_step(g)
        if not s:
            continue
        matched = False
        for o in options:
            if o["type"] not in s["acts"]:
                continue
            if s.get("target") and o.get("target") != s["target"]:
                continue
            want = s.get("data") or {}
            if "btype" in want and o["data"].get("btype") not in (None, want["btype"]):
                continue
            if "tech" in want and o["data"].get("tech") not in (None, want["tech"]):
                continue
            o["u"] += 0.45 + 0.7 * g["prio"]
            o.setdefault("goal", g["id"])
            o["label"] = o["label"] if "→" in o["label"] else f"{o['label']} → {g['text']}"
            matched = True
        if not matched:
            g["attempts"] += 1
            if g["attempts"] in (12, 30) and g["replans"] < 4:
                replan(w, a, g, "Der nächste Schritt ist gerade nicht möglich – neuer Anlauf.")
        matched_any = matched_any or matched


# ------------------------------------------------------------------ event hooks
def notify(w: World, a: dict, kind: str, **kw) -> None:
    """React to something that happened to this agent: emotions, opinions, beliefs, lessons, goals."""
    if not a.get("alive"):
        return
    other = kw.get("other")
    if kind == "bestohlen":
        feel(w, a, "aerger", 0.4, target=other)
        feel(w, a, "angst", 0.15)
        believe(w, a, "vorrat_diebstahl")
        if other:
            judge_person(w, a, other, False, 2.0, "hat mich bestohlen")
        a["replan"] = "wurde bestohlen"
    elif kind == "betrogen":
        feel(w, a, "aerger", 0.35, target=other)
        if other:
            judge_person(w, a, other, False, 2.0, "hat mich beim Tausch betrogen")
        learn_lesson(w, a, "trade", -0.05, "Beim Tauschen muss ich vorsichtig sein.")
    elif kind == "geholfen":
        feel(w, a, "dankbarkeit", 0.4, target=other)
        feel(w, a, "freude", 0.1)
        if other:
            judge_person(w, a, other, True, 1.0, "hat mir geholfen")
    elif kind == "tausch_ok":
        believe(w, a, "handel_lohnt", 0.3)
        if other:
            judge_person(w, a, other, True, 0.3)
        a["lessons"]["trade"] = round(min(0.3, a["lessons"].get("trade", 0) + 0.005), 3)
    elif kind == "zuhause_verloren":
        feel(w, a, "trauer", 0.3)
        feel(w, a, "angst", 0.3)
        a["replan"] = "Zuhause verloren"
    elif kind == "hochwasser":
        feel(w, a, "angst", 0.3)
        believe(w, a, "fluss_hochwasser")
    elif kind == "trauerfall":
        feel(w, a, "trauer", 0.5 * kw.get("closeness", 1.0))
        a["replan"] = "Tod eines nahestehenden Menschen"
    elif kind == "erkrankt":
        feel(w, a, "angst", 0.25)
        attribute_illness(w, a, kw.get("factors", {}))
        a["replan"] = "erkrankt"
    elif kind == "gewaehlt":
        feel(w, a, "stolz", 0.4)
        feel(w, a, "freude", 0.3)
    elif kind == "vorschlag_ergebnis":
        if kw.get("adopted"):
            learn_lesson(w, a, "propose", 0.08, "Mein Vorschlag wurde angenommen – es lohnt sich, sich einzubringen.")
            feel(w, a, "stolz", 0.2)
        else:
            a["lessons"]["propose"] = round(a["lessons"].get("propose", 0) - 0.03, 3)
    elif kind == "verurteilt":
        feel(w, a, "scham", 0.4)
        if kw.get("innocent"):
            feel(w, a, "aerger", 0.6, target=kw.get("accuser"))
            a["morals"]["autoritaet"] = round(clamp(a["morals"]["autoritaet"] - 0.1), 3)
        else:
            learn_lesson(w, a, kw.get("offense_action", "steal"), -0.35, "Ich wurde verurteilt – das war es nicht wert.")
        a["replan"] = "verurteilt"
    elif kind == "freigesprochen":
        feel(w, a, "freude", 0.3)
    elif kind == "eigene_tat":
        if not kw.get("caught"):
            a["lessons"][kw.get("action", "steal")] = round(a["lessons"].get(kw.get("action", "steal"), 0) + 0.04, 3)
            believe(w, a, "verbrechen_lohnt", 0.5)
        feel(w, a, "scham", 0.35 * a["morals"]["ehrlichkeit"])
    elif kind == "versprechen_gebrochen":
        feel(w, a, "aerger", 0.3, target=other)
        if other:
            judge_person(w, a, other, False, 1.5, "hat ein Versprechen gebrochen")
    elif kind == "versprechen_gehalten":
        if other:
            judge_person(w, a, other, True, 1.2, "hat Wort gehalten")
        feel(w, a, "dankbarkeit", 0.2, target=other)
    elif kind == "geburt":
        feel(w, a, "freude", 0.6)
    elif kind == "entdeckung":
        feel(w, a, "stolz", 0.4)
        learn_lesson(w, a, "research", 0.05, "Forschen hat sich gelohnt.")
    elif kind == "ernte":
        believe(w, a, "ackerbau_lohnt", 0.2)
    elif kind == "kaelte":
        believe(w, a, "holz_winter", 0.5)
        feel(w, a, "angst", 0.1)
    elif kind == "gerichtsentscheid_fehlerhaft":
        feel(w, a, "aerger", 0.4)
        a["morals"]["autoritaet"] = round(clamp(a["morals"]["autoritaet"] - 0.05), 3)


def hourly(w: World, a: dict) -> None:
    decay_emotions(w, a)
    if a.get("replan"):
        reason = a["replan"]
        a["replan"] = None
        manage_goals(w, a, reason=f"Reaktion: {reason}")
    advance_plans(w, a)


def daily(w: World, a: dict) -> None:
    manage_goals(w, a, reason="Tagesrückblick")
    # resume a construction site that was put on hold earlier
    building_goal = any(g["status"] == "aktiv" and g["type"] in ("zuhause", "hof", "werkstatt", "laden", "besseres_zuhause", "auswandern")
                        for g in a["agenda"])
    if not a.get("building_plan") and a.get("paused_sites") and not building_goal:
        while a["paused_sites"]:
            sid = a["paused_sites"].pop(0)
            if sid in w.sites and w.sites[sid]["owner"] == a["id"]:
                a["building_plan"] = sid
                w.remember(a, "entscheidung", f"Ich nehme die zurückgestellte Baustelle ({R.BUILDINGS[w.sites[sid]['type']]['label']}) wieder auf.", 3)
                break
    # lessons slowly fade (people forget how bad something felt)
    for k in list(a["lessons"]):
        a["lessons"][k] = round(a["lessons"][k] * 0.995, 4)
    if w.day % 7 == 0:
        a["dev_log"] = (a["dev_log"] + [{"t": w.tick, "personality": dict(a["personality"]), "morals": dict(a["morals"]),
                                         "skills": {k: v for k, v in a["skills"].items() if v > 0.15}, "mood": mood(a)}])[-40:]
