"""Training data from the simulation – only what can be verified.

Pipeline: capture (world DB) → quality filter → verification (engine ground truth) →
deduplication + eval exclusion + safety filter (data.add_example) → versioned dataset
(existing builder) → LoRA → independent evaluation → manual activation.

Verified task families (answers computed by code from real simulation records):
  sim_trade     price arithmetic from real barter trades
  sim_vote      vote counting under a stated rule from real ballots
  sim_supply    supply planning from residents' real stocks
  sim_factcheck claim vs. observation (claims, witnesses and offenders from the event log)

Unverifiable material (dialogue lines) is only exported on request, as *pending* examples
from a self-generated source, and must be reviewed by hand in the AI Lab.
"""
from __future__ import annotations

import random

from ..training import curriculum as cur
from . import rules as R
from .state import World

INSTR = cur.ANSWER_INSTRUCTION


def _task(family: str, prompt: str, answer: str, solution: str, kind: str, meta: dict) -> cur.Task:
    return cur.Task(family=family, difficulty=2, prompt=f"{prompt} {INSTR}", answer=answer, solution=solution, kind=kind,
                    meta={"source": "simulation", **meta})


def _fmt(x: float) -> str:
    return cur._fmt(round(x, 2))


def trade_tasks(events: list[dict], names: dict[str, str]) -> list[cur.Task]:
    out = []
    for e in events:
        d = e["data"]
        if e["kind"] != "tausch" or d.get("give", "").startswith("coin") or d.get("get", "").startswith("coin"):
            continue
        qg, qr = int(d["q_give"]), int(d["q_get"])
        give, get = R.ITEM_LABEL[d["give"]], R.ITEM_LABEL[d["get"]]
        a, b = (names.get(x, x) for x in e["actors"][:2])
        price = qg / qr
        prompt = (f"{a} gab {b} {qg} Einheiten {give} und erhielt dafür {qr} Einheiten {get}. "
                  f"Wie viele Einheiten {give} kostete eine Einheit {get}? Runde auf zwei Nachkommastellen.")
        sol = f"{qg} : {qr} = {_fmt(price)}.\nAntwort: {_fmt(price)}"
        out.append(_task("sim_trade", prompt, _fmt(price), sol, "number", {"event": e["id"]}))
    return out


def vote_tasks(events: list[dict], rng: random.Random) -> list[cur.Task]:
    out = []
    for e in events:
        if e["kind"] != "abstimmung":
            continue
        d = e["data"]
        ja, nein, enth = int(d.get("ja", 0)), int(d.get("nein", 0)), int(d.get("enthaltung", 0))
        k = rng.randint(2, max(3, ja + 2))
        ok = ja > nein and ja >= k
        prompt = (f"Bei einer Abstimmung gab es {ja} Ja-Stimmen, {nein} Nein-Stimmen und {enth} Enthaltungen. Regel: Ein Vorschlag "
                  f"ist angenommen, wenn es mehr Ja- als Nein-Stimmen gibt und mindestens {k} Ja-Stimmen. Ist er angenommen? "
                  "Antworte mit ja oder nein.")
        sol = (f"Mehr Ja als Nein: {'ja' if ja > nein else 'nein'} ({ja} gegen {nein}). Mindestens {k} Ja: "
               f"{'ja' if ja >= k else 'nein'}.\nAntwort: {'ja' if ok else 'nein'}")
        out.append(_task("sim_vote", prompt, "ja" if ok else "nein", sol, "exact", {"event": e["id"], "k": k}))
    return out


def supply_tasks(w: World) -> list[cur.Task]:
    out = []
    for a in w.agents.values():
        if not a["alive"] or w.age(a) < R.ADULT_AGE:
            continue
        food = int((a.get("inv") or {}).get("food", 0))
        if food < 2:
            continue
        days = food // 2
        prompt = (f"{a['name']} besitzt {food} Einheiten Nahrung und isst 2 Mahlzeiten pro Tag (je 1 Einheit). "
                  "Für wie viele volle Tage reicht der Vorrat?")
        sol = f"{food} : 2 = {days}{' Rest 1' if food % 2 else ''}. Volle Tage: {days}.\nAntwort: {days}"
        out.append(_task("sim_supply", prompt, str(days), sol, "number", {"agent": a["id"], "tick": w.tick}))
    return out


def factcheck_tasks(w: World, events_by_id: dict[int, dict]) -> list[cur.Task]:
    out = []
    data = w.config.get("_eventdata", {})
    for c in w.cases.values():
        ev = data.get(str(c.get("claimed_event")))
        accuser, accused = w.agents.get(c["accuser"]), w.agents.get(c["accused"])
        if not accuser or not accused:
            continue
        witnesses = [w.agents[x]["name"] for x in c["evidence"] if x in w.agents and x != c["accuser"]]
        offender = ev.get("offender") if ev else None
        observed = (f"Beobachtung von {', '.join(witnesses)}: {w.agents[offender]['name'] if offender in w.agents else 'jemand'} "
                    f"wurde beim Wegnehmen gesehen.") if witnesses and offender else "Es gibt keine Zeugenbeobachtung."
        supported = bool(witnesses) and offender == c["accused"]
        prompt = (f"Behauptung: „{accused['name']} hat etwas von {accuser['name']} genommen.“ {observed} "
                  f"Ist die Behauptung durch eine Beobachtung belegt? Antworte mit ja oder nein.")
        sol = ("Die Beobachtung nennt genau die beschuldigte Person." if supported else
               "Ohne Beobachtung, die die beschuldigte Person nennt, ist die Behauptung nicht belegt.") + \
            f"\nAntwort: {'ja' if supported else 'nein'}"
        out.append(_task("sim_factcheck", prompt, "ja" if supported else "nein", sol, "exact", {"case": c["id"]}))
    return out


def all_tasks(w: World, events: list[dict], seed: int = 1) -> list[cur.Task]:
    rng = random.Random(seed)
    names = {a["id"]: a["name"] for a in w.agents.values()}
    tasks = trade_tasks(events, names) + vote_tasks(events, rng) + supply_tasks(w) + factcheck_tasks(w, {e["id"]: e for e in events})
    # every exported task must verify against its own gold solution (guards against generator bugs)
    return [t for t in tasks if cur.verify(t, t.solution)[0]]


def export_to_pool(s, w: World, events: list[dict], *, per_family: int = 60, seed: int = 1,
                   include_dialogs: bool = False) -> dict:
    """Write verified simulation tasks into the example pool (approved) and optionally dialogues (pending)."""
    from ..training import data as D
    from ..training.evalset import eval_prompt_hashes
    evalh = eval_prompt_hashes()
    tasks = all_tasks(w, events, seed)
    rng = random.Random(seed)
    rng.shuffle(tasks)
    counts: dict[str, int] = {}
    stats = {"verified_tasks": 0, "duplicates": 0, "eval_excluded": 0, "rejected_filter": 0, "dialogs_pending": 0}
    for t in tasks:
        if counts.get(t.family, 0) >= per_family:
            continue
        if t.prompt_hash in evalh:
            stats["eval_excluded"] += 1
            continue
        try:
            ex = D.add_example(s, messages=[{"role": "user", "content": t.prompt}], response=t.solution, source="sim_gold",
                               family=t.family, verified=True, verifier=f"simulation.{t.family}", status="approved",
                               meta={**t.meta, "world": w.world_id, "answer": t.answer})
        except D.DataError:
            stats["rejected_filter"] += 1
            continue
        if ex:
            counts[t.family] = counts.get(t.family, 0) + 1
            stats["verified_tasks"] += 1
        else:
            stats["duplicates"] += 1
    if include_dialogs:
        for e in events:
            if e["kind"] != "dialog" or "„" not in e["text"]:
                continue
            line = e["text"].split("„", 1)[1].rstrip("“")
            try:
                if D.add_example(s, messages=[{"role": "user", "content": "Sag etwas Freundliches zu einer Nachbarin."}],
                                 response=line, source="sim_agent", status="pending",
                                 meta={"world": w.world_id, "event": e["id"], "generated_by": e["data"].get("generated_by")}):
                    stats["dialogs_pending"] += 1
            except D.DataError:
                stats["rejected_filter"] += 1
    return {**stats, "per_family": counts}


def build_sim_eval(n: int = 32, seed: int = 424242, days: int = 40) -> list[dict]:
    """A held-out evaluation world: separate seed, rules only, never used for training data."""
    from . import engine
    from .genesis import create_world
    w = create_world("eval-world", "Evaluationswelt", seed)
    engine.run_ticks(w, days * R.TICKS_PER_DAY)
    tasks = all_tasks(w, list(w.event_buffer), seed)
    rng = random.Random(seed)
    by_fam: dict[str, list] = {}
    for t in tasks:
        by_fam.setdefault(t.family, []).append(t)
    out: list[cur.Task] = []
    fams = sorted(by_fam)
    i = 0
    seen = set()
    while len(out) < n and any(by_fam.values()):
        fam = fams[i % len(fams)]
        i += 1
        if by_fam[fam]:
            t = by_fam[fam].pop(rng.randrange(len(by_fam[fam])))
            if t.prompt_hash not in seen:
                seen.add(t.prompt_hash)
                out.append(t)
    return [t.to_dict() for t in out]


# ------------------------------------------------------------------ resident decisions (World 3.0)
TRAIN_DECISION_CATS = ("bedarf", "planung", "vertrauen", "folgen", "ursache")  # "anpassung"/"normen" stay untrained (transfer test)


def export_resident_decisions(s, *, worlds: int = 6, per_cat: int = 10, seed_base: int = 900_000) -> dict:
    """Situation-determined decision examples from separate training worlds (never the benchmark seed).
    The answer is fixed by the constructed situation, so these are verified by construction."""
    from ..training import data as D
    from . import benchmark as B
    stats = {"added": 0, "duplicates": 0, "rejected_filter": 0, "worlds": worlds, "categories": list(TRAIN_DECISION_CATS)}
    for k in range(worlds):
        seed = seed_base + k
        if seed in (B.BENCH_SEED, 424242):
            continue
        for it in B.build_items(seed=seed, per_cat=per_cat):
            if it["cat"] not in TRAIN_DECISION_CATS:
                continue
            ans = it["correct"][0] + 1
            try:
                ex = D.add_example(s, messages=[{"role": "system", "content": it["system"]}, {"role": "user", "content": it["user"]}],
                                   response=f"Wahl: {ans}", source="sim_gold", family="bewohner_entscheidung", verified=True,
                                   verifier=f"benchmark.{it['cat']}", status="approved",
                                   meta={"world_seed": seed, "cat": it["cat"], "answer": str(ans)})
            except D.DataError:
                stats["rejected_filter"] += 1
                continue
            if ex:
                stats["added"] += 1
            else:
                stats["duplicates"] += 1
    return stats
