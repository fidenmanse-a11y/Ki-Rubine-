"""World 3.0 social mechanics: friendships, promises, persuasion, rumours & lies, alliances, feuds.

Deception and harm are abstract actions inside the simulated world (e.g. "spreads a false claim
about X"). No real-world instructions are modelled.
"""
from __future__ import annotations

from . import cognition as C
from . import rules as R
from .state import World, clamp


# ------------------------------------------------------------------ friendships
def update_friendships(w: World) -> None:
    living = {a["id"]: a for a in w.living()}
    for key, r in list(w.relations.items()):
        a_id, b_id = key.split(">", 1)
        if a_id > b_id or a_id not in living or b_id not in living:
            continue
        back = w.relations.get(f"{b_id}>{a_id}")
        if not back:
            continue
        a, b = living[a_id], living[b_id]
        is_friend = b_id in a["friends"]
        strong = min(r["affection"], back["affection"]) > 0.68 and min(r["trust"], back["trust"]) > 0.6 and \
            min(r["familiarity"], back["familiarity"]) > 0.35
        broken = min(r["affection"], back["affection"]) < 0.45 or min(r["trust"], back["trust"]) < 0.4
        if strong and not is_friend:
            a["friends"].append(b_id)
            b["friends"].append(a_id)
            eid = w.emit("sozial", "freundschaft", f"{a['name']} und {b['name']} sind Freunde geworden.", actors=[a_id, b_id],
                         x=a["x"], y=a["y"])
            for x, y in ((a, b), (b, a)):
                x["bio"].append([w.tick, f"Freundschaft mit {y['name']}."])
                w.remember(x, "sozial", f"{y['name']} ist jetzt ein Freund/eine Freundin.", 6, event=eid, subjects=[y["id"]])
                C.feel(w, x, "freude", 0.2)
        elif is_friend and broken:
            a["friends"].remove(b_id)
            b["friends"].remove(a_id)
            w.emit("sozial", "freundschaft_beendet", f"Die Freundschaft zwischen {a['name']} und {b['name']} ist zerbrochen.",
                   actors=[a_id, b_id], x=a["x"], y=a["y"])
            for x, y in ((a, b), (b, a)):
                x["bio"].append([w.tick, f"Freundschaft mit {y['name']} zerbrochen."])
                C.feel(w, x, "trauer", 0.2)


def moral_influence(w: World) -> None:
    """Friends slowly influence each other's moral convictions (social learning)."""
    for a in w.living():
        if not a["friends"]:
            continue
        fr = [w.agents[f] for f in a["friends"] if f in w.agents and w.agents[f]["alive"]]
        if not fr:
            continue
        for m in C.MORALS:
            avg = sum(f["morals"][m] for f in fr) / len(fr)
            a["morals"][m] = round(a["morals"][m] + 0.01 * (avg - a["morals"][m]), 4)


# ------------------------------------------------------------------ promises
def promise(w: World, frm: dict, to: dict, kind: str, target: str, days: int, text: str) -> dict:
    w.counters["V"] += 1
    pid = f"V{w.counters['V']:05d}"
    p = {"id": pid, "from": frm["id"], "to": to["id"], "kind": kind, "target": target, "made": w.tick,
         "due": w.tick + days * R.TICKS_PER_DAY, "status": "offen", "text": text}
    w.promises[pid] = p
    w.emit("sozial", "versprechen", f"{frm['name']} verspricht {to['name']}: {text}.", actors=[frm["id"], to["id"]],
           x=frm["x"], y=frm["y"], data={"promise": pid})
    w.learn(to, f"prom:{pid}", "event", f"{frm['name']} hat versprochen: {text}", "beobachtet", 1.0, ref=pid)
    return p


def promise_fulfilled(w: World, p: dict) -> bool:
    frm = w.agents.get(p["from"])
    if not frm:
        return False
    if p["kind"] == "bauhilfe":
        s = w.sites.get(p["target"])
        if s is None:  # finished – did the promiser take part?
            b = next((b for b in w.buildings.values() if p["from"] in b.get("builders", []) and b.get("built", 0) >= p["made"]), None)
            return b is not None
        return p["from"] in s["workers"] or s.get("donors", {}).get(p["from"], 0) > 0
    if p["kind"] == "stimme":
        prop = w.proposals.get(p["target"])
        return bool(prop) and prop["votes"].get(p["from"]) == "ja"
    return False


def check_promises(w: World) -> None:
    for p in w.promises.values():
        if p["status"] != "offen":
            continue
        frm, to = w.agents.get(p["from"]), w.agents.get(p["to"])
        if not frm or not to or not frm["alive"] or not to["alive"]:
            p["status"] = "hinfällig"
            continue
        if promise_fulfilled(w, p):
            p["status"] = "gehalten"
            w.adjust_rel(to["id"], frm["id"], trust=0.08, note="Versprechen gehalten")
            C.notify(w, to, "versprechen_gehalten", other=frm["id"])
        elif w.tick > p["due"]:
            p["status"] = "gebrochen"
            frm["stats"]["promises_broken"] = frm["stats"].get("promises_broken", 0) + 1
            eid = w.emit("sozial", "versprechen_gebrochen", f"{frm['name']} hat das Versprechen an {to['name']} nicht gehalten ({p['text']}).",
                         actors=[frm["id"], to["id"]], x=to["x"], y=to["y"], public=False, witnesses=False, data={"promise": p["id"]})
            w.adjust_rel(to["id"], frm["id"], trust=-0.12, affection=-0.05, note="Versprechen gebrochen", event=eid)
            C.notify(w, to, "versprechen_gebrochen", other=frm["id"])
            C.feel(w, frm, "scham", 0.15 * frm["morals"]["ehrlichkeit"])


def maybe_ask_for_help(w: World, a: dict, b: dict) -> None:
    """During a conversation: if a has a construction site and b likes a, b may promise to help."""
    site = w.sites.get(a.get("building_plan") or "")
    if not site or any(p["status"] == "offen" and p["from"] == b["id"] and p["target"] == site["id"] for p in w.promises.values()):
        return
    r = w.rel(b["id"], a["id"])
    willing = 0.3 * b["personality"]["agreeableness"] + 0.4 * r["affection"] + 0.2 * b["values"]["community"] - 0.3
    if w.rng.random() < willing:
        promise(w, b, a, "bauhilfe", site["id"], 3, f"beim Bau von {R.BUILDINGS[site['type']]['label']} zu helfen")


def promise_options(w: World, a: dict, opt) -> list[dict]:
    out = []
    for p in w.promises.values():
        if p["status"] != "offen" or p["from"] != a["id"]:
            continue
        if p["kind"] == "bauhilfe" and p["target"] in w.sites:
            s = w.sites[p["target"]]
            weight = 0.4 + 0.6 * a["personality"]["conscientiousness"] * a["morals"]["ehrlichkeit"] + \
                0.4 * (p["due"] - w.tick < R.TICKS_PER_DAY)
            from .construction import missing_materials
            if missing_materials(s) and any((a.get("inv") or {}).get(it, 0) > 0 for it in missing_materials(s)):
                out.append(opt("deliver", f"Versprechen halten: Material zu {w.agents[p['to']]['name']} bringen", weight,
                               dest=(s["x"], s["y"]), target=s["id"], data={"promise": p["id"]}, dur=1))
            elif not missing_materials(s):
                out.append(opt("build", f"Versprechen halten: bei {w.agents[p['to']]['name']} mitbauen", weight,
                               dest=(s["x"], s["y"]), target=s["id"], data={"promise": p["id"]}, dur=4))
    return out


# ------------------------------------------------------------------ persuasion
def persuade(w: World, a: dict, b: dict, prop_id: str) -> bool:
    prop = w.proposals.get(prop_id)
    if not prop or prop["status"] != "offen":
        return False
    r = w.rel(b["id"], a["id"])
    est, unc = C.honesty_estimate(b, a["id"])
    p_success = clamp(0.15 + 0.4 * r["trust"] + 0.2 * a["skills"]["leadership"] + 0.2 * b["personality"]["openness"]
                      + 0.15 * est - 0.2 * unc - 0.25 * C.opinion(b, a["id"])["verdacht"])
    ok = w.rng.random() < p_success
    a["skills"]["leadership"] = round(min(1.0, a["skills"]["leadership"] + 0.004), 4)
    if ok:
        b.setdefault("leanings", {})[prop_id] = round(b.get("leanings", {}).get(prop_id, 0) + 0.35, 3)
        w.learn(b, f"prop:{prop_id}", "proposal", f"Abstimmung: {prop['title']} (von {a['name']} empfohlen)", "erzählt", 0.9, ref=prop_id)
        if w.rng.random() < 0.5 * b["morals"]["loyalitaet"] + 0.2:
            promise(w, b, a, "stimme", prop_id, 2, f"für „{prop['title']}“ zu stimmen")
        text = f"{a['name']} überzeugt {b['name']}, „{prop['title']}“ zu unterstützen."
    else:
        b.setdefault("leanings", {})[prop_id] = round(b.get("leanings", {}).get(prop_id, 0) - 0.1, 3)
        w.adjust_rel(b["id"], a["id"], affection=-0.02)
        text = f"{b['name']} widerspricht {a['name']} und lässt sich nicht von „{prop['title']}“ überzeugen."
    w.emit("politik", "ueberzeugung" if ok else "widerspruch", text, actors=[a["id"], b["id"]], x=a["x"], y=a["y"],
           data={"proposal": prop_id, "p": round(p_success, 2)})
    return ok


# ------------------------------------------------------------------ rumours & lies
def spread_rumor(w: World, liar: dict, listener: dict, about: dict) -> None:
    """A deliberately false claim (abstract). The engine records that it is false (developer truth)."""
    w.counters["Q"] += 1
    rid = f"Q{w.counters['Q']:05d}"
    text = f"{about['name']} soll heimlich Vorräte anderer genommen haben."
    w.rumors[rid] = {"id": rid, "origin": liar["id"], "about": about["id"], "text": text, "false": True, "tick": w.tick, "reach": [listener["id"]]}
    liar["stats"]["lies"] = liar["stats"].get("lies", 0) + 1
    liar["secrets"] = (liar["secrets"] + [{"t": w.tick, "x": f"Ich habe über {about['name']} gelogen."}])[-10:]
    C.feel(w, liar, "scham", 0.2 * liar["morals"]["ehrlichkeit"])
    _hear_rumor(w, listener, liar, rid)
    w.emit("sozial", "geruecht", f"{liar['name']} erzählt {listener['name']} ein Gerücht über {about['name']}.",
           actors=[liar["id"], listener["id"], about["id"]], x=liar["x"], y=liar["y"], public=False, witnesses=False,
           data={"rumor": rid, "false": True, "offender": liar["id"]})


def _hear_rumor(w: World, listener: dict, teller: dict, rid: str) -> None:
    rum = w.rumors[rid]
    about = rum["about"]
    if listener["id"] == about:
        # the subject knows the claim is false -> the teller looks dishonest; the chain unravels toward the origin
        C.judge_person(w, listener, teller["id"], False, 1.5, "hat Lügen über mich verbreitet")
        C.feel(w, listener, "aerger", 0.35, target=teller["id"])
        w.adjust_rel(listener["id"], teller["id"], trust=-0.12, affection=-0.08, note="Gerücht über mich")
        if teller["id"] != rum["origin"] and rum["origin"] in w.agents:
            origin = w.agents[rum["origin"]]
            C.judge_person(w, teller, origin["id"], False, 1.2, "hat mir eine Lüge erzählt")
            w.adjust_rel(teller["id"], origin["id"], trust=-0.1, note="hat mich belogen")
            rum["exposed"] = True
            w.emit("sozial", "luege_aufgedeckt", f"Das Gerücht über {listener['name']} ist als falsch erkannt worden – es stammte von {origin['name']}.",
                   actors=[listener["id"], teller["id"], origin["id"]], x=listener["x"], y=listener["y"], data={"rumor": rid})
        return
    est, unc = C.honesty_estimate(listener, about)
    trust_teller = w.rel(listener["id"], teller["id"])["trust"]
    if est > 0.72 and unc < 0.35:
        # listener knows the person well and does not believe it
        w.adjust_rel(listener["id"], teller["id"], trust=-0.04)
        w.emit("sozial", "widerspruch", f"{listener['name']} glaubt das Gerücht über {w.agents[about]['name']} nicht.",
               actors=[listener["id"], teller["id"]], x=listener["x"], y=listener["y"], data={"rumor": rid})
        return
    conf = round(clamp(0.3 + 0.5 * trust_teller), 2)
    w.learn(listener, f"rumor:{rid}", "claim", rum["text"], "Gerücht", conf, ref=rid, frm=teller["id"])
    C.opinion(listener, about)["verdacht"] = round(clamp(C.opinion(listener, about)["verdacht"] + 0.2 * conf), 3)
    if listener["id"] not in rum["reach"]:
        rum["reach"].append(listener["id"])


def relay_rumors(w: World, speaker: dict, listener: dict) -> None:
    for key, f in list(speaker["facts"].items()):
        if key.startswith("rumor:") and f["conf"] > 0.3 and key not in listener["facts"] and w.rng.random() < 0.4:
            rid = key.split(":", 1)[1]
            if rid in w.rumors:
                _hear_rumor(w, listener, speaker, rid)
                break


# ------------------------------------------------------------------ alliances
def found_alliance(w: World, founder: dict, members: list[dict], purpose: str) -> dict:
    w.counters["U"] += 1
    aid = f"U{w.counters['U']:04d}"
    al = {"id": aid, "name": f"Bündnis um {founder['name']}", "founder": founder["id"], "members": [founder["id"]] + [m["id"] for m in members],
          "purpose": purpose, "created": w.tick, "active": True, "region": w.home_region(founder), "named_by": None}
    w.alliances[aid] = al
    w.emit("politik", "buendnis", f"{founder['name']} gründet ein Bündnis mit {', '.join(m['name'] for m in members)} ({purpose}).",
           actors=al["members"], x=founder["x"], y=founder["y"], data={"alliance": aid})
    for m in [founder] + members:
        m["bio"].append([w.tick, f"Mitglied im {al['name']}."])
    if w.mind is not None:
        w.mind.request_naming(w, founder["id"], "buendnis", aid)
    return al


def alliance_of(w: World, aid: str) -> list[dict]:
    return [al for al in w.alliances.values() if al["active"] and aid in al["members"]]


def alliance_options(w: World, a: dict, opt) -> list[dict]:
    if alliance_of(w, a["id"]) or w.age(a) < R.ADULT_AGE:
        return []
    p = a["personality"]
    if p["extraversion"] + a["skills"]["leadership"] + p["ambition"] < 1.3:
        return []
    friends_near = [w.agents[f] for f in a["friends"] if f in w.agents and w.agents[f]["alive"] and not alliance_of(w, f)]
    if len(friends_near) < 2:
        return []
    return [opt("alliance", f"Mit {', '.join(f['name'] for f in friends_near[:3])} ein Bündnis schmieden",
                0.2 + 0.3 * p["ambition"] + 0.2 * a["morals"]["loyalitaet"], data={"members": [f["id"] for f in friends_near[:4]]}, dur=1)]


def alliance_vote_bias(w: World, a: dict, prop: dict) -> float:
    bias = 0.0
    for al in alliance_of(w, a["id"]):
        stances = [prop["votes"][m] for m in al["members"] if m in prop["votes"] and m != a["id"]]
        if stances:
            yes = sum(1 for s in stances if s == "ja") / len(stances)
            bias += (yes - 0.5) * 0.6 * a["morals"]["loyalitaet"]
        if prop["proposer"] in al["members"]:
            bias += 0.25 * a["morals"]["loyalitaet"]
    return bias


def update_alliances(w: World) -> None:
    for al in w.alliances.values():
        if not al["active"]:
            continue
        al["members"] = [m for m in al["members"] if m in w.agents and w.agents[m]["alive"]]
        pairs = [(x, y) for x in al["members"] for y in al["members"] if x != y]
        cohesion = sum(w.rel(x, y)["affection"] for x, y in pairs) / len(pairs) if pairs else 0
        al["cohesion"] = round(cohesion, 3)
        if len(al["members"]) < 2 or cohesion < 0.45:
            al["active"] = False
            al["ended"] = w.tick
            w.emit("politik", "buendnis_aufgeloest", f"{al['name']} hat sich aufgelöst (Zusammenhalt {cohesion:.0%}).", data={"alliance": al["id"]},
                   witnesses=False)


# ------------------------------------------------------------------ feuds
def feud_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def update_feuds(w: World) -> None:
    living = {a["id"]: a for a in w.living()}
    for a in living.values():
        for tid, t in a["emo_targets"].items():
            if t.get("aerger", 0) < 0.55 or tid not in living:
                continue
            b = living[tid]
            k = feud_key(a["id"], tid)
            mutual = b["emo_targets"].get(a["id"], {}).get("aerger", 0) > 0.3 or w.rel(tid, a["id"])["affection"] < 0.35
            if k not in w.feuds and mutual:
                w.feuds[k] = {"key": k, "a": a["id"], "b": tid, "since": w.tick, "intensity": round(t["aerger"], 3), "active": True,
                              "causes": [h[1] for h in w.rel(a["id"], tid)["hist"][-3:]]}
                w.emit("sozial", "fehde", f"Zwischen {a['name']} und {b['name']} ist eine anhaltende Feindschaft entstanden.",
                       actors=[a["id"], tid], data={"feud": k}, witnesses=False)
    for k, f in w.feuds.items():
        if not f["active"]:
            continue
        a, b = living.get(f["a"]), living.get(f["b"])
        if not a or not b:
            f["active"] = False
            f["ended"] = w.tick
            continue
        anger = max(a["emo_targets"].get(b["id"], {}).get("aerger", 0), b["emo_targets"].get(a["id"], {}).get("aerger", 0))
        f["intensity"] = round(0.8 * f["intensity"] + 0.2 * anger, 3)
        if f["intensity"] < 0.12 and min(w.rel(a["id"], b["id"])["affection"], w.rel(b["id"], a["id"])["affection"]) >= 0.45:
            f["active"] = False
            f["ended"] = w.tick
            w.emit("sozial", "versoehnung", f"{a['name']} und {b['name']} haben ihren Streit beigelegt.", actors=[a["id"], b["id"]],
                   data={"feud": k}, witnesses=False)
            for x in (a, b):
                x["bio"].append([w.tick, f"Versöhnung mit {(b if x is a else a)['name']}."])


def apologize(w: World, a: dict, b: dict) -> None:
    forgive = clamp(0.3 + 0.5 * b["personality"]["agreeableness"] + 0.2 * w.rel(b["id"], a["id"])["familiarity"])
    if w.rng.random() < forgive:
        t = b["emo_targets"].get(a["id"], {})
        if "aerger" in t:
            t["aerger"] = round(t["aerger"] * 0.4, 3)
        a_t = a["emo_targets"].get(b["id"], {})
        if "aerger" in a_t:
            a_t["aerger"] = round(a_t["aerger"] * 0.6, 3)
        w.adjust_rel(b["id"], a["id"], affection=0.08, trust=0.05, note="Entschuldigung angenommen")
        w.adjust_rel(a["id"], b["id"], affection=0.06, note="Versöhnungsversuch")
        w.emit("sozial", "entschuldigung", f"{a['name']} entschuldigt sich bei {b['name']} – die Entschuldigung wird angenommen.",
               actors=[a["id"], b["id"]], x=a["x"], y=a["y"])
    else:
        w.emit("sozial", "entschuldigung", f"{a['name']} entschuldigt sich bei {b['name']}, doch {b['name']} bleibt verärgert.",
               actors=[a["id"], b["id"]], x=a["x"], y=a["y"])


def daily(w: World) -> None:
    update_friendships(w)
    check_promises(w)
    update_alliances(w)
    update_feuds(w)
    moral_influence(w)
