"""Bodies and lifetimes: needs, stress, health, illness, aging, death and births (abstract, non-graphic)."""
from __future__ import annotations

import math

from . import rules as R
from .env import temperature
from .state import World, clamp

WORK_ACTIONS = {"forage", "fish", "farm", "chop", "quarry", "herbs", "build", "craft", "medicine", "work", "repair",
                "research", "teach", "heal", "deliver"}


def in_heated_shelter(w: World, a: dict) -> bool:
    h = w.buildings.get(a.get("home") or "")
    return bool(h and h["x"] == a["x"] and h["y"] == a["y"] and h["condition"] > 0.25 and h.get("heated", True))


def update_needs(w: World, a: dict) -> None:
    n = a["needs"]
    act = (a.get("action") or {}).get("type")
    n["hunger"] = clamp(n["hunger"] + R.NEED_RATE["hunger"] * (1.3 if act in WORK_ACTIONS else 1.0))
    hot = temperature(w, a["x"], a["y"]) > 26
    n["thirst"] = clamp(n["thirst"] + R.NEED_RATE["thirst"] * (1.5 if hot else 1.0))
    n["social"] = clamp(n["social"] + R.NEED_RATE["social"] * (0.5 + a["personality"]["extraversion"]))
    if a.get("asleep"):
        n["energy"] = clamp(n["energy"] + (R.ENERGY_SLEEP_SHELTER if in_heated_shelter(w, a) else R.ENERGY_SLEEP_OUTSIDE))
    else:
        drain = R.ENERGY_DRAIN_WORK if act in WORK_ACTIONS else R.ENERGY_DRAIN_IDLE
        n["energy"] = clamp(n["energy"] - drain * (1.4 if a.get("chronic") else 1.0))
    # exposure to cold without (heated) shelter
    t = temperature(w, a["x"], a["y"])
    if t < R.COLD_THRESHOLD_C and not in_heated_shelter(w, a):
        active = 0.5 if (not a.get("asleep") and act in WORK_ACTIONS) else 1.0  # working keeps warm
        a["exposure"] = clamp(a["exposure"] + 0.005 * active * (R.COLD_THRESHOLD_C - t) / 6)
    else:
        a["exposure"] = clamp(a["exposure"] - 0.02)
    # stress moves toward a level determined by unmet needs and recent stressors
    ill = a["illness"]["severity"] if a.get("illness") else 0.0
    target = (0.45 * max(0, n["hunger"] - 0.5) + 0.45 * max(0, n["thirst"] - 0.5) + 0.35 * a["exposure"]
              + 0.3 * max(0, 0.3 - n["energy"]) + 0.3 * ill + 0.2 * max(0, n["social"] - 0.7)
              + a.get("stressors", 0.0))
    rate = 0.01 * (1.5 - a["personality"]["patience"])
    n["stress"] = clamp(n["stress"] + (clamp(target) - n["stress"]) * rate)
    a["stressors"] = max(0.0, a.get("stressors", 0.0) * 0.997)
    # health
    h = a["health"]
    if n["hunger"] >= 1.0:
        h -= 0.0025
    if n["thirst"] >= 1.0:
        h -= 0.006
    if a["exposure"] > 0.7:
        h -= 0.0012
    if ill:
        h -= 0.0012 * ill
    if n["hunger"] < 0.6 and n["thirst"] < 0.6 and not ill and a["exposure"] < 0.5:
        h += 0.0012
    a["health"] = clamp(h, 0.0, a["max_health"])


def child_care(w: World, a: dict) -> None:
    """Household rule: young children (< 12) are fed from household stocks when hungry, if any exist."""
    if a["needs"]["hunger"] < 0.45 or w.age(a) >= 12:
        return
    sources = []
    home = w.buildings.get(a.get("home") or "")
    if home:
        sources.append(("building", home["id"]))
    for pid in a["parents"]:
        p = w.agents.get(pid)
        if p and p["alive"]:
            sources.append(("agent", pid))
    for ref in sources:
        if w.qty(ref, "food") > 0:
            w.consume(ref, "food", 1, "kinderversorgung")
            a["needs"]["hunger"] = clamp(a["needs"]["hunger"] - R.MEAL_RELIEF)
            return
    if a["needs"]["hunger"] > 0.8 and w.tick % R.TICKS_PER_DAY == 0:
        for pid in a["parents"]:
            p = w.agents.get(pid)
            if p and p["alive"]:
                p["stressors"] = min(1.0, p.get("stressors", 0) + 0.15)
                w.remember(p, "sorge", f"{a['name']} hat Hunger und unser Haushalt hat keine Nahrung.", 6, subjects=[a["id"]],
                           tags=["hunger", "familie"])


def health_status(w: World, a: dict) -> list[str]:
    out = []
    if not a["alive"]:
        return ["verstorben"]
    if a.get("illness"):
        out.append("erkrankt")
    if a.get("chronic"):
        out.append("chronisch beeinträchtigt")
    if a["health"] < 0.3 or (w.age(a) > 75 and a["health"] < 0.6):
        out.append("pflegebedürftig")
    if a["needs"]["energy"] < 0.2:
        out.append("erschöpft")
    if a["needs"]["stress"] > 0.65:
        out.append("gestresst")
    if not a.get("illness") and a.get("recovering_until", -1) > w.tick:
        out.append("genesend")
    return out or ["gesund"]


def daily_health(w: World) -> None:
    living = w.living()
    sick_at = {}
    for a in living:
        if a.get("illness") and a["illness"].get("contagious"):
            key = (a["x"] // 4, a["y"] // 4)
            sick_at[key] = sick_at.get(key, 0) + 1
    for a in living:
        age = w.age(a)
        n = a["needs"]
        ill = a.get("illness")
        if ill:
            treated = ill.get("treated_until", -1) > w.tick
            ok = n["hunger"] < 0.6 and a["exposure"] < 0.5
            delta = -0.06 - (0.12 if treated else 0) if ok else 0.04
            ill["severity"] = round(clamp(ill["severity"] + delta + w.rng.gauss(0, 0.02)), 3)
            ill["days"] = ill.get("days", 0) + 1
            if ill["severity"] <= 0.02:
                if ill["days"] > 6 and ill.get("peak", 0) > 0.5 and w.chance(0.15):
                    a["chronic"] = True
                    a["max_health"] = 0.8
                    w.emit("leben", "chronisch", f"{a['name']} ist nach {ill['name']} dauerhaft beeinträchtigt.",
                           actors=[a["id"]], x=a["x"], y=a["y"], public=False, witnesses=False)
                a["illness"] = None
                a["recovering_until"] = w.tick + 2 * R.TICKS_PER_DAY
                w.remember(a, "gesundheit", f"Ich habe {ill['name']} überstanden.", 4, tags=["krankheit"])
            else:
                ill["peak"] = max(ill.get("peak", 0), ill["severity"])
        else:
            contagion = sick_at.get((a["x"] // 4, a["y"] // 4), 0)
            no_water = 0.0 if w.near_water(a["x"], a["y"], 6) else 0.5
            risk = 0.004 * (1 + 2 * n["hunger"] + 1.5 * a["exposure"] + 1.5 * n["stress"] + max(0, age - 50) / 25
                            + no_water) * (1 + 1.5 * contagion)
            if w.chance(risk):
                names = list(R.ILLNESSES)
                weights = [R.ILLNESSES[k][0] for k in names]
                name = w.rng.choices(names, weights)[0]
                lo, hi = R.ILLNESSES[name][1]
                sev = round(w.rng.uniform(lo, hi) * (1 + max(0, age - 60) / 40), 3)
                a["illness"] = {"name": name, "severity": sev, "contagious": R.ILLNESSES[name][2], "since": w.tick,
                                "days": 0, "peak": sev}
                eid = w.emit("leben", "erkrankung", f"{a['name']} ist an {name} erkrankt.", actors=[a["id"]],
                             x=a["x"], y=a["y"], public=False, witnesses=False)
                w.remember(a, "gesundheit", f"Ich bin an {name} erkrankt.", 6, event=eid, tags=["krankheit"])
                from .cognition import notify
                notify(w, a, "erkrankt", factors={"hunger": 2 * n["hunger"], "kaelte": 1.5 * a["exposure"], "stress": 1.5 * n["stress"],
                                                  "wasser": no_water, "ansteckung": 1.5 * contagion * 0.3})
        # natural mortality hazard (per year, converted per day), rises with age and poor health
        hazard_year = 0.0006 * math.exp(0.085 * age) * (1 + 2.5 * (1 - a["health"]))
        if age > 1 and w.chance(hazard_year / R.DAYS_PER_YEAR):
            cause = "hohes Alter" if age > 65 else (f"Krankheit ({a['illness']['name']})" if a.get("illness") else "plötzliche Erkrankung")
            kill(w, a, cause)
            continue
        if a["health"] <= 0.0:
            kill(w, a, _cause_from_state(a))


def _cause_from_state(a: dict) -> str:
    n = a["needs"]
    if n["thirst"] >= 1.0:
        return "Wassermangel (Versorgungskrise)"
    if n["hunger"] >= 1.0:
        return "Nahrungsmangel (Versorgungskrise)"
    if a.get("illness"):
        return f"Krankheit ({a['illness']['name']})"
    if a["exposure"] > 0.7:
        return "Kälte ohne Unterkunft"
    return a.get("last_injury") or "Erschöpfung"


def kill(w: World, a: dict, cause: str, cause_event: int | None = None) -> int:
    """Permanent death in the canonical history. ID, history and effects remain; no respawn."""
    if not a["alive"]:
        return 0
    from .society import on_death
    age = int(w.age(a))
    a["alive"] = False
    a["death_tick"] = w.tick
    a["death_cause"] = cause
    a["action"] = None
    a["path"] = []
    a["asleep"] = False
    w.totals["deaths"] += 1
    w.daily["deaths"] += 1
    eid = w.emit("leben", "tod", f"{a['name']} {a['family']} ist im Alter von {age} Jahren verstorben (Ursache: {cause}).",
                 actors=[a["id"]], x=a["x"], y=a["y"], data={"cause": cause, "age": age}, cause=cause_event,
                 witnesses=False)
    a["bio"].append([w.tick, f"Verstorben mit {age} Jahren ({cause})."])
    on_death(w, a, eid)
    for m in a["ltm"]:
        w._archive(a, m, "verstorben")
    a["ltm"], a["stm"] = [], []
    return eid


def process_births(w: World) -> None:
    from .genesis import GIVEN, make_agent
    for a in list(w.living()):
        exp = a.get("expecting")
        if not exp or exp["due"] > w.tick:
            continue
        a["expecting"] = None
        partner = w.agents.get(exp["partner"])
        if len(w.living()) >= int(w.config.get("max_population", 120)):
            w.emit("system", "populationsgrenze", "Geburt nicht simuliert: technische Populationsgrenze erreicht.",
                   witnesses=False)
            continue
        parents = [p for p in (a, partner) if p]
        pers = {}
        for k in a["personality"]:
            base = sum(p["personality"][k] for p in parents) / len(parents)
            pers[k] = round(clamp(base + w.rng.gauss(0, 0.15), 0.02, 0.98), 3)
        vals = {k: round(clamp(sum(p["values"][k] for p in parents) / len(parents) + w.rng.gauss(0, 0.15), 0.02, 0.98), 3)
                for k in a["values"]}
        used = {x["name"] for x in w.agents.values()}
        pool = [g for g in GIVEN if g not in used] or GIVEN
        home = w.buildings.get(a.get("home") or "")
        x, y = (home["x"], home["y"]) if home else (a["x"], a["y"])
        child = make_agent(w, w.rng, name=w.rng.choice(pool), family=a["family"], origin="geboren im Tal",
                           birth_tick=w.tick, x=x, y=y, personality=pers, values=vals,
                           generation=max(p.get("generation", 0) for p in parents) + 1, parents=[p["id"] for p in parents])
        child["techs"] = list(R.BASE_TECHS)
        child["skills"] = {s: 0.0 for s in R.SKILLS}
        child["home"] = a.get("home")
        child["needs"] = {"hunger": 0.2, "thirst": 0.1, "energy": 0.9, "social": 0.2, "stress": 0.05}
        for p in parents:
            p["children"].append(child["id"])
            w.adjust_rel(p["id"], child["id"], affection=0.12, trust=0.1, familiarity=0.3, note="Geburt")
            w.adjust_rel(child["id"], p["id"], affection=0.12, trust=0.12, familiarity=0.3)
        w.totals["births"] += 1
        w.daily["births"] += 1
        names = " und ".join(p["name"] for p in parents)
        eid = w.emit("leben", "geburt", f"{child['name']} {child['family']} wurde geboren (Eltern: {names}).",
                     actors=[child["id"]] + [p["id"] for p in parents], x=x, y=y, data={"generation": child["generation"]})
        child["bio"].append([w.tick, f"Geboren als Kind von {names}."])
        for p in parents:
            p["bio"].append([w.tick, f"Kind {child['name']} geboren."])
            w.remember(p, "biografie", f"Unser Kind {child['name']} wurde geboren.", 9, event=eid, subjects=[child["id"]],
                       tags=["familie"])
            from .cognition import notify
            notify(w, p, "geburt")


def daily_growth(w: World) -> None:
    """Childhood development and learning; coming of age."""
    from .society import school_available
    for a in w.living():
        age = w.age(a)
        if age < R.ADULT_AGE:
            lo, hi = R.SCHOOL_AGE
            learn_rate = 0.004
            if lo <= age <= hi and school_available(w, a):
                learn_rate = 0.012
                a["stats"]["schultage"] = a["stats"].get("schultage", 0) + 1
                for t in _teachable_techs(w, a):
                    if w.chance(0.03):
                        a["techs"] = sorted(set(a["techs"] + [t]))
            for s in a["skills"]:
                a["skills"][s] = round(min(1.0, a["skills"][s] + learn_rate * w.rng.random()), 4)
            # learning from parents at home
            for pid in a["parents"]:
                p = w.agents.get(pid)
                if p and p["alive"] and age >= 4:
                    missing = [t for t in p["techs"] if t not in a["techs"]]
                    if missing and w.chance(0.01):
                        a["techs"] = sorted(set(a["techs"] + [w.rng.choice(missing)]))
            if int(age) == R.ADULT_AGE - 1 and (w.tick - a["birth_tick"]) % R.TICKS_PER_YEAR < R.TICKS_PER_DAY:
                pass
        elif not a.get("adult_announced") and a["generation"] > 0:
            a["adult_announced"] = True
            eid = w.emit("leben", "volljaehrig", f"{a['name']} {a['family']} ist erwachsen geworden.", actors=[a["id"]],
                         x=a["x"], y=a["y"])
            a["bio"].append([w.tick, "Erwachsen geworden."])
            w.remember(a, "biografie", "Ich bin jetzt erwachsen und treffe meine eigenen Entscheidungen.", 8, event=eid)


def _teachable_techs(w: World, a: dict) -> list[str]:
    known_by_teachers = set()
    for t in w.living():
        if t.get("action", {}) and (t.get("action") or {}).get("type") == "teach":
            known_by_teachers |= set(t["techs"])
    for d in w.documents.values():
        known_by_teachers.add(d.get("tech"))
    return [t for t in known_by_teachers if t and t not in a["techs"] and all(p in a["techs"] for p in R.TECHS.get(t, {}).get("prereq", []))]
