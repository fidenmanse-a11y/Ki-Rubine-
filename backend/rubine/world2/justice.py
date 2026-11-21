"""World 3.0 justice: complaint → investigation → charge → trial → verdict → sentence → (appeal).

Principles enforced by the engine (the residents decide *which* institutions and laws exist):
  * Presumption of innocence: a conviction needs an evidence score at or above the threshold
    (default 1.0; residents can raise it by law "beweisregel").
  * Accusation ≠ evidence ≠ verdict. Testimony comes only from people who actually observed
    something – or from witnesses who choose to lie (recorded as false for the developer view).
  * Sentences follow the region's laws (restitution, fine, prison, probation, banishment) and
    are limited by existing infrastructure (no prison building -> no prison sentence).
  * Convicted residents may appeal if the region has an appeal instance (court with >= 2 judges
    or an appeal court). Retrials re-examine all evidence; wrongful verdicts can be overturned.
"""
from __future__ import annotations

from . import cognition as C
from . import rules as R
from .state import World, clamp

OFFENSE_ACTION = {"diebstahl": "steal", "betrug": "trade", "gewalt": "confront", "regelverstoss": "forage",
                  "machtmissbrauch": "embezzle", "vertragsbruch": "hire", "meineid": "testify"}


def _soc():
    from . import society as S
    return S


def evidence_threshold(w: World, region: int) -> float:
    law = _soc().active_law(w, region, "beweisregel")
    return float(law["effect"]["params"].get("schwelle", 1.0)) if law else 1.0


def judges_for(w: World, case: dict) -> list[str]:
    S = _soc()
    region = case["region"]
    court = S.institution_of(w, region, "gericht")
    excluded = {case["accused"], case["accuser"]}
    js = [j for j in (court["members"] if court else []) if j in w.agents and w.agents[j]["alive"] and j not in excluded
          and not w.agents[j].get("prison")]
    if not js:
        gov = S.government_of(w, region)
        if gov and gov["form"] in ("rat", "oberhaupt_wahl", "oberhaupt_erblich"):
            js = [j for j in gov["leaders"] if j in w.agents and w.agents[j]["alive"] and j not in excluded]
    return js


def _collect_testimony(w: World, case: dict, thorough: float) -> None:
    """True witnesses come forward (if found); loyal friends may stay silent; enemies may lie."""
    S = _soc()
    key = f"ev:{case['claimed_event']}" if case.get("claimed_event") else None
    true_off = case.get("true_offender")
    case.setdefault("exculpatory", [])
    case.setdefault("false_testimony", [])
    for a in w.living():
        if a["id"] in (case["accused"],) or a["id"] in case["evidence"] or a["id"] in case["exculpatory"] or a["id"] in case["false_testimony"]:
            continue
        f = a["facts"].get(key) if key else None
        if f and f["src"] == "beobachtet":
            if w.rng.random() > thorough:
                continue
            if true_off != case["accused"]:
                case["exculpatory"].append(a["id"])
                continue
            loyal = w.rel(a["id"], case["accused"])["affection"] > 0.8 and a["morals"]["loyalitaet"] > a["morals"]["ehrlichkeit"]
            if not loyal:
                case["evidence"].append(a["id"])
            continue
        # false testimony: only people with strong anger at the accused and weak honesty; rare
        anger = a["emo_targets"].get(case["accused"], {}).get("aerger", 0)
        if anger > 0.6 and a["morals"]["ehrlichkeit"] < 0.3 and w.age(a) >= R.ADULT_AGE and w.rng.random() < 0.3:
            case["false_testimony"].append(a["id"])
            a["secrets"] = (a["secrets"] + [{"t": w.tick, "x": f"Ich habe gegen {w.agents[case['accused']]['name']} falsch ausgesagt."}])[-10:]
            a["stats"]["false_testimony"] = a["stats"].get("false_testimony", 0) + 1


def _statement(w: World, accused: dict, case: dict) -> str:
    """The accused speaks: confession, (truthful) denial or a lie."""
    guilty = case.get("true_offender") == accused["id"]
    if guilty:
        p_conf = clamp(0.6 * accused["morals"]["ehrlichkeit"] + 0.4 * accused["emo"]["scham"] - 0.25 * (1 - accused["morals"]["autoritaet"]))
        if w.rng.random() < p_conf:
            return "gestaendnis"
        accused["secrets"] = (accused["secrets"] + [{"t": w.tick, "x": "Ich habe vor Gericht geleugnet."}])[-10:]
        return "leugnet (unwahr)"
    return "bestreitet (wahr)"


def _score(w: World, judge: dict, case: dict, statement: str) -> float:
    s = 0.0
    for wid in case["evidence"] + case["false_testimony"]:
        if wid == case["accuser"]:
            continue
        est, unc = C.honesty_estimate(judge, wid)
        s += 0.6 + 0.6 * est - 0.3 * unc  # credibility as the judge sees it
    if case["accuser"] in case["evidence"]:
        s += 0.8
    if statement == "gestaendnis":
        s += 2.5
    s -= 1.5 * len(case.get("exculpatory", []))
    if case.get("documented"):
        s += 2.0  # e.g. a false statement established in a previous proceeding
    bias = w.rel(judge["id"], case["accused"])["affection"] - 0.5
    s -= max(0.0, bias) * 1.2 * (1 - judge["morals"]["fairness"])
    return round(s, 2)


def process_cases(w: World) -> None:
    S = _soc()
    for case in list(w.cases.values()):
        if case["status"] in ("schuldig",) and case.get("appeal") and case["appeal"]["status"] == "eingelegt":
            _appeal_hearing(w, case)
            continue
        if case["status"] not in ("behauptung", "ermittlung", "anklage"):
            continue
        accused = w.agents.get(case["accused"])
        accuser = w.agents.get(case["accuser"])
        if not accused or not accused["alive"]:
            case["status"] = "eingestellt"
            case["summary"] = "Verfahren eingestellt (beschuldigte Person verstorben)."
            continue
        region = case["region"]
        watch = S.institution_of(w, region, "wache")
        judges = judges_for(w, case)
        if watch and watch["members"] and case["status"] == "behauptung":
            case["status"] = "ermittlung"
            case.setdefault("log", []).append([w.tick, "Ermittlung durch die Wache"])
        if not judges:
            if w.tick - case["opened"] > 10 * R.TICKS_PER_DAY:
                case["status"] = "ungeklaert"
                case["summary"] = f"Vorwurf gegen {accused['name']} blieb ungeklärt (keine zuständige Instanz)."
                if accuser and accuser["alive"]:
                    accuser["stressors"] = min(1.0, accuser.get("stressors", 0) + 0.1)
                    w.remember(accuser, "justiz", f"Niemand hat meinen Vorwurf gegen {accused['name']} geprüft.", 5, tags=["unrecht"])
            continue
        investigators = [w.agents[m] for m in (watch["members"] if watch else []) if m in w.agents and w.agents[m]["alive"]]
        thorough = max([0.5 + 0.5 * m["reasoning"] for m in investigators] or [0.4])
        _collect_testimony(w, case, thorough)
        if w.tick - case["opened"] < R.TICKS_PER_DAY:
            continue
        judge = w.agents[judges[0]]
        threshold = evidence_threshold(w, region)
        if case["status"] != "anklage":
            # charging decision (presumption of innocence: weak cases are dropped)
            pre = _score(w, judge, case, "bestreitet")
            if pre < threshold * 0.6:
                # no charge without sufficient evidence; investigation goes on for a while, then the case is dropped
                if w.tick - case["opened"] > 3 * R.TICKS_PER_DAY:
                    case["status"] = "eingestellt"
                    case["summary"] = f"Verfahren gegen {accused['name']} eingestellt: zu wenige Beweise (Unschuldsvermutung)."
                    _finish(w, case, accused, accuser, judge, guilty=False)
                continue
            case["status"] = "anklage"
            case.setdefault("log", []).append([w.tick, f"Anklage erhoben (vorläufige Beweislage {pre})"])
            continue
        statement = _statement(w, accused, case)
        score = _score(w, judge, case, statement)
        guilty = score >= threshold
        case["statement"] = statement
        case["score"] = score
        case["threshold"] = threshold
        case["status"] = "schuldig" if guilty else "freigesprochen"
        court_name = "Gericht" if S.institution_of(w, region, "gericht") else "Regierung"
        case["verdict"] = {"judge": judge["id"], "tick": w.tick, "witnesses": [e for e in case["evidence"] if e != case["accuser"]],
                           "by": court_name, "score": score}
        sanction = apply_sentence(w, case, accused, accuser, judge) if guilty else "keine"
        case["sanction"] = sanction
        case["summary"] = (f"Urteil ({court_name}, {judge['name']}): {accused['name']} {'schuldig' if guilty else 'freigesprochen'} "
                           f"({case['type']}); Aussage: {statement}; Beweiswert {score} (nötig {threshold}); Folge: {sanction}.")
        _finish(w, case, accused, accuser, judge, guilty)


def _finish(w: World, case: dict, accused: dict, accuser: dict | None, judge: dict, guilty: bool) -> None:
    S = _soc()
    truth = case.get("true_offender") == case["accused"]
    case["matches_truth"] = (guilty == truth)
    if guilty and not truth:
        w.totals["wrongful_convictions"] += 1
    eid = w.emit("justiz", "urteil", case["summary"], actors=[accused["id"], judge["id"]] + ([accuser["id"]] if accuser else []),
                 x=judge["x"], y=judge["y"], cause=case.get("claim_event"),
                 data={"case": case["id"], "guilty": guilty, "verified_offender": case.get("true_offender")})
    S._announce(w, case["region"], f"case:{case['id']}", case["summary"], eid)
    w.remember(accused, "justiz", case["summary"], 8, event=eid, tags=["urteil"])
    w.totals["verdicts"] += 1
    if guilty:
        accused["convictions"] = accused.get("convictions", 0) + 1
        C.notify(w, accused, "verurteilt", innocent=not truth, accuser=case["accuser"],
                 offense_action=OFFENSE_ACTION.get(case["type"], "steal"))
        if not truth:
            w.remember(accused, "justiz", "Ich wurde für etwas verurteilt, das ich nicht getan habe.", 9, event=eid, tags=["fehlurteil"])
        # stigma: people who learn of the verdict trust the convicted less (reduced by a reintegration law)
        reint = S.active_law(w, case["region"], "wiedereingliederung")
        for a in w.living():
            if f"case:{case['id']}" in a["facts"] and a["id"] != accused["id"]:
                C.opinion(a, accused["id"])["verdacht"] = round(clamp(C.opinion(a, accused["id"])["verdacht"] + (0.1 if reint else 0.25)), 3)
    else:
        C.notify(w, accused, "freigesprochen")
        if accuser and accuser["alive"]:
            accuser["stressors"] = min(1.0, accuser.get("stressors", 0) + 0.05)


def apply_sentence(w: World, case: dict, accused: dict, accuser: dict | None, judge: dict) -> str:
    S = _soc()
    region = case["region"]
    law_type = {"diebstahl": "eigentumsschutz", "betrug": "eigentumsschutz", "gewalt": "gewaltverbot"}.get(case["type"])
    law = S.active_law(w, region, law_type) if law_type else None
    sank = (law["effect"]["params"].get("sanktion") if law else None) or "rueckgabe"
    gov = S.government_of(w, region)
    data = S._event_data(w, case.get("claimed_event"))
    item, n = data.get("item", "food"), int(data.get("n", 1) or 1)
    parts = []
    priors = accused.get("convictions", 0)
    harsh = judge["morals"]["autoritaet"] - judge["morals"]["fuersorge"]
    # restitution comes first where there is a victim
    if case["type"] in ("diebstahl", "betrug") and accuser and accuser["alive"]:
        due = n * (2 if sank == "doppelte_rueckgabe" else 1)
        paid = min(due, w.qty(("agent", accused["id"]), item))
        if paid:
            w.transfer(("agent", accused["id"]), ("agent", accuser["id"]), item, paid)
        parts.append(f"Wiedergutmachung {paid}/{due} {R.ITEM_LABEL.get(item, item)}")
        if paid < due:
            accused["debts"] = accused.get("debts", 0) + 1
    if sank == "geldstrafe" or (case["type"] == "gewalt" and sank == "busse"):
        fine = 3 + priors
        paid = min(fine, w.qty(("agent", accused["id"]), "food"))
        dst = ("inst", gov["id"]) if gov else (("agent", accuser["id"]) if accuser else None)
        if paid and dst:
            w.transfer(("agent", accused["id"]), dst, "food", paid)
        parts.append(f"Geldstrafe {paid}/{fine} Nahrung")
    if sank == "haft":
        prison = next((b for b in w.buildings.values() if b["type"] == "gefaengnis" and b["region"] == region and b["condition"] > 0.2), None)
        if prison:
            days = int(round(2 + 2 * (case["type"] == "gewalt") + 2 * priors + 2 * max(0.0, harsh)))
            imprison(w, accused, prison, days, case)
            parts.append(f"Haft {days} Tage")
        else:
            accused["probation_until"] = w.tick + 14 * R.TICKS_PER_DAY
            parts.append("Bewährung (kein Gefängnis vorhanden)")
    if sank == "bewaehrung":
        if priors > 1 and accused.get("probation_until", 0) > w.tick:
            S.banish(w, accused, region, 14)
            parts.append("Bewährungsbruch: Verbannung 14 Tage")
        else:
            accused["probation_until"] = w.tick + 14 * R.TICKS_PER_DAY
            parts.append("Bewährung 14 Tage")
    if sank == "verbannung":
        S.banish(w, accused, region, 14)
        parts.append("Verbannung 14 Tage")
    if sank == "arrest":
        accused["arrest_until"] = w.tick + 2 * R.TICKS_PER_DAY
        parts.append("Arrest 2 Tage")
    if case["type"] == "machtmissbrauch" and gov and accused["id"] in gov["leaders"]:
        gov["leaders"].remove(accused["id"])
        gov["history"].append([w.tick, f"{accused['name']} wegen Machtmissbrauch abgesetzt"])
        parts.append("Amtsenthebung")
    if case["type"] == "meineid":
        accused["probation_until"] = w.tick + 14 * R.TICKS_PER_DAY
        parts.append("Bewährung wegen Falschaussage")
    return ", ".join(parts) or "Ermahnung"


# ------------------------------------------------------------------ prison
def imprison(w: World, a: dict, prison: dict, days: int, case: dict) -> None:
    a["prison"] = {"building": prison["id"], "until": w.tick + days * R.TICKS_PER_DAY, "case": case["id"], "since": w.tick}
    a["x"], a["y"], a["path"], a["action"], a["pending"] = prison["x"], prison["y"], [], None, None
    a["bio"].append([w.tick, f"Zu {days} Tagen Haft verurteilt."])
    w.remember(a, "biografie", f"Ich bin für {days} Tage im Gefängnis.", 9, tags=["haft"])
    c = w.contracts.get(a.get("employer") or "")
    if c and c["status"] == "aktiv":
        from .economy import end_contract
        end_contract(w, c, "beendet (Haft)")
    w.totals["imprisonments"] += 1


def daily_prisons(w: World) -> None:
    S = _soc()
    for a in w.living():
        pr = a.get("prison")
        if not pr:
            continue
        b = w.buildings.get(pr["building"])
        gov = S.government_of(w, b["region"]) if b else None
        # inmates are fed from the common treasury; if it is empty, they go hungry (a visible failure)
        fed = 0
        for _ in range(2):
            if gov and w.qty(("inst", gov["id"]), "food") > 0:
                w.transfer(("inst", gov["id"]), ("agent", a["id"]), "food", 1)
                fed += 1
        if fed < 2 and not pr.get("warned_day") == w.day:
            pr["warned_day"] = w.day
            w.emit("justiz", "haftbedingungen", f"Im Gefängnis fehlt Nahrung für {a['name']} (Gemeinschaftskasse leer).",
                   actors=[a["id"]], data={"inst": gov["id"] if gov else None}, witnesses=False)
        if b is None or w.tick >= pr["until"]:
            release(w, a, "Haft verbüßt" if b else "Gefängnis existiert nicht mehr")


def release(w: World, a: dict, why: str) -> None:
    S = _soc()
    a["prison"] = None
    a["released"] = w.tick
    reint = S.active_law(w, w.home_region(a), "wiedereingliederung")
    eid = w.emit("justiz", "entlassung", f"{a['name']} wurde aus der Haft entlassen ({why})" +
                 (" – ein Wiedereingliederungsprogramm hilft beim Neuanfang." if reint else "."), actors=[a["id"]], x=a["x"], y=a["y"])
    a["bio"].append([w.tick, f"Aus der Haft entlassen ({why})."])
    w.remember(a, "biografie", "Ich bin wieder frei.", 8, event=eid, tags=["haft"])
    if reint:
        a["stressors"] = max(0.0, a.get("stressors", 0) - 0.2)
        for o in w.living():
            op = o["opinions"].get(a["id"])
            if op:
                op["verdacht"] = round(op["verdacht"] * 0.6, 3)
    a["replan"] = "aus der Haft entlassen"


def in_prison(a: dict) -> bool:
    return bool(a.get("prison"))


# ------------------------------------------------------------------ appeals
def appeal_possible(w: World, case: dict) -> bool:
    S = _soc()
    court = S.institution_of(w, case["region"], "gericht")
    appeal_court = S.institution_of(w, case["region"], "berufungsgericht")
    return bool((appeal_court and appeal_court["members"]) or (court and len(court["members"]) >= 2))


def file_appeal(w: World, a: dict, case: dict) -> bool:
    if case.get("appeal") or case["status"] != "schuldig" or not appeal_possible(w, case):
        return False
    case["appeal"] = {"status": "eingelegt", "filed": w.tick, "by": a["id"]}
    w.emit("justiz", "berufung", f"{a['name']} legt Berufung gegen das Urteil ein ({case['type']}).", actors=[a["id"]],
           x=a["x"], y=a["y"], data={"case": case["id"]})
    return True


def _appeal_hearing(w: World, case: dict) -> None:
    S = _soc()
    if w.tick - case["appeal"]["filed"] < R.TICKS_PER_DAY:
        return
    first = case["verdict"]["judge"]
    appeal_court = S.institution_of(w, case["region"], "berufungsgericht")
    pool = (appeal_court["members"] if appeal_court else []) + judges_for(w, case)
    pool = [j for j in pool if j != first and j in w.agents and w.agents[j]["alive"]]
    accused = w.agents.get(case["accused"])
    if not pool or not accused:
        case["appeal"]["status"] = "unzulässig"
        return
    judge = w.agents[pool[0]]
    _collect_testimony(w, case, 0.8 + 0.2 * judge["reasoning"])
    # a careful second instance may expose false testimony
    exposed = []
    for fid in list(case.get("false_testimony", [])):
        contradiction = bool(case.get("exculpatory")) or w.rng.random() < 0.25 + 0.5 * judge["reasoning"]
        if contradiction:
            exposed.append(fid)
            case["false_testimony"].remove(fid)
    statement = "bestreitet (wahr)" if case.get("true_offender") != accused["id"] else case.get("statement", "leugnet (unwahr)")
    score = _score(w, judge, case, "gestaendnis" if statement == "gestaendnis" else "bestreitet")
    upheld = score >= case.get("threshold", 1.0)
    case["appeal"].update({"status": "bestätigt" if upheld else "aufgehoben", "judge": judge["id"], "tick": w.tick, "score": score,
                           "exposed_false_witnesses": exposed})
    truth = case.get("true_offender") == accused["id"]
    if upheld:
        text = f"Berufung abgewiesen ({judge['name']}): Das Urteil gegen {accused['name']} bleibt bestehen (Beweiswert {score})."
    else:
        case["status"] = "aufgehoben"
        gov = S.government_of(w, case["region"])
        comp = 0
        if gov:
            comp = min(3, w.qty(("inst", gov["id"]), "food"))
            if comp:
                w.transfer(("inst", gov["id"]), ("agent", accused["id"]), "food", comp)
        if accused.get("prison") and accused["prison"].get("case") == case["id"]:
            release(w, accused, "Urteil aufgehoben")
        accused["convictions"] = max(0, accused.get("convictions", 0) - 1)
        text = (f"Berufung erfolgreich ({judge['name']}): Das Urteil gegen {accused['name']} wurde aufgehoben"
                + (f", Entschädigung {comp} Nahrung" if comp else "") + ".")
        if not truth:
            w.totals["overturned_wrongful"] += 1
        for a in w.living():
            if f"case:{case['id']}" in a["facts"]:
                w.remember(a, "justiz", f"Das Urteil gegen {accused['name']} war falsch und wurde aufgehoben.", 6, tags=["fehlurteil"])
                if a["morals"]["fairness"] > 0.7:
                    C.notify(w, a, "gerichtsentscheid_fehlerhaft")
    eid = w.emit("justiz", "berufungsurteil", text, actors=[accused["id"], judge["id"]], data={"case": case["id"], "upheld": upheld,
                 "verdict_correct_now": (upheld == truth)}, witnesses=False)
    S._announce(w, case["region"], f"appeal:{case['id']}", text, eid)
    for fid in exposed:
        fw = w.agents.get(fid)
        if fw and fw["alive"]:
            w.emit("justiz", "falschaussage_aufgedeckt", f"Die Aussage von {fw['name']} im Verfahren gegen {accused['name']} war falsch.",
                   actors=[fid, accused["id"]], data={"case": case["id"]}, witnesses=False)
            S.open_case(w, "meineid", accuser=judge, accused=fw, event=None, evidence=[judge["id"]], claimed_event=None)
            new = list(w.cases.values())[-1]
            new["true_offender"] = fid  # the false statement is an established fact of the record
            new["documented"] = True
