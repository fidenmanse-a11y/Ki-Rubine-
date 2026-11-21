"""Society: conversations & information, proposals & voting, governments & institutions, laws,
justice (claims vs. evidence vs. verdicts), deviance, families, inheritance, culture.

The engine provides *mechanisms* (how a vote is counted under a given rule, what a law
does when it is in force). Which proposals are made, how people vote, which institutions
exist and whether rules are followed is decided by the residents.
"""
from __future__ import annotations

from . import rules as R
from .economy import food_days, gini, give, introduce_currency, stock, wealth
from .state import World, clamp, dist

GOV = "regierung"


# ------------------------------------------------------------------ lookups
def government_of(w: World, region: int) -> dict | None:
    for inst in w.institutions.values():
        if inst["type"] == GOV and inst["region"] == region and inst["active"]:
            return inst
    return None


def treasury_of(w: World, region: int) -> dict | None:
    return government_of(w, region)


def institution_of(w: World, region: int, itype: str) -> dict | None:
    for inst in w.institutions.values():
        if inst["type"] == itype and inst["region"] == region and inst["active"]:
            return inst
    return None


def active_law(w: World, region: int, effect: str) -> dict | None:
    for law in w.laws.values():
        if law["status"] == "aktiv" and law["region"] == region and law["effect"]["type"] == effect:
            return law
    return None


def knows_law(w: World, a: dict, law: dict) -> bool:
    return f"law:{law['id']}" in a["facts"]


def school_available(w: World, a: dict) -> bool:
    region = w.home_region(a)
    inst = institution_of(w, region, "schule")
    if not inst or not inst["members"]:
        return False
    return any(b["type"] == "schule" and b["region"] == region and b["condition"] > 0.25 for b in w.buildings.values())


# ------------------------------------------------------------------ conversations & information
SHARE_PRIORITY = {"law": 5, "proposal": 5, "claim": 4, "verdict": 4, "event": 3, "place": 2, "tech": 1}


def share_facts(w: World, speaker: dict, listener: dict, k: int = 2) -> list[str]:
    cands = []
    for key, f in speaker["facts"].items():
        if key in listener["facts"] and listener["facts"][key]["conf"] >= f["conf"] * 0.85:
            continue
        if f["k"] == "private":
            continue
        age_days = (w.tick - f["t"]) / R.TICKS_PER_DAY
        score = SHARE_PRIORITY.get(f["k"], 1) * f["conf"] / (1 + age_days * 0.3) + w.rng.random() * 0.5
        cands.append((score, key, f))
    cands.sort(key=lambda z: z[0], reverse=True)
    shared = []
    for _, key, f in cands[:k]:
        src = "erzählt" if f["src"] in ("beobachtet", "selbst") else "Gerücht"
        conf = f["conf"] * (0.85 if src == "erzählt" else 0.7)
        if conf < 0.2:
            continue
        if w.learn(listener, key, f["k"], f["x"], src, conf, ref=f.get("ref"), frm=speaker["id"]):
            shared.append(f["x"])
    # one resource location
    for res, pts in speaker["known"]["res"].items():
        lst = listener["known"]["res"].setdefault(res, [])
        for p in pts:
            if p not in lst:
                lst.append(p)
                break
    return shared


def compatibility(a: dict, b: dict) -> float:
    keys = ("agreeableness", "openness", "extraversion", "conscientiousness")
    pd = sum(abs(a["personality"][k] - b["personality"][k]) for k in keys) / len(keys)
    vd = sum(abs(a["values"][k] - b["values"][k]) for k in a["values"]) / len(a["values"])
    return clamp(1 - 0.6 * pd - 0.8 * vd)


def converse(w: World, a: dict, b: dict) -> int:
    shared_ab = share_facts(w, a, b)
    shared_ba = share_facts(w, b, a)
    comp = compatibility(a, b)
    for x, y in ((a, b), (b, a)):
        val = (comp - 0.5) * 0.12 + (x["personality"]["agreeableness"] - 0.5) * 0.05 + w.rng.gauss(0, 0.02)
        w.adjust_rel(x["id"], y["id"], affection=val, trust=val * 0.6, familiarity=0.06, note="Gespräch")
        x["needs"]["social"] = clamp(x["needs"]["social"] - 0.35)
        x["needs"]["stress"] = clamp(x["needs"]["stress"] - 0.03)
    topics = (shared_ab + shared_ba)[:2]
    topic_txt = ("; ".join(t[:80] for t in topics)) if topics else "den Alltag"
    eid = w.emit("sozial", "gespraech", f"{a['name']} und {b['name']} unterhalten sich (Thema: {topic_txt}).",
                 actors=[a["id"], b["id"]], x=a["x"], y=a["y"], data={"shared": len(topics)})
    for x, y in ((a, b), (b, a)):
        w.remember(x, "gespraech", f"Gespräch mit {y['name']}: {topic_txt}", 3 + 2 * (len(topics) > 0), event=eid,
                   subjects=[y["id"]])
    if w.mind is not None and w.mind.available() and w.mind.q.qsize() < 3:
        w.mind.request_dialog(w, a, b, topic_txt, eid)
    return eid


def read_notices(w: World, a: dict) -> int:
    """Notice boards at a hall or market: learn laws, open proposals and verdicts of this region."""
    region = w.region_of(a["x"], a["y"])
    n = 0
    for law in w.laws.values():
        if law["region"] == region and law["status"] == "aktiv":
            n += w.learn(a, f"law:{law['id']}", "law", f"Gesetz: {law['title']}", "Aushang", 1.0, ref=law["id"])
    for p in w.proposals.values():
        if p["region"] == region and p["status"] == "offen":
            n += w.learn(a, f"prop:{p['id']}", "proposal", f"Abstimmung: {p['title']}", "Aushang", 1.0, ref=p["id"])
    for c in w.cases.values():
        if c.get("region") == region and c["status"] in ("schuldig", "freigesprochen"):
            n += w.learn(a, f"case:{c['id']}", "verdict", c["summary"], "Aushang", 1.0, ref=c["id"])
    return n


# ------------------------------------------------------------------ issues → proposal ideas
def recent_tags(w: World, a: dict, days: int = 14) -> dict[str, int]:
    since = w.tick - days * R.TICKS_PER_DAY
    out: dict[str, int] = {}
    for m in a["ltm"] + a["stm"]:
        if m["t"] >= since:
            for t in m.get("tags", []):
                out[t] = out.get(t, 0) + 1
    return out


def civic_drive(a: dict) -> float:
    p, v = a["personality"], a["values"]
    return clamp(0.25 + 0.3 * v["community"] + 0.25 * p["ambition"] + 0.2 * a["skills"]["leadership"]
                 + 0.15 * p["extraversion"] - 0.2 * p["conflict_avoidance"])


def proposal_ideas(w: World, a: dict) -> list[dict]:
    """What this resident might want to change, derived from their own experiences and knowledge."""
    if w.age(a) < R.ADULT_AGE:
        return []
    region = w.home_region(a)
    gov = government_of(w, region)
    tags = recent_tags(w, a)
    p, v = a["personality"], a["values"]
    ideas: list[dict] = []
    open_titles = {x["key"] for x in w.proposals.values() if x["status"] == "offen" and x["region"] == region}

    def add(key: str, kind: str, effect: dict, title: str, weight: float, reason: str) -> None:
        if key not in open_titles:
            ideas.append({"key": key, "kind": kind, "effect": effect, "title": title, "weight": weight, "reason": reason})

    adults_here = len(w.adults(region))
    if gov is None and adults_here >= 5 and (tags.get("diebstahl", 0) + tags.get("streit", 0) + tags.get("hunger", 0) > 0
                                             or w.day > 10):
        if p["ambition"] > 0.65 and a["skills"]["leadership"] > 0.2:
            form = "oberhaupt_erblich" if v["tradition"] > 0.7 else "oberhaupt_wahl"
        elif v["community"] + v["fairness"] > 1.1:
            form = "versammlung"
        else:
            form = "rat"
        add(f"gov:{form}", "regierung", {"type": "regierung", "params": {"form": form, "leader": a["id"]}},
            R.GOVERNMENT_FORMS[form], 0.5 + 0.1 * (tags.get("diebstahl", 0) + tags.get("streit", 0)),
            "Es gibt keine gemeinsamen Regeln und keine Instanz, die Streit klärt.")
    if tags.get("diebstahl", 0) + tags.get("betrug", 0) > 0 and not active_law(w, region, "eigentumsschutz"):
        sank = "verbannung" if (p["agreeableness"] < 0.35 and v["security"] > 0.6) else \
            ("doppelte_rueckgabe" if v["security"] > 0.55 else "rueckgabe")
        add("law:eigentumsschutz", "gesetz", {"type": "eigentumsschutz", "params": {"sanktion": sank}},
            "Eigentum schützen", 0.6 + 0.2 * tags.get("diebstahl", 0), "Es wurde gestohlen.")
    if tags.get("gewalt", 0) and not active_law(w, region, "gewaltverbot"):
        add("law:gewaltverbot", "gesetz", {"type": "gewaltverbot", "params": {"sanktion": "arrest" if v["security"] > 0.5 else "busse"}},
            "Gewalt verbieten", 0.8, "Es gab Gewalt.")
    if gov and (tags.get("hunger", 0) >= 2 or tags.get("not", 0)) and not active_law(w, region, "grundversorgung") \
            and v["community"] + v["fairness"] > 1.0:
        add("law:grundversorgung", "gesetz", {"type": "grundversorgung", "params": {}},
            "Grundversorgung für Hungernde", 0.5, "Menschen hungern, obwohl andere Vorräte haben.")
    if gov and not active_law(w, region, "steuer") and (active_law(w, region, "grundversorgung") or
                                                         active_law(w, region, "gesundheitsversorgung")) \
            and sum((gov.get("inv") or {}).values()) < 5:
        rate = 0.05 if v["wealth"] > 0.6 else 0.1
        add("law:steuer", "gesetz", {"type": "steuer", "params": {"satz": rate}}, f"Abgabe von {int(rate * 100)} % auf Handel",
            0.45, "Die Gemeinschaftskasse ist leer.")
    if gov and not institution_of(w, region, "gericht") and (tags.get("diebstahl", 0) + tags.get("streit", 0)
                                                              + tags.get("betrug", 0) + tags.get("vertragsbruch", 0)) >= 1:
        add("inst:gericht", "institution", {"type": "institution", "params": {"itype": "gericht"}}, "Ein Gericht einrichten",
            0.55, "Streitfälle bleiben ungeklärt.")
    if gov and not institution_of(w, region, "wache") and tags.get("diebstahl", 0) >= 2:
        add("inst:wache", "institution", {"type": "institution", "params": {"itype": "wache"}}, "Eine Wache aufstellen",
            0.45, "Diebstähle häufen sich.")
    if gov and "rechnen" in a["techs"] and not any(c["region"] == region for c in w.currencies.values()) and a["stats"].get("trades", 0) >= 3:
        add("cur", "waehrung", {"type": "waehrung", "params": {"per_adult": 20}}, "Eine gemeinsame Währung einführen",
            0.4 + 0.3 * p["openness"], "Tauschhandel ist umständlich.")
    if gov and "schrift" in a["techs"] and not institution_of(w, region, "schule") and \
            any(w.age(c) < R.ADULT_AGE for c in w.living() if w.home_region(c) == region):
        add("inst:schule", "institution", {"type": "institution", "params": {"itype": "schule"}}, "Eine Schule gründen",
            0.4, "Kinder sollen lesen und lernen können.")
    if gov and "kraeuterkunde" in a["techs"] and not institution_of(w, region, "heilwesen") and tags.get("krankheit", 0):
        add("inst:heilwesen", "institution", {"type": "institution", "params": {"itype": "heilwesen"}},
            "Gemeinsame Gesundheitsversorgung", 0.4, "Kranke brauchen Hilfe.")
    if gov and institution_of(w, region, "heilwesen") and not active_law(w, region, "gesundheitsversorgung") and tags.get("krankheit", 0):
        add("law:gesundheit", "gesetz", {"type": "gesundheitsversorgung", "params": {}}, "Behandlung aus der Gemeinschaftskasse",
            0.35, "Behandlung soll nicht vom Vermögen abhängen.")
    if gov and tags.get("hochwasser", 0) and "dammbau" in a["techs"]:
        add("proj:damm", "projekt", {"type": "projekt", "params": {"btype": "damm"}}, "Einen Damm bauen", 0.6,
            "Hochwasser hat Schaden angerichtet.")
    if gov and not any(b["type"] == "versammlungshalle" and b["region"] == region for b in w.buildings.values()) and "holzbau" in a["techs"]:
        add("proj:halle", "projekt", {"type": "projekt", "params": {"btype": "versammlungshalle"}}, "Eine Versammlungshalle bauen",
            0.3, "Die Gemeinschaft braucht einen Ort für Beschlüsse.")
    if tags.get("erschoepft", 0) >= 2 and gov:
        res = "forage" if tags.get("erschoepft_forage") else "wood"
        if not active_law(w, region, "ressourcenschutz"):
            add("law:ressource", "gesetz", {"type": "ressourcenschutz", "params": {"ressource": res}},
                f"{R.ITEM_LABEL.get(res, 'Sammelgut') if res != 'forage' else 'Sammelgründe'} schützen", 0.35,
                "Ressourcen gehen zur Neige.")
    if gov and v["community"] + v["tradition"] > 1.2 and not any(t["region"] == region for t in w.traditions.values()) and w.day > 14:
        add("fest", "fest", {"type": "fest", "params": {"season": w.season, "day": (w.day % R.DAYS_PER_SEASON) + 1}},
            f"Ein jährliches Fest im {R.SEASONS[w.season]}", 0.25, "Gemeinsam feiern stärkt die Gemeinschaft.")
    if gov and a.get("satisfaction", 0.6) < 0.32 and p["conflict_avoidance"] < 0.5 and gov.get("legitimacy", 1) < 0.45:
        forms = [f for f in R.GOVERNMENT_FORMS if f != gov["form"]]
        form = "versammlung" if v["freedom"] + v["fairness"] > 1.0 and "versammlung" in forms else forms[0]
        add(f"wechsel:{form}", "regierungswechsel", {"type": "regierung", "params": {"form": form, "leader": a["id"]}},
            f"Neue Ordnung: {R.GOVERNMENT_FORMS[form]}", 0.6, "Die jetzige Regierung hat kaum Rückhalt.")
    for law in w.laws.values():
        if law["status"] == "aktiv" and law["region"] == region and knows_law(w, a, law):
            u = law_utility(w, a, law["effect"])
            if u < -0.45:
                add(f"repeal:{law['id']}", "aufhebung", {"type": "aufhebung", "params": {"law": law["id"]}},
                    f"Gesetz aufheben: {law['title']}", 0.4 - u * 0.3, "Dieses Gesetz schadet mir/uns.")
    for idea in ideas:
        idea["weight"] *= civic_drive(a)
    return ideas


# ------------------------------------------------------------------ evaluating rules
def law_utility(w: World, a: dict, effect: dict) -> float:
    p, v = a["personality"], a["values"]
    t = effect["type"]
    prm = effect.get("params", {})
    rich = _wealth_rank(w, a)  # 0 poorest … 1 richest
    stole = a["stats"].get("thefts", 0) > 0
    tags = recent_tags(w, a, 28)
    if t == "eigentumsschutz":
        u = 0.55 * v["security"] + 0.3 * v["fairness"] + 0.3 * (tags.get("diebstahl", 0) > 0) - (0.6 if stole else 0) - 0.3
        if prm.get("sanktion") == "verbannung":
            u -= 0.35 * p["agreeableness"]
        return u
    if t == "gewaltverbot":
        return 0.6 * v["security"] + 0.3 * p["agreeableness"] - 0.15
    if t == "steuer":
        rate = float(prm.get("satz", 0.1))
        return 0.5 * v["community"] + 0.3 * v["fairness"] - 0.5 * v["freedom"] - 0.8 * rich * v["wealth"] - rate * 2 + 0.2
    if t == "grundversorgung":
        return 0.55 * v["community"] + 0.35 * v["fairness"] - 0.4 * v["wealth"] * rich + 0.5 * a["needs"]["hunger"] - 0.2
    if t == "ressourcenschutz":
        dep = a["stats"].get(f"gathered:{prm.get('ressource')}", 0) / 20
        return 0.4 * v["tradition"] + 0.4 * v["community"] + 0.3 * v["security"] - min(0.6, dep) - 0.35
    if t == "erbrecht":
        fam = 0.4 if a["children"] else 0
        return {"familie": 0.3 + fam, "kinder": 0.2 + fam, "gemeinschaft": v["community"] * 0.6 - 0.2}.get(prm.get("regel"), 0)
    if t == "schulpflicht":
        return 0.4 * (len(a["children"]) > 0) + 0.3 * v["community"] - 0.2 * v["freedom"]
    if t == "gesundheitsversorgung":
        return 0.5 * v["community"] + 0.3 * (tags.get("krankheit", 0) > 0) - 0.3 * rich * v["wealth"]
    return 0.0


def _wealth_rank(w: World, a: dict) -> float:
    vals = sorted(wealth(w, x) for x in w.adults(w.home_region(a)))
    if not vals:
        return 0.5
    mine = wealth(w, a)
    return sum(1 for x in vals if x <= mine) / len(vals)


def vote_utility(w: World, a: dict, prop: dict) -> float:
    p, v = a["personality"], a["values"]
    kind, eff = prop["kind"], prop["effect"]
    if kind in ("gesetz",):
        u = law_utility(w, a, eff)
    elif kind == "aufhebung":
        law = w.laws.get(eff["params"]["law"])
        u = -law_utility(w, a, law["effect"]) if law else 0
    elif kind in ("regierung", "regierungswechsel"):
        form = eff["params"]["form"]
        u = {"versammlung": 0.4 * v["fairness"] + 0.4 * v["freedom"] + 0.3 * v["community"] - 0.4,
             "rat": 0.4 * v["security"] + 0.3 * p["trust"] + 0.2 * v["community"] - 0.3,
             "oberhaupt_wahl": 0.5 * v["security"] + 0.3 * v["tradition"] - 0.4 * v["freedom"] - 0.1,
             "oberhaupt_erblich": 0.7 * v["tradition"] - 0.5 * v["fairness"] - 0.4 * v["freedom"]}[form]
        if kind == "regierungswechsel":
            u += 0.8 * (0.5 - a.get("satisfaction", 0.5)) - 0.3 * v["tradition"]
        if form == "oberhaupt_erblich":
            u += 0.6 * (w.rel(a["id"], prop["proposer"])["trust"] - 0.5)
        u += 0.15  # having any common order is valued
    elif kind == "institution":
        it = eff["params"]["itype"]
        u = {"gericht": 0.5 * v["fairness"] + 0.3 * v["security"] - 0.2, "wache": 0.6 * v["security"] - 0.3 * v["freedom"] - 0.05,
             "schule": 0.4 * v["community"] + 0.4 * (len(a["children"]) > 0) + 0.2 * p["curiosity"] - 0.2,
             "heilwesen": 0.5 * v["community"] + 0.3 * (recent_tags(w, a).get("krankheit", 0) > 0) - 0.15}[it]
    elif kind == "waehrung":
        u = 0.4 * p["openness"] + 0.3 * v["wealth"] - 0.3 * v["tradition"] + 0.05
    elif kind == "projekt":
        u = 0.5 * v["community"] + 0.2 * v["security"] - 0.15
    elif kind == "fest":
        u = 0.4 * v["community"] + 0.3 * v["tradition"] + 0.2 * p["extraversion"] - 0.35
    else:
        u = 0.0
    u += 0.35 * (w.rel(a["id"], prop["proposer"])["trust"] - 0.5) if prop["proposer"] != a["id"] else 0.5
    u += w.rng.gauss(0, 0.12)
    return u


# ------------------------------------------------------------------ proposals
def eligible_voters(w: World, prop: dict) -> list[dict]:
    gov = w.institutions.get(prop.get("gov") or "")
    adults = w.adults(prop["region"])
    if prop["kind"] == "regierungswechsel" or gov is None or gov["form"] == "versammlung":
        return adults
    if gov["form"] == "rat":
        return [a for a in adults if a["id"] in gov["leaders"]] or adults
    if gov["form"].startswith("oberhaupt"):
        return [a for a in adults if a["id"] in gov["leaders"]] or adults
    return adults


def make_proposal(w: World, a: dict, idea: dict, title: str | None = None, text: str | None = None,
                  decided_by: str = "regeln") -> dict:
    region = w.home_region(a)
    gov = government_of(w, region)
    pid = w.new_id("P")
    hall = next((b for b in w.buildings.values() if b["type"] == "versammlungshalle" and b["region"] == region), None)
    prop = {"id": pid, "key": idea["key"], "kind": idea["kind"], "effect": idea["effect"], "title": title or idea["title"],
            "text": text or idea["reason"], "proposer": a["id"], "region": region, "gov": gov["id"] if gov else None,
            "rule": _rule_name(gov, idea["kind"]), "created": w.tick, "closes": w.tick + R.VOTE_DURATION_TICKS,
            "votes": {a["id"]: "ja"}, "status": "offen", "result": None, "x": hall["x"] if hall else a["x"],
            "y": hall["y"] if hall else a["y"], "decided_by": decided_by}
    if idea["kind"] == "wahl":
        prop["candidates"] = idea["effect"]["params"]["candidates"]
        prop["votes"] = {}
    w.proposals[pid] = prop
    prop["event"] = w.emit("politik", "vorschlag", f"{a['name']} schlägt vor: „{prop['title']}“ (Abstimmung bis morgen, "
                           f"Regel: {prop['rule']}).", actors=[a["id"]], x=prop["x"], y=prop["y"],
                           data={"proposal": pid, "kind": idea["kind"]})
    for b in w.agents_near(prop["x"], prop["y"], 8):
        w.learn(b, f"prop:{pid}", "proposal", f"Abstimmung: {prop['title']} (vorgeschlagen von {a['name']})",
                "beobachtet" if b["id"] != a["id"] else "selbst", 1.0, ref=pid)
    a["stats"]["proposals"] = a["stats"].get("proposals", 0) + 1
    return prop


def _rule_name(gov: dict | None, kind: str) -> str:
    if kind == "regierungswechsel":
        return "Mehrheit aller Erwachsenen der Region"
    if gov is None:
        return f"Gründungsregel (Ja > Nein und mind. {R.BOOTSTRAP_MIN_YES} bzw. {int(R.BOOTSTRAP_QUORUM * 100)} % Ja)"
    return {"versammlung": "Mehrheit der Abstimmenden (Versammlung)", "rat": "Mehrheit des Rates",
            "oberhaupt_wahl": "Entscheidung des Oberhaupts", "oberhaupt_erblich": "Entscheidung des Oberhaupts"}[gov["form"]]


def cast_vote(w: World, a: dict, prop: dict) -> str:
    if prop["kind"] == "wahl":
        best, bs = None, -1e9
        for cid in prop["candidates"]:
            c = w.agents.get(cid)
            if not c or not c["alive"]:
                continue
            r = w.rel(a["id"], cid)
            s = 0.4 * r["trust"] + 0.35 * r["respect"] + 0.25 * r["affection"] + (0.3 if cid == a["id"] else 0) + w.rng.gauss(0, 0.08)
            if s > bs:
                best, bs = cid, s
        choice = best or "enthaltung"
    else:
        u = vote_utility(w, a, prop)
        choice = "ja" if u > 0.08 else "nein" if u < -0.08 else "enthaltung"
    prop["votes"][a["id"]] = choice
    w.daily["votes"] += 1
    a["stats"]["votes"] = a["stats"].get("votes", 0) + 1
    return choice


def close_proposals(w: World) -> None:
    for prop in list(w.proposals.values()):
        if prop["status"] != "offen" or w.tick < prop["closes"]:
            continue
        voters = {v["id"] for v in eligible_voters(w, prop)}
        votes = {k: v for k, v in prop["votes"].items() if k in voters}
        if prop["kind"] == "wahl":
            _close_election(w, prop, votes)
            continue
        yes = sum(1 for v in votes.values() if v == "ja")
        no = sum(1 for v in votes.values() if v == "nein")
        gov = w.institutions.get(prop.get("gov") or "")
        adults = len(w.adults(prop["region"]))
        if prop["kind"] == "regierungswechsel":
            ok = yes > no and yes >= max(R.BOOTSTRAP_MIN_YES, 0.5 * adults)
        elif gov is None or not gov["active"]:
            ok = yes > no and yes >= max(R.BOOTSTRAP_MIN_YES, R.BOOTSTRAP_QUORUM * adults)
        elif gov["form"] == "versammlung":
            ok = yes > no and (yes + no) >= max(2, 0.25 * adults)
        elif gov["form"] == "rat":
            council = [x for x in gov["leaders"] if x in w.agents and w.agents[x]["alive"]]
            ok = bool(council) and sum(1 for c in council if votes.get(c) == "ja") > len(council) / 2
        else:
            leader = next((x for x in gov["leaders"] if x in w.agents and w.agents[x]["alive"]), None)
            ok = bool(leader) and votes.get(leader) == "ja"
        prop["status"] = "angenommen" if ok else "abgelehnt"
        prop["result"] = {"ja": yes, "nein": no, "enthaltung": len(votes) - yes - no, "berechtigt": len(voters)}
        eid = w.emit("politik", "abstimmung", f"Abstimmung „{prop['title']}“: {prop['status']} "
                     f"({yes} Ja, {no} Nein, {len(votes) - yes - no} Enthaltungen; {prop['rule']}).",
                     x=prop["x"], y=prop["y"], data={"proposal": prop["id"], **prop["result"]}, cause=prop.get("event"))
        prop["result_event"] = eid
        for vid in votes:
            if vid in w.agents:
                ag = w.agents[vid]
                w.learn(ag, f"res:{prop['id']}", "event", f"„{prop['title']}“ wurde {prop['status']}.", "beobachtet", 1.0, ref=eid)
                ag.setdefault("vote_history", []).append(1 if (votes[vid] == "ja") == ok else 0)
                ag["vote_history"] = ag["vote_history"][-10:]
        if ok:
            apply_proposal(w, prop, eid)


def apply_proposal(w: World, prop: dict, cause: int) -> None:
    eff = prop["effect"]
    region = prop["region"]
    proposer = w.agents.get(prop["proposer"])
    if prop["kind"] in ("regierung", "regierungswechsel"):
        old = government_of(w, region)
        if old:
            old["active"] = False
            old["dissolved"] = w.tick
            w.emit("politik", "regierung_aufgeloest", f"Die bisherige Regierung ({R.GOVERNMENT_FORMS[old['form']]}) wurde abgelöst.",
                   data={"inst": old["id"]}, cause=cause, witnesses=False)
        form = eff["params"]["form"]
        iid = w.new_id("I")
        inst = {"id": iid, "type": GOV, "form": form, "name": f"{R.GOVERNMENT_FORMS[form].split(' (')[0]} von {w.region_name(region)}",
                "region": region, "founded": w.tick, "founder": prop["proposer"], "members": [a["id"] for a in w.adults(region)],
                "leaders": [], "active": True, "legitimacy": 0.6, "inv": {}, "term_end": None, "seat": None,
                "history": [], "cause": cause, "protests": 0}
        if old:
            for it, n in list((old.get("inv") or {}).items()):
                w.transfer(("inst", old["id"]), ("inst", iid), it, n)
        w.institutions[iid] = inst
        eid = w.emit("politik", "regierung_gegruendet", f"Neue Regierungsform in {w.region_name(region)}: {R.GOVERNMENT_FORMS[form]}.",
                     data={"inst": iid, "form": form}, cause=cause, witnesses=False)
        _announce(w, region, f"gov:{iid}", f"In {w.region_name(region)} gilt jetzt: {R.GOVERNMENT_FORMS[form]}.", eid)
        if form == "oberhaupt_erblich":
            leader = eff["params"].get("leader") or prop["proposer"]
            inst["leaders"] = [leader]
            inst["history"].append([w.tick, f"Oberhaupt: {w.agents[leader]['name']}"])
        elif form in ("rat", "oberhaupt_wahl"):
            schedule_election(w, inst, cause=eid)
    elif prop["kind"] == "gesetz":
        lid = w.new_id("L")
        law = {"id": lid, "region": region, "inst": prop.get("gov"), "title": prop["title"], "text": prop["text"],
               "effect": eff, "status": "aktiv", "adopted": w.tick, "proposal": prop["id"], "proposer": prop["proposer"]}
        w.laws[lid] = law
        eid = w.emit("politik", "gesetz", f"Gesetz in Kraft: „{law['title']}“ ({R.LAW_EFFECTS[eff['type']]['label']}"
                     + (f", {', '.join(f'{k}: {v}' for k, v in eff.get('params', {}).items())}" if eff.get("params") else "") + ").",
                     data={"law": lid}, cause=cause, witnesses=False)
        law["event"] = eid
        _announce(w, region, f"law:{lid}", f"Gesetz: {law['title']}", eid, voters=prop["votes"])
    elif prop["kind"] == "aufhebung":
        law = w.laws.get(eff["params"]["law"])
        if law and law["status"] == "aktiv":
            law["status"] = "aufgehoben"
            law["repealed"] = w.tick
            w.emit("politik", "gesetz_aufgehoben", f"Gesetz aufgehoben: „{law['title']}“.", data={"law": law["id"]}, cause=cause,
                   witnesses=False)
    elif prop["kind"] == "institution":
        itype = eff["params"]["itype"]
        iid = w.new_id("I")
        inst = {"id": iid, "type": itype, "name": f"{R.PUBLIC_INSTITUTIONS[itype]} {w.region_name(region)}", "region": region,
                "founded": w.tick, "founder": prop["proposer"], "members": [prop["proposer"]], "leaders": [], "active": True,
                "inv": {}, "cause": cause}
        w.institutions[iid] = inst
        eid = w.emit("politik", "institution", f"Neue Institution: {inst['name']} (erstes Mitglied: {proposer['name'] if proposer else '—'}).",
                     data={"inst": iid}, cause=cause, witnesses=False)
        _announce(w, region, f"inst:{iid}", f"Neu: {inst['name']}", eid)
    elif prop["kind"] == "waehrung":
        gov = government_of(w, region)
        if gov:
            name = f"Taler von {w.region_name(region)}"
            cur = introduce_currency(w, gov, name, int(eff["params"].get("per_adult", 20)), cause)
            if w.mind is not None and proposer:
                w.mind.request_naming(w, proposer["id"], "waehrung", cur["id"])
    elif prop["kind"] == "projekt":
        gov = government_of(w, region)
        btype = eff["params"]["btype"]
        if gov and proposer:
            from .construction import choose_plot, start_site
            plot = choose_plot(w, proposer, btype)
            if plot:
                start_site(w, btype, plot[0], plot[1], owner=gov["id"], owner_kind="inst", cause=cause, by=proposer["id"])
    elif prop["kind"] == "fest":
        tid = w.new_id("F")
        w.traditions[tid] = {"id": tid, "name": prop["title"], "region": region, "season": eff["params"]["season"],
                             "day": eff["params"]["day"], "created": w.tick, "held": 0, "status": "beschlossen", "cause": cause}


def _announce(w: World, region: int, key: str, text: str, eid: int, voters: dict | None = None) -> None:
    for a in w.living():
        if (voters and a["id"] in voters) or (w.home_region(a) == region and w.rng.random() < 0.35):
            kind = "law" if key.startswith("law:") else "event"
            w.learn(a, key, kind, text, "beobachtet" if voters and a["id"] in voters else "erzählt", 1.0, ref=eid)


def schedule_election(w: World, inst: dict, cause: int | None = None) -> None:
    seats = 1 if inst["form"].startswith("oberhaupt") else (3 if len(inst["members"]) < 15 else 5)
    adults = w.adults(inst["region"])
    cands = sorted(adults, key=lambda a: a["personality"]["ambition"] + a["skills"]["leadership"] + w.rng.random() * 0.4,
                   reverse=True)
    cands = [c["id"] for c in cands if c["personality"]["ambition"] + c["skills"]["leadership"] > 0.7][:max(seats + 2, 3)]
    if len(cands) < seats:
        cands = [c["id"] for c in sorted(adults, key=lambda a: -a["personality"]["ambition"])[:seats + 1]]
    if not cands:
        return
    initiator = w.agents[cands[0]]
    idea = {"key": f"wahl:{inst['id']}:{w.tick}", "kind": "wahl", "effect": {"type": "wahl",
            "params": {"inst": inst["id"], "seats": seats, "candidates": cands}},
            "title": f"Wahl: {'Oberhaupt' if seats == 1 else f'{seats} Ratsmitglieder'} ({inst['name']})", "reason": "Wahl"}
    prop = make_proposal(w, initiator, idea)
    prop["proposer"] = initiator["id"]
    prop["rule"] = f"Die {seats} Kandidierenden mit den meisten Stimmen"
    for c in cands:
        w.agents[c]["stats"]["candidacies"] = w.agents[c]["stats"].get("candidacies", 0) + 1
    _announce(w, inst["region"], f"prop:{prop['id']}", f"Wahl: {prop['title']}", prop["event"])


def _close_election(w: World, prop: dict, votes: dict) -> None:
    inst = w.institutions.get(prop["effect"]["params"]["inst"])
    seats = prop["effect"]["params"]["seats"]
    tally: dict[str, int] = {}
    for v in votes.values():
        if v in prop["candidates"]:
            tally[v] = tally.get(v, 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    winners = [cid for cid, _ in ranked[:seats]]
    prop["status"] = "abgeschlossen"
    prop["result"] = {"stimmen": tally, "gewaehlt": winners}
    names = ", ".join(f"{w.agents[c]['name']} ({n})" for c, n in ranked)
    eid = w.emit("politik", "wahl", f"Wahlergebnis ({prop['title']}): {names or 'keine Stimmen'}. Gewählt: "
                 f"{', '.join(w.agents[c]['name'] for c in winners) or 'niemand'}.", x=prop["x"], y=prop["y"],
                 data={"proposal": prop["id"], "winners": winners, "tally": tally}, cause=prop.get("event"))
    if inst and inst["active"] and winners:
        inst["leaders"] = winners
        years = R.COUNCIL_TERM_YEARS if inst["form"] == "rat" else R.LEADER_TERM_YEARS
        inst["term_end"] = w.tick + years * R.TICKS_PER_YEAR
        inst["history"].append([w.tick, f"Gewählt: {', '.join(w.agents[c]['name'] for c in winners)}"])
        for c in winners:
            w.agents[c]["bio"].append([w.tick, f"In {inst['name']} gewählt."])
            w.remember(w.agents[c], "biografie", f"Ich wurde in {inst['name']} gewählt.", 8, event=eid, tags=["amt"])
            w.agents[c]["skills"]["leadership"] = round(min(1.0, w.agents[c]["skills"]["leadership"] + 0.05), 3)
    _announce(w, prop["region"], f"res:{prop['id']}", f"Gewählt: {', '.join(w.agents[c]['name'] for c in winners)}", eid)


def daily_politics(w: World) -> None:
    for inst in list(w.institutions.values()):
        if not inst["active"] or inst["type"] != GOV:
            continue
        region = inst["region"]
        members = w.adults(region)
        inst["members"] = [m["id"] for m in members]
        # succession / terms
        leaders_alive = [x for x in inst["leaders"] if x in w.agents and w.agents[x]["alive"]]
        if inst["form"] == "oberhaupt_erblich" and inst["leaders"] and not leaders_alive:
            old = w.agents.get(inst["leaders"][0])
            heirs = [w.agents[c] for c in (old["children"] if old else []) if c in w.agents and w.agents[c]["alive"]
                     and w.age(w.agents[c]) >= R.ADULT_AGE]
            if heirs:
                heir = max(heirs, key=lambda h: w.age(h))
                inst["leaders"] = [heir["id"]]
                inst["history"].append([w.tick, f"Erbfolge: {heir['name']}"])
                w.emit("politik", "erbfolge", f"{heir['name']} folgt als Oberhaupt nach.", actors=[heir["id"]], data={"inst": inst["id"]},
                       witnesses=False)
            elif not inst.get("vacant"):
                inst["vacant"] = True
                w.emit("politik", "vakanz", f"{inst['name']} hat kein Oberhaupt mehr (keine erwachsenen Erben).",
                       data={"inst": inst["id"]}, witnesses=False)
        elif inst["form"] in ("rat", "oberhaupt_wahl"):
            due = inst.get("term_end") is not None and w.tick >= inst["term_end"]
            if (due or (inst["leaders"] and not leaders_alive)) and not any(
                    p["kind"] == "wahl" and p["status"] == "offen" and p["effect"]["params"]["inst"] == inst["id"]
                    for p in w.proposals.values()):
                inst["term_end"] = None
                schedule_election(w, inst)
        # legitimacy = smoothed approval of members
        if members:
            appr = []
            for m in members:
                trust_leaders = [w.rel(m["id"], l)["trust"] for l in leaders_alive if l != m["id"]]
                tl = sum(trust_leaders) / len(trust_leaders) if trust_leaders else 0.5
                vh = m.get("vote_history") or [0.5]
                appr.append(0.45 * m.get("satisfaction", 0.5) + 0.35 * tl + 0.2 * sum(vh) / len(vh))
            inst["legitimacy"] = round(0.8 * inst["legitimacy"] + 0.2 * (sum(appr) / len(appr)), 3)
        # basic provision law
        law = active_law(w, region, "grundversorgung")
        if law:
            for m in w.living():
                if w.home_region(m) == region and m["needs"]["hunger"] > 0.6 and food_days(w, m) < 1 and w.qty(("inst", inst["id"]), "food") > 0:
                    w.transfer(("inst", inst["id"]), ("agent", m["id"]), "food", 1)
                    w.daily["provision"] += 1


def satisfaction(w: World, a: dict) -> float:
    n = a["needs"]
    shelter = 1.0 if a.get("home") else 0.4
    fairness_pen = gini([wealth(w, x) for x in w.adults(w.home_region(a))]) * a["values"]["fairness"]
    s = (0.25 * (1 - n["hunger"]) + 0.15 * (1 - n["thirst"]) + 0.15 * a["health"] + 0.15 * shelter
         + 0.15 * (1 - n["stress"]) + 0.15 * (1 - n["social"]) - 0.2 * fairness_pen)
    return round(clamp(s), 3)


# ------------------------------------------------------------------ deviance & justice
def steal(w: World, thief: dict, victim: dict | None, building: dict | None, item: str, n: int) -> int:
    src = ("agent", victim["id"]) if victim else ("building", building["id"])
    owner_id = victim["id"] if victim else building.get("owner")
    n = min(n, w.qty(src, item))
    if n <= 0:
        return 0
    w.transfer(src, ("agent", thief["id"]), item, n)
    x, y = thief["x"], thief["y"]
    owner_name = w.agents[owner_id]["name"] if owner_id in w.agents else (w.institutions.get(owner_id or "", {}).get("name") or "Gemeinschaft")
    eid = w.emit("justiz", "diebstahl", f"{thief['name']} hat {n} {R.ITEM_LABEL.get(item, item)} von {owner_name} genommen.",
                 actors=[thief["id"]] + ([owner_id] if owner_id in w.agents else []), x=x, y=y, public=False, witnesses=False,
                 data={"offender": thief["id"], "victim": owner_id, "item": item, "n": n, "from_building": building["id"] if building else None})
    thief["stats"]["thefts"] = thief["stats"].get("thefts", 0) + 1
    w.totals["thefts"] += 1
    w.daily["thefts"] += 1
    # guilt / rationalisation
    w.remember(thief, "tat", f"Ich habe {n} {R.ITEM_LABEL.get(item, item)} von {owner_name} genommen.", 7, event=eid,
               subjects=[owner_id] if owner_id else [], tags=["diebstahl_selbst"])
    thief["stressors"] = min(1.0, thief.get("stressors", 0) + 0.15 * thief["personality"]["agreeableness"])
    # witnesses who are awake nearby actually saw it
    for wt in w.agents_near(x, y, 3):
        if wt["id"] == thief["id"] or wt.get("asleep") or w.age(wt) < 6:
            continue
        w.learn(wt, f"ev:{eid}", "claim", f"{thief['name']} hat {owner_name} {R.ITEM_LABEL.get(item, item)} weggenommen.",
                "beobachtet", 1.0, ref=eid)
        w.remember(wt, "beobachtung", f"Ich habe gesehen, wie {thief['name']} etwas von {owner_name} nahm.", 6, event=eid,
                   subjects=[thief["id"]], tags=["diebstahl"])
        w.adjust_rel(wt["id"], thief["id"], trust=-0.1, respect=-0.06, note="Diebstahl beobachtet", event=eid)
        if owner_id == wt["id"]:
            discover_offense(w, wt, "diebstahl", thief, eid, item, n, observed=True)
    if victim and owner_id != thief["id"] and not any(wt["id"] == victim["id"] for wt in w.agents_near(x, y, 3) if not wt.get("asleep")):
        victim.setdefault("pending_discoveries", []).append({"type": "diebstahl", "event": eid, "offender": thief["id"],
                                                             "due": w.tick + w.rng.randint(1, 12), "item": item, "n": n})
    elif building and owner_id in w.agents:
        w.agents[owner_id].setdefault("pending_discoveries", []).append(
            {"type": "diebstahl", "event": eid, "offender": thief["id"], "due": w.tick + w.rng.randint(4, 40), "item": item, "n": n})
    return eid


def check_discoveries(w: World, a: dict) -> None:
    pend = a.get("pending_discoveries") or []
    keep = []
    for d in pend:
        if d["due"] > w.tick:
            keep.append(d)
            continue
        off = w.agents.get(d["offender"])
        # did someone tell us who it was?
        known_culprit = f"ev:{d['event']}" in a["facts"]
        discover_offense(w, a, d["type"], off if known_culprit else None, d["event"], d.get("item"), d.get("n", 1),
                         observed=False)
    a["pending_discoveries"] = keep


def discover_offense(w: World, victim: dict, otype: str, offender: dict | None, event: int, item: str | None, n: int,
                     observed: bool) -> None:
    w.remember(victim, "verlust", f"Mir fehlen {n} {R.ITEM_LABEL.get(item or '', item or 'Sachen')}"
               + (f" – {offender['name']} war es." if offender else " – ich weiß nicht, wer es war."), 7, event=event,
               tags=["diebstahl" if otype == "diebstahl" else "betrug"])
    victim["stressors"] = min(1.0, victim.get("stressors", 0) + 0.12)
    suspect, evidence = offender, [victim["id"]] if (offender and observed) else []
    if offender is None:
        # no knowledge of the culprit: a distrustful person may blame someone they distrust (possibly innocent)
        if victim["personality"]["trust"] < 0.4:
            cands = [x for x in w.agents_near(victim["x"], victim["y"], 10) if x["id"] != victim["id"] and w.age(x) >= 12]
            if cands:
                suspect = min(cands, key=lambda x: w.rel(victim["id"], x["id"])["trust"] + w.rng.random() * 0.2)
                evidence = []
    if not suspect:
        return
    w.adjust_rel(victim["id"], suspect["id"], trust=-0.12, affection=-0.06, note=f"verdächtigt ({otype})", event=event)
    region = w.home_region(victim)
    has_institution = institution_of(w, region, "gericht") or institution_of(w, region, "wache") or government_of(w, region)
    if has_institution and victim["personality"]["conflict_avoidance"] < 0.75:
        open_case(w, otype, accuser=victim, accused=suspect, event=event if offender else None, evidence=evidence,
                  claimed_event=event)
    elif victim["personality"]["conflict_avoidance"] < 0.5:
        confront(w, victim, suspect, event)


def open_case(w: World, ctype: str, *, accuser: dict, accused: dict, event: int | None, evidence: list[str],
              claimed_event: int | None = None) -> dict:
    kid = w.new_id("K")
    region = w.home_region(accuser)
    case = {"id": kid, "type": ctype, "accuser": accuser["id"], "accused": accused["id"], "event": event,
            "claimed_event": claimed_event or event, "evidence": list(dict.fromkeys(evidence)), "status": "behauptung",
            "opened": w.tick, "region": region, "summary": "", "verdict": None}
    w.cases[kid] = case
    case["claim_event"] = w.emit("justiz", "anschuldigung", f"{accuser['name']} beschuldigt {accused['name']} ({ctype}).",
                                 actors=[accuser["id"], accused["id"]], x=accuser["x"], y=accuser["y"],
                                 data={"case": kid, "type": ctype}, cause=None)
    w.learn(accuser, f"case:{kid}", "claim", f"{accuser['name']} beschuldigt {accused['name']} ({ctype})", "selbst", 0.9, ref=kid)
    w.adjust_rel(accused["id"], accuser["id"], trust=-0.1, affection=-0.1, note="beschuldigt worden")
    w.totals["cases"] += 1
    return case


def confront(w: World, a: dict, b: dict, event: int | None) -> int:
    eid = w.emit("justiz", "streit", f"{a['name']} stellt {b['name']} zur Rede.", actors=[a["id"], b["id"]], x=a["x"], y=a["y"],
                 cause=event)
    for x, y in ((a, b), (b, a)):
        w.adjust_rel(x["id"], y["id"], affection=-0.1, trust=-0.06, note="Streit", event=eid)
        w.remember(x, "konflikt", f"Streit mit {y['name']}.", 5, event=eid, subjects=[y["id"]], tags=["streit"])
        x["stressors"] = min(1.0, x.get("stressors", 0) + 0.1)
    # escalation arises from low self-control and hostility on either side
    for x, y in ((a, b), (b, a)):
        hostility = 1 - w.rel(x["id"], y["id"])["affection"]
        p = (1 - x["personality"]["self_control"]) * (1 - x["personality"]["conflict_avoidance"]) * hostility * 0.25
        if w.chance(p):
            violence(w, x, y, eid)
            break
    return eid


def violence(w: World, attacker: dict, target: dict, cause: int | None) -> int:
    from .life import kill
    harm = round(w.rng.uniform(0.08, 0.3), 3)
    target["health"] = clamp(target["health"] - harm)
    target["last_injury"] = "Verletzung durch Gewalt"
    attacker["stats"]["violence"] = attacker["stats"].get("violence", 0) + 1
    w.totals["violence"] += 1
    eid = w.emit("justiz", "gewalt", f"Bei einem Streit wurde {target['name']} von {attacker['name']} verletzt.",
                 actors=[attacker["id"], target["id"]], x=target["x"], y=target["y"], cause=cause, data={"harm": harm,
                 "offender": attacker["id"], "victim": target["id"]})
    w.remember(target, "konflikt", f"{attacker['name']} hat mich verletzt.", 9, event=eid, subjects=[attacker["id"]], tags=["gewalt"])
    w.adjust_rel(target["id"], attacker["id"], trust=-0.12, affection=-0.12, note="Gewalt", event=eid)
    for wt in w.agents_near(target["x"], target["y"], 5):
        if wt["id"] not in (attacker["id"], target["id"]):
            w.remember(wt, "beobachtung", f"{attacker['name']} hat {target['name']} verletzt.", 7, event=eid, tags=["gewalt"])
    if target["health"] <= 0:
        kill(w, target, "Gewalttat", cause_event=eid)
    if government_of(w, w.home_region(target)):
        witnesses = [x["id"] for x in w.agents_near(target["x"], target["y"], 4) if x["id"] not in (attacker["id"],)]
        open_case(w, "gewalt", accuser=target if target["alive"] else w.agents[witnesses[0]] if witnesses else attacker,
                  accused=attacker, event=eid, evidence=witnesses)
    return eid


def daily_justice(w: World) -> None:
    for case in w.cases.values():
        if case["status"] not in ("behauptung", "ermittlung"):
            continue
        region = case["region"]
        accused = w.agents.get(case["accused"])
        accuser = w.agents.get(case["accuser"])
        if not accused or not accused["alive"]:
            case["status"] = "eingestellt"
            case["summary"] = "Verfahren eingestellt (beschuldigte Person verstorben)."
            continue
        watch = institution_of(w, region, "wache")
        if watch and watch["members"] and case["status"] == "behauptung":
            case["status"] = "ermittlung"
        # investigators (watch) or the court itself collect testimony from people who actually saw something
        if case.get("claimed_event") and (watch or institution_of(w, region, "gericht")):
            key = f"ev:{case['claimed_event']}"
            seen_offender = _offender_of(w, case["claimed_event"])
            for a in w.living():
                if a["id"] in case["evidence"] or a["id"] in case.setdefault("exculpatory", []) or a["id"] == case["accused"]:
                    continue
                f = a["facts"].get(key)
                if f and f["src"] == "beobachtet":
                    if seen_offender != case["accused"]:
                        case["exculpatory"].append(a["id"])  # they saw someone else do it
                        continue
                    loyal = w.rel(a["id"], case["accused"])["affection"] > 0.8 and a["personality"]["agreeableness"] < 0.5
                    if not loyal:
                        case["evidence"].append(a["id"])
        court = institution_of(w, region, "gericht")
        gov = government_of(w, region)
        judges = [j for j in (court["members"] if court else []) if j in w.agents and w.agents[j]["alive"] and j != case["accused"]]
        if not judges and gov and gov["form"] in ("rat", "oberhaupt_wahl", "oberhaupt_erblich"):
            judges = [j for j in gov["leaders"] if j in w.agents and w.agents[j]["alive"] and j != case["accused"]]
        if not judges:
            if w.tick - case["opened"] > 10 * R.TICKS_PER_DAY:
                case["status"] = "ungeklaert"
                case["summary"] = f"Vorwurf gegen {accused['name']} blieb ungeklärt (keine zuständige Instanz)."
                if accuser and accuser["alive"]:
                    accuser["stressors"] = min(1.0, accuser.get("stressors", 0) + 0.1)
                    w.remember(accuser, "justiz", f"Niemand hat meinen Vorwurf gegen {accused['name']} geprüft.", 5, tags=["unrecht"])
            continue
        if w.tick - case["opened"] < R.TICKS_PER_DAY:
            continue
        judge = w.agents[judges[0]]
        witnesses = [e for e in case["evidence"] if e != case["accuser"]]
        direct = case["accuser"] in case["evidence"]
        bias = w.rel(judge["id"], case["accused"])["affection"] - 0.5
        strength = len(witnesses) + (0.8 if direct else 0) - max(0.0, bias) * 1.5 - 1.5 * len(case.get("exculpatory", []))
        guilty = strength >= 1.0
        case["status"] = "schuldig" if guilty else "freigesprochen"
        case["verdict"] = {"judge": judge["id"], "tick": w.tick, "witnesses": witnesses, "by": "Gericht" if court else "Regierung"}
        sanction_txt = apply_sanction(w, case, accused, accuser) if guilty else "keine"
        case["summary"] = (f"Urteil ({case['verdict']['by']}, {judge['name']}): {accused['name']} "
                           f"{'schuldig' if guilty else 'freigesprochen'} ({case['type']}); Zeugen: {len(witnesses)}; Folge: {sanction_txt}.")
        truth = case["event"] is not None and _offender_of(w, case["claimed_event"]) == case["accused"]
        case["matches_truth"] = (guilty == truth)
        eid = w.emit("justiz", "urteil", case["summary"], actors=[accused["id"], judge["id"]] + ([accuser["id"]] if accuser else []),
                     x=judge["x"], y=judge["y"], cause=case.get("claim_event"), data={"case": case["id"], "guilty": guilty,
                     "verified_offender": _offender_of(w, case["claimed_event"])})
        _announce(w, region, f"case:{case['id']}", case["summary"], eid)
        w.remember(accused, "justiz", case["summary"], 8, event=eid, tags=["urteil"])
        w.totals["verdicts"] += 1


def _offender_of(w: World, event_id: int | None) -> str | None:
    return _event_data(w, event_id).get("offender")


def apply_sanction(w: World, case: dict, accused: dict, accuser: dict | None) -> str:
    region = case["region"]
    law = active_law(w, region, "eigentumsschutz" if case["type"] in ("diebstahl", "betrug") else
                     ("gewaltverbot" if case["type"] == "gewalt" else "_none"))
    sank = (law["effect"]["params"].get("sanktion") if law else None) or "rueckgabe"
    ev = _event_data(w, case["claimed_event"])
    item, n = ev.get("item", "food"), int(ev.get("n", 1) or 1)
    if case["type"] in ("diebstahl", "betrug") and accuser:
        due = n * (2 if sank == "doppelte_rueckgabe" else 1)
        paid = min(due, w.qty(("agent", accused["id"]), item))
        if paid:
            w.transfer(("agent", accused["id"]), ("agent", accuser["id"]), item, paid)
        txt = f"Rückgabe von {paid}/{due} {R.ITEM_LABEL.get(item, item)}"
        if paid < due:
            accused["debts"] = accused.get("debts", 0) + 1
        if sank == "verbannung":
            banish(w, accused, region, 14)
            txt += ", Verbannung für 14 Tage"
        return txt
    if case["type"] == "gewalt":
        if sank == "arrest":
            accused["arrest_until"] = w.tick + 2 * R.TICKS_PER_DAY
            return "Arrest für 2 Tage"
        if sank == "verbannung":
            banish(w, accused, region, 14)
            return "Verbannung für 14 Tage"
        paid = min(3, w.qty(("agent", accused["id"]), "food"))
        if paid and accuser and accuser["alive"]:
            w.transfer(("agent", accused["id"]), ("agent", accuser["id"]), "food", paid)
        return f"Buße von {paid} Nahrung"
    if case["type"] == "vertragsbruch":
        return "Ermahnung; offene Forderung bleibt bestehen"
    if case["type"] == "machtmissbrauch":
        gov = government_of(w, region)
        if gov and accused["id"] in gov["leaders"]:
            gov["leaders"].remove(accused["id"])
            gov["history"].append([w.tick, f"{accused['name']} wegen Machtmissbrauch abgesetzt"])
        return "Amtsenthebung"
    return "keine"


def _event_data(w: World, event_id: int | None) -> dict:
    if event_id is None:
        return {}
    return w.config.get("_eventdata", {}).get(str(event_id), {})


def banish(w: World, a: dict, region: int, days: int) -> None:
    a["banned"][str(region)] = w.tick + days * R.TICKS_PER_DAY
    a["bio"].append([w.tick, f"Für {days} Tage aus {w.region_name(region)} verbannt."])
    w.remember(a, "biografie", f"Ich wurde für {days} Tage aus {w.region_name(region)} verbannt.", 9, tags=["verbannung"])
    a["stressors"] = min(1.0, a.get("stressors", 0) + 0.4)


# ------------------------------------------------------------------ families, death, inheritance
def form_partnership(w: World, a: dict, b: dict) -> int:
    a["partner"], b["partner"] = b["id"], a["id"]
    home = a.get("home") or b.get("home")
    if home:
        for x in (a, b):
            if not x.get("home"):
                x["home"] = home
    eid = w.emit("sozial", "partnerschaft", f"{a['name']} und {b['name']} sind jetzt ein Paar.", actors=[a["id"], b["id"]],
                 x=a["x"], y=a["y"])
    for x, y in ((a, b), (b, a)):
        w.adjust_rel(x["id"], y["id"], affection=0.1, trust=0.08, familiarity=0.1, note="Partnerschaft", event=eid)
        x["bio"].append([w.tick, f"Partnerschaft mit {y['name']}."])
        w.remember(x, "biografie", f"{y['name']} und ich sind jetzt ein Paar.", 9, event=eid, subjects=[y["id"]], tags=["familie"])
    return eid


def on_death(w: World, a: dict, eid: int) -> None:
    w.config.setdefault("_dead_names", {})[a["id"]] = a["name"]
    if a.get("partner") and a["partner"] in w.agents:
        w.agents[a["partner"]]["partner"] = None
    for c in w.contracts.values():
        if c["status"] == "aktiv" and a["id"] in (c.get("worker"), c.get("employer"), c.get("lender"), c.get("borrower")):
            c["status"] = "beendet (Tod)"
            wk = w.agents.get(c.get("worker") or "")
            if wk and wk.get("employer") == c["id"]:
                wk["employer"] = None
    for other in w.living():
        r = w.rel(other["id"], a["id"])
        if r["familiarity"] > 0.15 or r["affection"] > 0.65:
            grief = r["affection"] * (1 if r["familiarity"] > 0.3 else 0.5)
            other["stressors"] = min(1.0, other.get("stressors", 0) + 0.4 * grief)
            w.remember(other, "verlust", f"{a['name']} ist gestorben.", 5 + 4 * grief, event=eid, subjects=[a["id"]], tags=["trauer"])
            w.learn(other, f"ev:{eid}", "event", f"{a['name']} ist gestorben.", "erzählt", 1.0, ref=eid)
    inherit(w, a, eid)


def inherit(w: World, a: dict, eid: int) -> None:
    """Possessions follow the region's inheritance law; without one, the engine default (documented) applies:
    partner, else children (equal shares), else the regional government treasury, else lost."""
    region = w.home_region(a)
    law = active_law(w, region, "erbrecht")
    rule = law["effect"]["params"]["regel"] if law else "standard"
    partner = w.agents.get(a.get("partner") or "")
    kids = [w.agents[c] for c in a["children"] if c in w.agents and w.agents[c]["alive"]]
    gov = government_of(w, region)
    heirs: list[tuple[str, str]] = []
    if rule == "gemeinschaft" and gov:
        heirs = [("inst", gov["id"])]
    elif rule == "kinder" and kids:
        heirs = [("agent", k["id"]) for k in kids]
    elif partner and partner["alive"]:
        heirs = [("agent", partner["id"])]
    elif kids:
        heirs = [("agent", k["id"]) for k in kids]
    elif gov:
        heirs = [("inst", gov["id"])]
    for it, n in list((a.get("inv") or {}).items()):
        if not heirs:
            w.consume(("agent", a["id"]), it, n, "nachlass_verloren")
            continue
        share, rest = divmod(n, len(heirs))
        for i, h in enumerate(heirs):
            q = share + (1 if i < rest else 0)
            if q:
                w.transfer(("agent", a["id"]), h, it, q)
    for b in w.buildings.values():
        if b.get("owner") == a["id"]:
            if heirs:
                b["owner_kind"], b["owner"] = heirs[0][0], heirs[0][1]
            else:
                b["owner"], b["owner_kind"] = None, "herrenlos"
    w.emit("wirtschaft", "erbe", f"Nachlass von {a['name']} verteilt ({'Gesetz: ' + rule if law else 'Standardregel'}; "
           f"Erben: {', '.join(w.agents[h[1]]['name'] if h[0] == 'agent' else w.institutions[h[1]]['name'] for h in heirs) or 'keine'}).",
           actors=[a["id"]], cause=eid, witnesses=False)


# ------------------------------------------------------------------ culture
def festivals_today(w: World) -> None:
    doy = w.day % R.DAYS_PER_YEAR
    for t in w.traditions.values():
        if t["season"] * R.DAYS_PER_SEASON + t["day"] - 1 != doy or t.get("last_day") == w.day:
            continue
        t["last_day"] = w.day
        attendees = [a for a in w.living() if w.home_region(a) == t["region"] and
                     w.rng.random() < 0.3 + 0.5 * a["values"]["community"]]
        if len(attendees) < 3:
            w.emit("wissen", "fest_ausgefallen", f"Das Fest „{t['name']}“ fand kaum Beachtung ({len(attendees)} Personen).",
                   data={"tradition": t["id"]}, witnesses=False)
            continue
        t["held"] += 1
        for a in attendees:
            a["needs"]["social"] = clamp(a["needs"]["social"] - 0.5)
            a["needs"]["stress"] = clamp(a["needs"]["stress"] - 0.1)
            for b in w.rng.sample(attendees, min(3, len(attendees))):
                if b["id"] != a["id"]:
                    w.adjust_rel(a["id"], b["id"], affection=0.04, familiarity=0.03)
        eid = w.emit("wissen", "fest", f"Fest „{t['name']}“ mit {len(attendees)} Teilnehmenden (zum {t['held']}. Mal).",
                     data={"tradition": t["id"], "n": len(attendees)}, witnesses=False)
        if t["held"] == 2:
            t["status"] = "tradition"
            w.emit("wissen", "tradition", f"„{t['name']}“ ist zur Tradition geworden.", cause=eid, witnesses=False)


def donate(w: World, a: dict, gov: dict, item: str, n: int) -> int:
    n = min(n, w.qty(("agent", a["id"]), item))
    if n <= 0:
        return 0
    w.transfer(("agent", a["id"]), ("inst", gov["id"]), item, n)
    w.emit("wirtschaft", "spende", f"{a['name']} spendet {n} {R.ITEM_LABEL.get(item, item)} an {gov['name']}.",
           actors=[a["id"]], x=a["x"], y=a["y"])
    return n


__all__ = ["government_of", "treasury_of", "active_law", "converse", "proposal_ideas", "make_proposal", "cast_vote",
           "close_proposals", "daily_politics", "daily_justice", "steal", "check_discoveries", "open_case", "confront",
           "violence", "form_partnership", "on_death", "satisfaction", "festivals_today", "donate", "read_notices",
           "school_available", "share_facts", "give", "stock", "dist"]
