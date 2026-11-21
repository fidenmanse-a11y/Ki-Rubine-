"""Action catalog: which options a resident has (from their own knowledge), how attractive they are
(needs, personality, values, goals, relationships), and how the world engine executes them.

Language models never change state directly: they can only pick one of these validated options.
"""
from __future__ import annotations

import math

from . import rules as R
from . import society as S
from .construction import choose_plot, deliver, missing_materials, repair, start_site, work_on
from .economy import (end_contract, execute_trade, food_days, give, hire, honesty, lend, propose_trade,
                      region_currency, repay, stock, valuation, wage_offer)
from .env import temperature
from .perception import find_path, known_spots, nearest, perceive
from .state import World, clamp, dist

SIGNIFICANT = {"build_start", "propose", "steal", "partner", "child", "hire", "embezzle", "protest", "lend", "join"}
CATEGORY = {"eat": "versorgung", "drink": "versorgung", "sleep": "erholung", "rest": "erholung", "forage": "vorraete",
            "fish": "vorraete", "farm": "vorraete", "chop": "vorraete", "quarry": "vorraete", "herbs": "vorraete",
            "craft": "handel", "medicine": "wissen", "build_start": "bauen", "deliver": "bauen", "build": "bauen",
            "repair": "bauen", "talk": "gemeinschaft", "help": "gemeinschaft", "trade": "handel", "vote": "politik",
            "propose": "politik", "notices": "politik", "join": "politik", "protest": "politik", "donate": "gemeinschaft",
            "research": "wissen", "teach": "wissen", "write": "wissen", "read": "wissen", "art": "wissen",
            "heal": "gemeinschaft", "seek_care": "versorgung", "work": "handel", "hire": "handel", "lend": "handel",
            "repay": "handel", "partner": "familie", "child": "familie", "steal": "versorgung", "embezzle": "handel",
            "leave": "versorgung", "play": "erholung", "school": "wissen", "follow": "familie"}
FOCUS = {"vorraete": "Vorräte anlegen", "bauen": "Bauen", "handel": "Handel & Arbeit", "politik": "Gemeinschaft & Politik",
         "wissen": "Wissen & Kultur", "familie": "Familie & Freunde", "erholung": "Erholung", "gemeinschaft": "Anderen helfen"}


def opt(kind: str, label: str, u: float, *, dest=None, target=None, data=None, dur: int = 4) -> dict:
    return {"type": kind, "label": label, "u": round(u, 3), "dest": list(dest) if dest else None, "target": target,
            "data": data or {}, "dur": dur, "sig": kind in SIGNIFICANT, "cat": CATEGORY.get(kind, "sonst")}


def efficiency(w: World, a: dict, skill: str) -> float:
    n = a["needs"]
    tools = 1.25 if (a.get("inv") or {}).get("tools", 0) > 0 else 1.0
    return max(0.1, (0.45 + 0.55 * n["energy"]) * (1 - 0.3 * n["stress"]) * (0.5 + 0.5 * a["health"])
               * (0.7 + a["skills"].get(skill, 0)) * tools)


def find_water(w: World, a: dict) -> list[int] | None:
    x, y = a["x"], a["y"]
    if w.near_water(x, y, 1):
        return [x, y]
    for r in range(1, 14):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if abs(dx) != r else range(-r, r + 1):
                nx, ny = x + dx, y + dy
                if w.in_bounds(nx, ny) and w.passable(nx, ny) and w.near_water(nx, ny, 1):
                    return [nx, ny]
    return None


def _home(w: World, a: dict) -> dict | None:
    return w.buildings.get(a.get("home") or "")


def _banned_here(w: World, a: dict, x: int, y: int) -> bool:
    until = a["banned"].get(str(w.region_of(x, y)))
    return bool(until and until > w.tick)


def _nearby(w: World, a: dict, r: int = 3) -> list[dict]:
    return [b for b in w.agents_near(a["x"], a["y"], r) if b["id"] != a["id"]]


# ------------------------------------------------------------------ option generation
def generate_options(w: World, a: dict) -> list[dict]:
    age = w.age(a)
    if age < 12:
        return _child_options(w, a)
    n = a["needs"]
    p, v = a["personality"], a["values"]
    goals = {g["type"] for g in a["goals"]}
    out: list[dict] = []
    home = _home(w, a)
    fd = food_days(w, a)
    food_need = clamp(1 - fd / 4)
    night = w.is_night()
    region = w.region_of(a["x"], a["y"])
    gov = S.government_of(w, region)
    arrested = (a.get("arrest_until") or 0) > w.tick

    # --- survival
    inv_food = (a.get("inv") or {}).get("food", 0)
    if inv_food > 0 and n["hunger"] > 0.2:
        out.append(opt("eat", "Essen", 3.2 * n["hunger"] ** 1.6 + (0.3 if w.hour in (7, 12, 18) else 0), dur=1))
    elif home and (home.get("inv") or {}).get("food", 0) > 0 and n["hunger"] > 0.3:
        out.append(opt("eat", "Zu Hause essen", 3.0 * n["hunger"] ** 1.6, dest=(home["x"], home["y"]), target=home["id"], dur=1))
    water = find_water(w, a)
    if water and n["thirst"] > 0.2:
        out.append(opt("drink", "Trinken", 3.6 * n["thirst"] ** 1.6 - dist(a["x"], a["y"], *water) / 60, dest=water, dur=1))
    if night or n["energy"] < 0.3:
        u = (1.6 + 2.2 * (1 - n["energy"])) if night else 3.0 * max(0, 0.3 - n["energy"]) * 3
        dest = (home["x"], home["y"]) if home and dist(a["x"], a["y"], home["x"], home["y"]) < 30 else None
        out.append(opt("sleep", "Schlafen" + (" (zu Hause)" if dest else " (im Freien)"), u, dest=dest, dur=2))
    out.append(opt("rest", "Ausruhen", 0.15 + 0.7 * n["stress"] + (0.2 if night else 0), dur=3))
    if home and a["exposure"] > 0.3 and (a["x"], a["y"]) != (home["x"], home["y"]):
        out.append(opt("rest", "Zu Hause aufwärmen", 2.2 * a["exposure"], dest=(home["x"], home["y"]), target=home["id"], dur=4))
    if arrested:
        return [o for o in out if o["type"] in ("eat", "sleep", "rest")] or [opt("rest", "Im Arrest", 1, dur=4)]
    if a.get("prison"):
        return _prison_options(w, a, out)
    if _banned_here(w, a, a["x"], a["y"]):
        out.append(opt("leave", "Die Region verlassen (verbannt)", 4.0, dur=1))
    if night and not a["personality"]["extraversion"] > 0.85:
        return out
    if a.get("illness") and a["illness"]["severity"] > 0.25:
        healer = _find_healer(w, a)
        if healer:
            out.append(opt("seek_care", "Behandlung suchen", 1.8 * a["illness"]["severity"] + 0.3, dest=healer["dest"],
                           target=healer["id"], dur=2))

    # --- production (based on own knowledge of places)
    work_u = 1.3 * food_need + 0.15 + 0.2 * v["wealth"] + (0.25 if "wohlstand" in goals else 0)
    law_res = S.active_law(w, region, "ressourcenschutz")
    for res, kind, label, skill in (("forage", "forage", "Sammeln", "gathering"), ("fish", "fish", "Fischen", "gathering")):
        spots = known_spots(w, a, res)
        if spots:
            spot, d = nearest(spots, a["x"], a["y"])
            if _banned_here(w, a, spot[0], spot[1]):
                continue
            u = work_u * (0.8 + a["skills"][skill]) - d / 40
            forbidden = law_res and law_res["effect"]["params"].get("ressource") == res and S.knows_law(w, a, law_res)
            if forbidden:
                u -= 0.6 * p["conscientiousness"] + 0.3
            out.append(opt(kind, label + (" (verboten)" if forbidden else ""), u, dest=spot, data={"res": res, "forbidden": bool(forbidden)}, dur=4))
    farm = _usable_farm(w, a)
    if farm:
        out.append(opt("farm", "Feld bestellen", (work_u * 1.25 + 0.1) * _season_factor(w), dest=(farm["x"], farm["y"]),
                       target=farm["id"], dur=8))
    plan = w.sites.get(a.get("building_plan") or "")
    need_mat = missing_materials(plan) if plan else {}
    for res, kind, label, skill, item in (("wood", "chop", "Holz fällen", "woodcutting", "wood"),
                                          ("stone", "quarry", "Steine brechen", "masonry", "stone")):
        spots = known_spots(w, a, res)
        if not spots:
            continue
        spot, d = nearest(spots, a["x"], a["y"])
        have = stock(w, a, item)
        need = 0.0
        if need_mat.get(item, 0) > (a.get("inv") or {}).get(item, 0):
            need += 1.1
        if item == "wood" and home and w.season >= 2 and have < 6:
            need += 0.9
        if have < 3:
            need += 0.15 + 0.25 * v["wealth"]
        out.append(opt(kind, label, need * (0.7 + a["skills"][skill]) - d / 40, dest=spot, data={"res": res}, dur=4))
    if ("kraeuterkunde" in a["techs"] or a["skills"]["healing"] > 0.25) and stock(w, a, "herbs") < 4:
        spots = known_spots(w, a, "herbs")
        if spots:
            spot, d = nearest(spots, a["x"], a["y"])
            out.append(opt("herbs", "Kräuter sammeln", 0.35 + 0.4 * a["skills"]["healing"] - d / 40, dest=spot, data={"res": "herbs"}, dur=3))
    shop = _usable_building(w, a, "werkstatt")
    if shop and "werkzeugbau" in a["techs"] and stock(w, a, "wood") >= 1 and stock(w, a, "stone") >= 1:
        out.append(opt("craft", "Werkzeug herstellen", 0.35 + 0.7 * (stock(w, a, "tools") == 0) + 0.3 * v["wealth"],
                       dest=(shop["x"], shop["y"]), target=shop["id"], dur=4))
    if "kraeuterkunde" in a["techs"] and (a.get("inv") or {}).get("herbs", 0) >= 2:
        out.append(opt("medicine", "Heilmittel herstellen", 0.25 + 0.6 * a["skills"]["healing"], dur=3))

    # --- building
    _building_options(w, a, out, home, plan, need_mat, goals)

    # --- work contracts
    c = w.contracts.get(a.get("employer") or "")
    if c and c["status"] == "aktiv" and 7 <= w.hour < 17 and not c.get("worked_today") and c["building"] in w.buildings:
        b = w.buildings[c["building"]]
        out.append(opt("work", f"Arbeiten bei {w.agents[c['employer']]['name']}", 1.0 + 0.5 * p["conscientiousness"] + 0.3 * food_need,
                       dest=(b["x"], b["y"]), target=c["id"], dur=8))
    _employer_options(w, a, out)

    # --- social
    near = _nearby(w, a, 3)
    awake = [b for b in near if not b.get("asleep") and w.age(b) >= 6]
    if awake:
        partner_pick = max(awake, key=lambda b: w.rel(a["id"], b["id"])["affection"] + w.rng.random() * 0.5)
        out.append(opt("talk", f"Mit {partner_pick['name']} reden", 1.3 * n["social"] + 0.25 * p["extraversion"] + 0.1,
                       target=partner_pick["id"], dur=2))
        for b in awake[:4]:
            if w.age(b) < R.ADULT_AGE:
                continue
            deal = propose_trade(w, a, b)
            if deal:
                out.append(opt("trade", f"Mit {b['name']} tauschen ({deal['q_give']} {R.ITEM_LABEL.get(deal['give'], 'Münzen')} gegen "
                               f"{deal['q_get']} {R.ITEM_LABEL.get(deal['get'], 'Münzen')})", 0.35 + 0.6 * food_need + 0.2 * p["extraversion"],
                               target=b["id"], data=deal, dur=1))
                break
    for b in _nearby(w, a, 8):
        if w.age(b) < 1:
            continue
        need_other = b["needs"]["hunger"] > 0.6 and food_days(w, b) < 0.5
        if need_other and (a.get("inv") or {}).get("food", 0) >= 3 and fd > 2:
            aff = w.rel(a["id"], b["id"])["affection"]
            kin = 0.8 if b["id"] in a["children"] or b["id"] == a.get("partner") else 0
            out.append(opt("help", f"{b['name']} Nahrung geben", (1.4 * p["agreeableness"] + 0.4 * v["community"]) * b["needs"]["hunger"]
                           * (0.5 + aff) + kin, target=b["id"], dur=1))
            if w.rel(a["id"], b["id"])["trust"] > 0.55 and p["ambition"] > 0.5 and w.age(b) >= R.ADULT_AGE:
                out.append(opt("lend", f"{b['name']} Nahrung leihen", 0.4 * p["ambition"] + 0.4 * b["needs"]["hunger"], target=b["id"], dur=1))
            break
    for cid, c in w.contracts.items():
        if c["type"] == "kredit" and c["status"] == "aktiv" and c["borrower"] == a["id"]:
            if w.qty(("agent", a["id"]), c["item"]) >= c["amount"] + c["interest"] + (2 if c["item"] == "food" else 0):
                out.append(opt("repay", "Kredit zurückzahlen", 0.6 + 0.8 * p["conscientiousness"], target=cid, dur=1))
    _family_options(w, a, out, near, goals)

    # --- civic life
    for key, f in list(a["facts"].items()):
        if f["k"] == "proposal":
            prop = w.proposals.get(f.get("ref") or "")
            if prop and prop["status"] == "offen" and a["id"] not in prop["votes"] and \
                    a["id"] in {x["id"] for x in S.eligible_voters(w, prop)}:
                out.append(opt("vote", f"Abstimmen: {prop['title']}", 0.5 + 0.8 * S.civic_drive(a), target=prop["id"], dur=1))
                break
    if w.hour in range(9, 19) and (w.day + int(a["id"][1:])) % 3 == 0:
        for idea in S.proposal_ideas(w, a)[:3]:
            out.append(opt("propose", f"Vorschlagen: {idea['title']}", idea["weight"] * 1.4, data={"idea": idea}, dur=2))
    hall = next((b for b in w.buildings.values() if b["type"] in ("versammlungshalle", "markt") and b["region"] == region
                 and dist(b["x"], b["y"], a["x"], a["y"]) < 12), None)
    if hall and a.get("notices_day") != w.day:
        out.append(opt("notices", "Aushänge lesen", 0.2 + 0.5 * S.civic_drive(a), dest=(hall["x"], hall["y"]), target=hall["id"], dur=1))
    _institution_options(w, a, out, region, gov)
    if gov and a.get("satisfaction", 0.6) < 0.35 and p["conflict_avoidance"] < 0.45:
        out.append(opt("protest", f"Gegen {gov['name']} protestieren", (0.45 - a["satisfaction"]) * 2 + 0.3 * v["freedom"], target=gov["id"], dur=2))
    if gov and p["agreeableness"] + v["community"] > 1.2 and (a.get("inv") or {}).get("food", 0) > 12:
        out.append(opt("donate", f"An {gov['name']} spenden", 0.2 + 0.4 * v["community"], target=gov["id"], dur=1))

    # --- knowledge & culture
    _knowledge_options(w, a, out, home)

    # --- deviance (possible, never forced)
    _deviance_options(w, a, out, fd, gov)

    # --- World 3.0: social strategy, institutions at work, plans
    from . import social3
    out += social3.promise_options(w, a, opt)
    out += social3.alliance_options(w, a, opt)
    _social3_options(w, a, out, gov)
    _role_options(w, a, out, region)
    _plan_specific_options(w, a, out, home)
    from .cognition import apply_goal_bonus
    apply_goal_bonus(w, a, out)

    # daily intention (focus) tilts categories
    focus = (a.get("intention") or {}).get("focus")
    if focus:
        for o in out:
            if o["cat"] == focus:
                o["u"] = round(o["u"] + 0.3, 3)
    # cannot go into a region one is banned from
    return [o for o in out if not (o["dest"] and _banned_here(w, a, o["dest"][0], o["dest"][1]))]


def _season_factor(w: World) -> float:
    return [1.0, 1.2, 0.9, 0.15][w.season]


def _usable_farm(w: World, a: dict) -> dict | None:
    for b in w.buildings.values():
        if b["type"] != "bauernhof" or b["condition"] < 0.2:
            continue
        if b["owner"] in (a["id"], a.get("partner")) or (b["owner_kind"] == "inst" and b["region"] == w.home_region(a)):
            return b
    return None


def _usable_building(w: World, a: dict, btype: str) -> dict | None:
    best = None
    for b in w.buildings.values():
        if b["type"] != btype or b["condition"] < 0.2:
            continue
        if b["owner"] in (a["id"], a.get("partner")) or b["owner_kind"] == "inst":
            if best is None or dist(b["x"], b["y"], a["x"], a["y"]) < dist(best["x"], best["y"], a["x"], a["y"]):
                best = b
    return best


def _find_healer(w: World, a: dict) -> dict | None:
    for b in w.buildings.values():
        if b["type"] in ("heilhaus", "krankenhaus") and b["condition"] > 0.3 and dist(b["x"], b["y"], a["x"], a["y"]) < 20:
            return {"id": b["id"], "dest": (b["x"], b["y"])}
    cands = [h for h in w.living() if h["id"] != a["id"] and h["skills"]["healing"] > 0.3 and "kraeuterkunde" in h["techs"]
             and dist(h["x"], h["y"], a["x"], a["y"]) < 15]
    if cands:
        h = min(cands, key=lambda h: dist(h["x"], h["y"], a["x"], a["y"]))
        return {"id": h["id"], "dest": (h["x"], h["y"])}
    return None


def _building_options(w: World, a: dict, out: list, home: dict | None, plan: dict | None, need_mat: dict, goals: set) -> None:
    p, v = a["personality"], a["values"]
    if plan:
        if need_mat:
            have_any = any((a.get("inv") or {}).get(it, 0) > 0 for it in need_mat)
            if have_any:
                out.append(opt("deliver", "Baumaterial zur Baustelle bringen", 1.25, dest=(plan["x"], plan["y"]), target=plan["id"], dur=1))
        else:
            out.append(opt("build", f"Am {R.BUILDINGS[plan['type']]['label']} bauen", 1.05 + 0.3 * p["conscientiousness"]
                           + (0.3 if "haus" in goals and plan["type"] in R.SHELTER_TYPES else 0),
                           dest=(plan["x"], plan["y"]), target=plan["id"], dur=4))
        return
    cold = temperature(w, a["x"], a["y"]) < R.COLD_THRESHOLD_C + 4
    if not home:
        btype = "haus" if "holzbau" in a["techs"] and stock(w, a, "wood") >= 6 else "huette"
        u = 0.9 + (0.4 if "haus" in goals else 0) + 1.2 * a["exposure"] + (0.4 if cold else 0) + 0.2 * v["security"]
        out.append(opt("build_start", f"Eine {R.BUILDINGS[btype]['label']} bauen", u, data={"btype": btype}, dur=1))
    elif home["type"] == "huette" and "holzbau" in a["techs"] and (a.get("inv") or {}).get("wood", 0) >= 6:
        out.append(opt("build_start", "Ein richtiges Wohnhaus bauen", 0.35 + 0.3 * v["security"] + 0.2 * p["ambition"],
                       data={"btype": "steinhaus" if "steinbau" in a["techs"] else "haus"}, dur=1))
    owned = {b["type"] for b in w.buildings.values() if b.get("owner") == a["id"]}
    region = w.home_region(a)
    if home:
        if "ackerbau" in a["techs"] and "bauernhof" not in owned:
            out.append(opt("build_start", "Einen Bauernhof anlegen", 0.35 + 0.6 * a["skills"]["farming"] + 0.2 * v["wealth"],
                           data={"btype": "bauernhof"}, dur=1))
        if "werkzeugbau" in a["techs"] and "werkstatt" not in owned and p["ambition"] > 0.45:
            out.append(opt("build_start", "Eine Werkstatt bauen", 0.2 + 0.4 * a["skills"]["crafting"] + 0.2 * p["ambition"],
                           data={"btype": "werkstatt"}, dur=1))
        if not any(b["type"] == "markt" and b["region"] == region for b in w.buildings.values()) and a["stats"].get("trades", 0) >= 3:
            out.append(opt("build_start", "Einen Marktplatz anlegen", 0.25 + 0.3 * a["skills"]["trading"] + 0.2 * v["community"],
                           data={"btype": "markt"}, dur=1))
        if "lagerhaltung" in a["techs"] and "lagerhaus" not in owned and stock(w, a, "food") > 15:
            out.append(opt("build_start", "Ein Lagerhaus bauen", 0.35, data={"btype": "lagerhaus"}, dur=1))
        if "werkzeugbau" in a["techs"] and not w.near_water(home["x"], home["y"], 5) and "brunnen" not in owned:
            out.append(opt("build_start", "Einen Brunnen bauen", 0.5, data={"btype": "brunnen"}, dur=1))
        if "kraeuterkunde" in a["techs"] and a["skills"]["healing"] > 0.35 and "heilhaus" not in owned:
            out.append(opt("build_start", "Ein Heilhaus bauen", 0.25 + 0.3 * v["community"], data={"btype": "heilhaus"}, dur=1))
        if "schrift" in a["techs"] and p["curiosity"] > 0.6 and "bibliothek" not in owned:
            out.append(opt("build_start", "Eine Bibliothek/Forschungsstätte bauen", 0.15 + 0.3 * p["curiosity"], data={"btype": "bibliothek"}, dur=1))
        if home["condition"] < 0.6:
            out.append(opt("repair", "Das Zuhause reparieren", 0.9 * (1 - home["condition"]), dest=(home["x"], home["y"]), target=home["id"], dur=2))
    # help on community or friends' construction sites
    for s in w.sites.values():
        if dist(s["x"], s["y"], a["x"], a["y"]) > 12:
            continue
        friend = s["owner_kind"] == "agent" and s["owner"] != a["id"] and w.rel(a["id"], s["owner"])["affection"] > 0.6
        public = s["owner_kind"] == "inst"
        if not (friend or public):
            continue
        u = 0.25 + 0.5 * v["community"] * public + 0.4 * friend
        if missing_materials(s):
            if any((a.get("inv") or {}).get(it, 0) > 0 for it in missing_materials(s)):
                out.append(opt("deliver", f"Material für {R.BUILDINGS[s['type']]['label']} spenden", u, dest=(s["x"], s["y"]), target=s["id"], dur=1))
        else:
            out.append(opt("build", f"Beim Bau helfen ({R.BUILDINGS[s['type']]['label']})", u, dest=(s["x"], s["y"]), target=s["id"], dur=4))
        break


def _employer_options(w: World, a: dict, out: list) -> None:
    biz = [b for b in w.buildings.values() if b.get("owner") == a["id"] and b["type"] in ("bauernhof", "werkstatt")]
    if not biz or a["personality"]["ambition"] < 0.4 or a.get("hire_day") == w.day:
        return
    staff = sum(1 for c in w.contracts.values() if c["type"] == "arbeit" and c["status"] == "aktiv" and c["employer"] == a["id"])
    if staff >= 2 * len(biz):
        return
    wage = wage_offer(w, a)
    if not wage:
        return
    for b in _nearby(w, a, 5):
        if w.age(b) >= R.ADULT_AGE and not b.get("employer") and not any(x.get("owner") == b["id"] and x["type"] in ("bauernhof", "werkstatt")
                                                                       for x in w.buildings.values()):
            out.append(opt("hire", f"{b['name']} eine Arbeit anbieten ({wage[1]} {R.ITEM_LABEL.get(wage[0], 'Münzen')}/Tag)",
                           0.3 + 0.5 * a["personality"]["ambition"], target=b["id"], data={"building": biz[0]["id"], "wage": list(wage)}, dur=1))
            return


def _family_options(w: World, a: dict, out: list, near: list, goals: set) -> None:
    if w.age(a) < R.ADULT_AGE:
        return
    p, v = a["personality"], a["values"]
    if not a.get("partner"):
        for b in near:
            if b.get("partner") or w.age(b) < R.ADULT_AGE or b["id"] in a["parents"] or b["id"] in a["children"] or \
                    set(b["parents"]) & set(a["parents"]):
                continue
            r = w.rel(a["id"], b["id"])
            if r["affection"] > 0.68 and r["trust"] > 0.55 and r["familiarity"] > 0.3:
                out.append(opt("partner", f"{b['name']} eine Partnerschaft vorschlagen", 0.3 + r["affection"] * 0.6
                               + (0.4 if "familie" in goals else 0), target=b["id"], dur=1))
                break
    else:
        partner = w.agents.get(a["partner"])
        if partner and partner["alive"] and a.get("home") and not a.get("expecting") and not partner.get("expecting") and \
                w.age(a) <= 45 and w.age(partner) <= 45 and food_days(w, a) >= 3 and \
                not any(w.age(w.agents[c]) < 2 for c in a["children"] if c in w.agents and w.agents[c]["alive"]) and len(a["children"]) < 4:
            out.append(opt("child", "Mit " + partner["name"] + " über ein Kind sprechen",
                           0.15 + (0.45 if "familie" in goals else 0) + 0.2 * v["tradition"] - 0.3 * a["needs"]["stress"],
                           target=partner["id"], dur=1))


def _institution_options(w: World, a: dict, out: list, region: int, gov: dict | None) -> None:
    p, v = a["personality"], a["values"]
    for inst in w.institutions.values():
        if not inst["active"] or inst["region"] != region or inst["type"] in ("regierung", "unternehmen") or a["id"] in inst["members"]:
            continue
        if len(inst["members"]) >= 4:
            continue
        fit = {"gericht": 0.5 * v["fairness"] + 0.3 * a["skills"]["leadership"],
               "wache": 0.5 * v["security"] + 0.2 * (1 - p["conflict_avoidance"]),
               "schule": 0.6 * a["skills"]["teaching"] + 0.3 * ("schrift" in a["techs"]),
               "heilwesen": 0.6 * a["skills"]["healing"] + 0.2 * v["community"],
               "zeitung": 0.3 * p["curiosity"], "hilfsverein": 0.5 * v["community"]}.get(inst["type"], 0.1)
        if fit > 0.3 and f"inst:{inst['id']}" in a["facts"]:
            out.append(opt("join", f"{inst['name']} beitreten", fit, target=inst["id"], dur=1))
            break
    # founding private organisations (no vote needed); one per type and home region
    region = w.home_region(a)
    if "schrift" in a["techs"] and p["curiosity"] + p["extraversion"] > 1.2 and \
            not any(i["type"] == "zeitung" and i["region"] == region and i["active"] for i in w.institutions.values()) and w.day > 7:
        out.append(opt("join", "Eine Zeitung gründen", 0.2 + 0.2 * p["curiosity"], data={"found": "zeitung"}, dur=1))
    if v["community"] + p["agreeableness"] > 1.4 and \
            not any(i["type"] == "hilfsverein" and i["region"] == region and i["active"] for i in w.institutions.values()) and \
            S.recent_tags(w, a).get("hunger", 0) and w.day > 5:
        out.append(opt("join", "Einen Hilfsverein gründen", 0.25 + 0.3 * v["community"], data={"found": "hilfsverein"}, dur=1))


def _knowledge_options(w: World, a: dict, out: list, home: dict | None) -> None:
    p = a["personality"]
    research_cands = [t for t, spec in R.TECHS.items() if t not in a["techs"] and spec["cost"] > 0
                      and all(x in a["techs"] for x in spec["prereq"])]
    if research_cands:
        t = max(research_cands, key=lambda t: a["research"].get(t, 0) + w.rng.random())
        out.append(opt("research", f"Forschen: {R.TECHS[t]['label']}", 0.1 + 0.5 * p["curiosity"] + 0.4 * a["skills"]["research"]
                       + (0.25 if "wissen" in {g['type'] for g in a['goals']} else 0) - 0.5 * a["needs"]["hunger"],
                       data={"tech": t}, dur=8))
    for b in _nearby(w, a, 3):
        missing = [t for t in a["techs"] if t not in b["techs"] and all(x in b["techs"] for x in R.TECHS[t]["prereq"])]
        if missing and w.age(b) >= 6:
            out.append(opt("teach", f"{b['name']} {R.TECHS[missing[0]]['label']} beibringen", 0.15 + 0.4 * a["skills"]["teaching"]
                           + 0.3 * p["agreeableness"] + 0.2 * w.rel(a["id"], b["id"])["affection"], target=b["id"],
                           data={"tech": missing[0]}, dur=4))
            break
    if "schrift" in a["techs"]:
        lib = next((b for b in w.buildings.values() if b["type"] in ("bibliothek", "versammlungshalle", "schule")
                    and dist(b["x"], b["y"], a["x"], a["y"]) < 15), None) or home
        if lib:
            documented = {d["tech"] for d in w.documents.values() if d["building"] == lib["id"]}
            undoc = [t for t in a["techs"] if t not in documented and R.TECHS[t]["cost"] > 0]
            if undoc:
                out.append(opt("write", f"{R.TECHS[undoc[0]]['label']} aufschreiben", 0.15 + 0.3 * p["curiosity"] + 0.2 * p["conscientiousness"],
                               dest=(lib["x"], lib["y"]), target=lib["id"], data={"tech": undoc[0]}, dur=6))
            readable = [d for d in w.documents.values() if d["building"] == lib["id"] and d["tech"] not in a["techs"]
                        and all(x in a["techs"] for x in R.TECHS[d["tech"]]["prereq"])]
            if readable:
                out.append(opt("read", f"Lesen: {R.TECHS[readable[0]['tech']]['label']}", 0.2 + 0.5 * p["curiosity"],
                               dest=(lib["x"], lib["y"]), target=readable[0]["id"], dur=4))
    if a["skills"]["art"] > 0.2 or set(a["interests"]) & {"Musik", "Malerei", "Geschichten", "Philosophie"}:
        if a.get("art_day") != w.day:
            out.append(opt("art", "Ein Werk schaffen (Lied, Bild oder Geschichte)", 0.4 * a["skills"]["art"] + 0.2 * p["openness"]
                           - 0.6 * a["needs"]["hunger"] - 0.1, dur=6))
    if a["skills"]["healing"] > 0.25 and (stock(w, a, "herbs") > 0 or stock(w, a, "medicine") > 0):
        for b in _nearby(w, a, 4):
            if b.get("illness") and b["illness"]["severity"] > 0.15 and b["illness"].get("treated_until", -1) < w.tick:
                out.append(opt("heal", f"{b['name']} behandeln", 0.5 + 0.6 * a["skills"]["healing"] + 0.4 * p["agreeableness"],
                               target=b["id"], dur=3))
                break


def _deviance_options(w: World, a: dict, out: list, fd: float, gov: dict | None) -> None:
    p = a["personality"]
    desperate = clamp((a["needs"]["hunger"] - 0.5) * 2) * clamp(1 - fd)
    greed = a["values"]["wealth"] * (1 - p["agreeableness"]) * 0.35
    morals = a.get("morals") or {"ehrlichkeit": honesty(a), "autoritaet": 0.5}
    drive = (1.8 * desperate + greed) * (1 - 0.6 * p["self_control"]) * (1 - 0.5 * (0.5 * honesty(a) + 0.5 * morals["ehrlichkeit"]))
    if drive < 0.15:
        return
    region = w.region_of(a["x"], a["y"])
    law = S.active_law(w, region, "eigentumsschutz")
    fear = ((0.3 * p["conscientiousness"] + 0.4 * morals["autoritaet"]) if law and S.knows_law(w, a, law) else 0) + \
        (0.3 if S.institution_of(w, region, "wache") else 0) + (0.5 if (a.get("probation_until") or 0) > w.tick else 0) + \
        0.2 * (a.get("convictions", 0) > 0)
    targets = []
    for b in w.agents_near(a["x"], a["y"], 2):
        if b["id"] != a["id"] and (b.get("inv") or {}).get("food", 0) >= 2:
            targets.append(("agent", b, b["id"]))
    for bld in w.buildings.values():
        if dist(bld["x"], bld["y"], a["x"], a["y"]) <= 6 and bld.get("owner") not in (a["id"], a.get("partner")) and \
                (bld.get("inv") or {}).get("food", 0) >= 2:
            targets.append(("building", bld, bld.get("owner")))
    if not targets:
        return
    kind, t, owner = min(targets, key=lambda z: w.rel(a["id"], z[2])["affection"] if z[2] in w.agents else 0.3)
    witnesses = sum(1 for x in w.agents_near(t["x"], t["y"], 3) if x["id"] not in (a["id"], owner) and not x.get("asleep"))
    guilt = 0.6 * w.rel(a["id"], owner)["affection"] if owner in w.agents else 0.1
    u = drive - fear - 0.25 * witnesses - guilt
    name = t["name"] if kind == "agent" else f"Vorrat ({R.BUILDINGS[t['type']]['label']})"
    out.append(opt("steal", f"Nahrung von {name} nehmen", u, dest=(t["x"], t["y"]) if kind == "building" else None,
                   target=t["id"], data={"kind": kind}, dur=1))
    if gov and a["id"] in gov.get("leaders", []) and (gov.get("inv") or {}).get("food", 0) > 5:
        out.append(opt("embezzle", "Aus der Gemeinschaftskasse nehmen", greed * 2 - 0.4 * p["conscientiousness"], target=gov["id"], dur=1))


def _child_options(w: World, a: dict) -> list[dict]:
    n = a["needs"]
    out = [opt("rest", "Spielen und ausruhen", 0.4, dur=3)]
    home = _home(w, a)
    if w.is_night() or n["energy"] < 0.3:
        out.append(opt("sleep", "Schlafen", 2.5, dest=(home["x"], home["y"]) if home else None, dur=2))
    water = find_water(w, a)
    if water and n["thirst"] > 0.3:
        out.append(opt("drink", "Trinken", 3.0 * n["thirst"], dest=water, dur=1))
    parent = next((w.agents[p] for p in a["parents"] if p in w.agents and w.agents[p]["alive"]), None)
    if parent and dist(parent["x"], parent["y"], a["x"], a["y"]) > 4 and not w.is_night():
        out.append(opt("follow", f"Zu {parent['name']} gehen", 0.6, dest=(parent["x"], parent["y"]), dur=1))
    if home and dist(home["x"], home["y"], a["x"], a["y"]) > 2 and w.age(a) < 6:
        out.append(opt("follow", "Nach Hause gehen", 0.8, dest=(home["x"], home["y"]), dur=1))
    near = [b for b in _nearby(w, a, 3) if not b.get("asleep")]
    if near:
        out.append(opt("talk", f"Mit {near[0]['name']} spielen", 0.5 + n["social"], target=near[0]["id"], dur=2))
    if w.age(a) >= 6 and S.school_available(w, a) and 8 <= w.hour < 13:
        sch = next((b for b in w.buildings.values() if b["type"] == "schule" and b["region"] == w.home_region(a)), None)
        if sch:
            out.append(opt("school", "Zur Schule gehen", 1.2, dest=(sch["x"], sch["y"]), target=sch["id"], dur=8))
    return out


# ------------------------------------------------------------------ choosing (rule-based policy)
def choose(w: World, a: dict, options: list[dict]) -> dict:
    """Softmax choice: higher utility is likelier, but impulsive/less conscientious people deviate more.
    This produces imperfect, personality-dependent decisions without scripted 'mistakes'."""
    temp = 0.22 + 0.35 * (1 - a["personality"]["conscientiousness"]) + 0.1 * a["needs"]["stress"]
    m = max(o["u"] for o in options)
    weights = [math.exp((o["u"] - m) / temp) for o in options]
    return w.rng.choices(options, weights)[0]


# ------------------------------------------------------------------ execution
def start(w: World, a: dict, o: dict, decision: dict | None = None) -> None:
    act = {"type": o["type"], "label": o["label"], "target": o["target"], "data": o["data"], "dur": o["dur"],
           "remaining": o["dur"], "dest": o["dest"], "phase": "travel" if o["dest"] else "do", "started": w.tick,
           "decision": decision["id"] if decision else None}
    if o["dest"] and (a["x"], a["y"]) != tuple(o["dest"]):
        path = find_path(w, (a["x"], a["y"]), (o["dest"][0], o["dest"][1]))
        if path is None:
            act = {"type": "rest", "label": "Weg versperrt – ausruhen", "target": None, "data": {}, "dur": 1, "remaining": 1,
                   "dest": None, "phase": "do", "started": w.tick, "decision": None}
            a["known"]["res"] = {k: [p for p in v if p != o["dest"]] for k, v in a["known"]["res"].items()}
        else:
            a["path"] = path
    else:
        act["phase"] = "do"
    a["action"] = act
    if o["type"] == "sleep":
        a["asleep"] = act["phase"] == "do"


def tick_action(w: World, a: dict) -> None:
    from .perception import move_along
    act = a["action"]
    if act["phase"] == "travel":
        arrived = move_along(w, a, 2.0)
        if w.tick % 4 == 0:
            perceive(w, a)
        if arrived:
            act["phase"] = "do"
            if act["type"] == "sleep":
                a["asleep"] = True
        elif not a["path"]:
            a["action"] = None  # blocked
        return
    if act["type"] == "sleep":
        if a["needs"]["energy"] >= 0.97 or (not w.is_night() and a["needs"]["energy"] > 0.6):
            a["asleep"] = False
            a["action"] = None
        return
    act["remaining"] -= 1
    if act["remaining"] <= 0:
        try:
            complete(w, a, act)
        finally:
            if a.get("action") is act:
                a["action"] = None


def complete(w: World, a: dict, act: dict) -> None:
    fn = COMPLETE.get(act["type"])
    if fn:
        fn(w, a, act)


def _gain(w: World, a: dict, res: str, item: str, skill: str, base: float, act: dict) -> int:
    x, y = a["x"], a["y"]
    # find the resource tile at/next to the agent
    tile = None
    for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if w.in_bounds(nx, ny) and w.map[res][ny, nx] > 0:
            tile = (nx, ny)
            break
    if tile is None:
        return 0
    eff = efficiency(w, a, skill)
    want = max(1, int(round(base * eff + w.rng.random() * 0.8)))
    avail = int(w.map[res][tile[1], tile[0]])
    n = min(want, avail)
    w.map[res][tile[1], tile[0]] = avail - n
    w.produce(("agent", a["id"]), item, n, f"natur:{res}@{tile[0]},{tile[1]}")
    a["skills"][skill] = round(min(1.0, a["skills"][skill] + 0.003), 4)
    a["stats"][f"gathered:{res}"] = a["stats"].get(f"gathered:{res}", 0) + n
    if w.map[res][tile[1], tile[0]] == 0:
        w.remember(a, "beobachtung", f"Die Stelle bei ({tile[0]},{tile[1]}) gibt kein {R.ITEM_LABEL.get(item, item)} mehr her.", 3,
                   tags=["erschoepft", f"erschoepft_{res}"])
        if res == "wood":
            from .mapgen import T
            w.map["terrain"][tile[1], tile[0]] = T["clearing"]
            w.map["clearing_age"][tile[1], tile[0]] = 0
            w.map["fertility"][tile[1], tile[0]] = max(float(w.map["fertility"][tile[1], tile[0]]), 0.6)
            w.daily["deforested"] += 1
            w.config["map_version"] = w.config.get("map_version", 0) + 1
    if act["data"].get("forbidden"):
        _violation_resource(w, a, res)
    _accident(w, a, {"wood": "chop", "stone": "quarry"}.get(res))
    return n


def _violation_resource(w: World, a: dict, res: str) -> None:
    region = w.region_of(a["x"], a["y"])
    law = S.active_law(w, region, "ressourcenschutz")
    eid = w.emit("justiz", "regelverstoss", f"{a['name']} sammelt trotz Ressourcenschutz ({R.ITEM_LABEL.get(res, res)}).",
                 actors=[a["id"]], x=a["x"], y=a["y"], public=False, witnesses=False, data={"offender": a["id"], "law": law["id"] if law else None})
    for wt in w.agents_near(a["x"], a["y"], 3):
        if wt["id"] != a["id"] and not wt.get("asleep") and law and S.knows_law(w, wt, law):
            w.learn(wt, f"ev:{eid}", "claim", f"{a['name']} hat gegen den Ressourcenschutz verstoßen.", "beobachtet", 1.0, ref=eid)
            if wt["values"]["security"] + wt["values"]["tradition"] > 1.1 and S.government_of(w, region):
                S.open_case(w, "regelverstoss", accuser=wt, accused=a, event=eid, evidence=[wt["id"]])
            break


def _accident(w: World, a: dict, kind: str | None) -> None:
    if not kind:
        return
    risk = R.ACCIDENT_RISK[kind] * (0.5 if (a.get("inv") or {}).get("tools") else 1.0) * (1.5 - a["needs"]["energy"])
    if w.chance(risk):
        harm = round(w.rng.uniform(0.1, 0.4), 3)
        a["health"] = clamp(a["health"] - harm)
        a["last_injury"] = "Arbeitsunfall"
        eid = w.emit("leben", "unfall", f"{a['name']} hatte einen Arbeitsunfall und ist verletzt.", actors=[a["id"]], x=a["x"], y=a["y"],
                     data={"harm": harm})
        w.remember(a, "gesundheit", "Ich hatte einen Unfall bei der Arbeit.", 7, event=eid, tags=["unfall"])
        if a["health"] <= 0:
            from .life import kill
            kill(w, a, "Arbeitsunfall", cause_event=eid)


def _c_eat(w, a, act):
    src = ("agent", a["id"]) if (a.get("inv") or {}).get("food", 0) > 0 else None
    home = _home(w, a)
    if src is None and home and (home.get("inv") or {}).get("food", 0) > 0 and (a["x"], a["y"]) == (home["x"], home["y"]):
        src = ("building", home["id"])
    if src:
        w.consume(src, "food", 1, "essen")
        a["needs"]["hunger"] = clamp(a["needs"]["hunger"] - R.MEAL_RELIEF)


def _c_drink(w, a, act):
    if w.near_water(a["x"], a["y"], 1) or a.get("prison"):
        a["needs"]["thirst"] = 0.0


def _c_rest(w, a, act):
    a["needs"]["stress"] = clamp(a["needs"]["stress"] - 0.04)
    a["needs"]["energy"] = clamp(a["needs"]["energy"] + 0.03)


def _c_forage(w, a, act):
    _gain(w, a, act["data"].get("res", "forage"), "food", "gathering", 2.2, act)


def _c_chop(w, a, act):
    _gain(w, a, "wood", "wood", "woodcutting", 2.0, act)


def _c_quarry(w, a, act):
    _gain(w, a, "stone", "stone", "masonry", 1.8, act)


def _c_herbs(w, a, act):
    _gain(w, a, "herbs", "herbs", "healing", 1.5, act)


def _c_farm(w, a, act):
    b = w.buildings.get(act["target"])
    if not b:
        return
    fert = float(w.map["fertility"][b["y"], b["x"]]) or 0.5
    drought = w.weather.get(str(b["region"]), {}).get("drought")
    irrig = 1.3 if "bewaesserung" in a["techs"] else 1.0
    flooded = w.map["flooded"][b["y"], b["x"]]
    n = int(round(3.5 * efficiency(w, a, "farming") * fert * _season_factor(w) * irrig * (0.5 if drought and irrig == 1 else 1)
                  * (0 if flooded else 1) + w.rng.random() * 0.6))
    if n > 0:
        if b["owner_kind"] == "inst":
            w.produce(("inst", b["owner"]), "food", n, f"ernte:{b['id']}")
        else:
            w.produce(("agent", a["id"]), "food", n, f"ernte:{b['id']}")
    a["skills"]["farming"] = round(min(1.0, a["skills"]["farming"] + 0.004), 4)
    w.map["fertility"][b["y"], b["x"]] = max(0.2, float(w.map["fertility"][b["y"], b["x"]]) - 0.001)


def _c_craft(w, a, act):
    for it in ("wood", "stone"):
        if w.qty(("agent", a["id"]), it) < 1:
            home = _home(w, a)
            if home and w.qty(("building", home["id"]), it) >= 1:
                w.transfer(("building", home["id"]), ("agent", a["id"]), it, 1)
            else:
                return
    w.consume(("agent", a["id"]), "wood", 1, "handwerk")
    w.consume(("agent", a["id"]), "stone", 1, "handwerk")
    w.produce(("agent", a["id"]), "tools", 1, "handwerk:werkzeug")
    a["skills"]["crafting"] = round(min(1.0, a["skills"]["crafting"] + 0.006), 4)


def _c_medicine(w, a, act):
    if w.qty(("agent", a["id"]), "herbs") >= 2:
        w.consume(("agent", a["id"]), "herbs", 2, "heilmittel")
        w.produce(("agent", a["id"]), "medicine", 1, "heilmittel")


def _c_build_start(w, a, act):
    btype = act["data"]["btype"]
    spec = R.BUILDINGS[btype]
    if spec["tech"] and spec["tech"] not in a["techs"]:
        return
    far = bool(act["data"].get("far"))
    plot = choose_plot(w, a, btype, near=(a["x"], a["y"]) if far else None)
    if not plot:
        w.remember(a, "beobachtung", f"Ich fand keinen geeigneten Platz für {spec['label']}.", 3)
        return
    site = start_site(w, btype, plot[0], plot[1], owner=a["id"], by=a["id"], cause=act.get("decision_event"))
    if far and btype in R.SHELTER_TYPES:
        site["relocate"] = True
    a["building_plan"] = site["id"]
    deliver(w, a, site) if (a["x"], a["y"]) == plot else None


def _c_deliver(w, a, act):
    s = w.sites.get(act["target"])
    if s:
        n = deliver(w, a, s)
        if n and s["owner"] != a["id"]:
            owner = w.agents.get(s["owner"])
            if owner:
                w.adjust_rel(owner["id"], a["id"], trust=0.05, affection=0.05, note="beim Bau geholfen")


def _c_build(w, a, act):
    s = w.sites.get(act["target"])
    if not s:
        if a.get("building_plan") == act["target"]:
            a["building_plan"] = None
        return
    b = work_on(w, a, s, act["dur"] / R.TICKS_PER_HOUR, efficiency(w, a, "building"))
    _accident(w, a, "build")
    if b:
        for x in w.agents.values():
            if x.get("building_plan") == s["id"]:
                x["building_plan"] = None
        if b["owner_kind"] == "agent" and b["owner"] != a["id"] and b["owner"] in w.agents:
            w.adjust_rel(b["owner"], a["id"], trust=0.06, affection=0.06, note="beim Bau geholfen")


def _c_repair(w, a, act):
    b = w.buildings.get(act["target"])
    if b:
        repair(w, a, b)


def _c_talk(w, a, act):
    b = w.agents.get(act["target"])
    if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        S.converse(w, a, b)


def _c_trade(w, a, act):
    b = w.agents.get(act["target"])
    if not b or not b["alive"] or dist(a["x"], a["y"], b["x"], b["y"]) > 4:
        return
    deal = propose_trade(w, a, b)  # re-evaluated at execution time: the partner must still agree
    if deal:
        execute_trade(w, a, b, deal)


def _c_help(w, a, act):
    b = w.agents.get(act["target"])
    if b and b["alive"]:
        give(w, a, b, "food", 2)


def _c_lend(w, a, act):
    b = w.agents.get(act["target"])
    if b and b["alive"] and w.qty(("agent", a["id"]), "food") >= 4:
        lend(w, a, b, "food", 3)


def _c_repay(w, a, act):
    c = w.contracts.get(act["target"])
    if c and c["status"] == "aktiv":
        repay(w, a, c)


def _c_vote(w, a, act):
    prop = w.proposals.get(act["target"])
    if prop and prop["status"] == "offen":
        S.cast_vote(w, a, prop)


def _c_propose(w, a, act):
    idea = act["data"]["idea"]
    S.make_proposal(w, a, idea, title=act["data"].get("title"), text=act["data"].get("text"),
                    decided_by=act["data"].get("decided_by", "regeln"))


def _c_notices(w, a, act):
    S.read_notices(w, a)
    a["notices_day"] = w.day


def _c_join(w, a, act):
    found = act["data"].get("found")
    region = w.home_region(a)
    if found and any(i["type"] == found and i["region"] == region and i["active"] for i in w.institutions.values()):
        return  # someone else was faster
    if found:
        iid = w.new_id("I")
        name = f"{R.PRIVATE_ORGS[found]} von {a['name']}"
        w.institutions[iid] = {"id": iid, "type": found, "name": name, "region": region, "founded": w.tick, "founder": a["id"],
                               "members": [a["id"]], "leaders": [a["id"]], "active": True, "inv": {}}
        w.emit("wissen" if found == "zeitung" else "sozial", "gruendung", f"{a['name']} gründet: {name}.", actors=[a["id"]],
               x=a["x"], y=a["y"], data={"inst": iid})
        a["bio"].append([w.tick, f"{name} gegründet."])
        if w.mind is not None:
            w.mind.request_naming(w, a["id"], "institution", iid)
        return
    inst = w.institutions.get(act["target"])
    if inst and inst["active"] and a["id"] not in inst["members"]:
        inst["members"].append(a["id"])
        w.emit("politik", "beitritt", f"{a['name']} wirkt jetzt in {inst['name']} mit.", actors=[a["id"]], x=a["x"], y=a["y"],
               data={"inst": inst["id"]})
        a["bio"].append([w.tick, f"Mitglied in {inst['name']}."])


def _c_protest(w, a, act):
    gov = w.institutions.get(act["target"])
    if gov and gov["active"]:
        gov["protests"] = gov.get("protests", 0) + 1
        eid = w.emit("politik", "protest", f"{a['name']} protestiert öffentlich gegen {gov['name']}.", actors=[a["id"]],
                     x=a["x"], y=a["y"], data={"inst": gov["id"]})
        for l in gov["leaders"]:
            if l in w.agents:
                w.adjust_rel(l, a["id"], affection=-0.04)
        w.remember(a, "politik", f"Ich habe gegen {gov['name']} protestiert.", 5, event=eid, tags=["protest"])


def _c_donate(w, a, act):
    gov = w.institutions.get(act["target"])
    if gov and gov["active"]:
        S.donate(w, a, gov, "food", 3)


def _c_research(w, a, act):
    t = act["data"]["tech"]
    if t in a["techs"]:
        return
    a["research"][t] = a["research"].get(t, 0) + (act["dur"] / R.TICKS_PER_HOUR) * efficiency(w, a, "research") * 2
    a["skills"]["research"] = round(min(1.0, a["skills"]["research"] + 0.006), 4)
    if a["research"][t] >= R.TECHS[t]["cost"]:
        a["techs"] = sorted(set(a["techs"] + [t]))
        a["research"].pop(t, None)
        first = not any(t in x["techs"] for x in w.agents.values() if x["id"] != a["id"])
        eid = w.emit("wissen", "entdeckung", f"{a['name']} hat {R.TECHS[t]['label']} {'erstmals entdeckt' if first else 'selbst erarbeitet'}.",
                     actors=[a["id"]], x=a["x"], y=a["y"], data={"tech": t, "first": first})
        a["bio"].append([w.tick, f"{R.TECHS[t]['label']} erforscht."])
        w.remember(a, "biografie", f"Ich habe {R.TECHS[t]['label']} verstanden.", 8, event=eid, tags=["wissen"])
        w.totals["discoveries"] += 1


def _c_teach(w, a, act):
    b = w.agents.get(act["target"])
    t = act["data"]["tech"]
    if b and b["alive"] and t not in b["techs"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        b["research"][t] = b["research"].get(t, 0) + 6 * (0.5 + a["skills"]["teaching"])
        a["skills"]["teaching"] = round(min(1.0, a["skills"]["teaching"] + 0.008), 4)
        if b["research"][t] >= R.TECHS[t]["cost"] * 0.5:
            b["techs"] = sorted(set(b["techs"] + [t]))
            b["research"].pop(t, None)
            w.emit("wissen", "gelernt", f"{b['name']} hat von {a['name']} {R.TECHS[t]['label']} gelernt.", actors=[a["id"], b["id"]],
                   x=a["x"], y=a["y"], data={"tech": t})
        w.adjust_rel(b["id"], a["id"], respect=0.05, affection=0.03, familiarity=0.04)


def _c_write(w, a, act):
    t = act["data"]["tech"]
    lib = w.buildings.get(act["target"])
    if not lib or t not in a["techs"]:
        return
    did = w.new_id("D")
    w.documents[did] = {"id": did, "tech": t, "author": a["id"], "building": lib["id"], "tick": w.tick,
                        "title": f"Über {R.TECHS[t]['label']}"}
    w.emit("wissen", "dokument", f"{a['name']} hat das Wissen über {R.TECHS[t]['label']} aufgeschrieben ({R.BUILDINGS[lib['type']]['label']}).",
           actors=[a["id"]], x=a["x"], y=a["y"], data={"document": did})


def _c_read(w, a, act):
    d = w.documents.get(act["target"])
    if not d or d["tech"] in a["techs"]:
        return
    a["research"][d["tech"]] = a["research"].get(d["tech"], 0) + 8 * efficiency(w, a, "research")
    if a["research"][d["tech"]] >= R.TECHS[d["tech"]]["cost"] * 0.5:
        a["techs"] = sorted(set(a["techs"] + [d["tech"]]))
        a["research"].pop(d["tech"], None)
        w.emit("wissen", "gelernt", f"{a['name']} hat aus einer Schrift {R.TECHS[d['tech']]['label']} gelernt.", actors=[a["id"]],
               x=a["x"], y=a["y"], data={"tech": d["tech"], "document": d["id"]})


def _c_art(w, a, act):
    a["art_day"] = w.day
    kinds = [k for k, i in (("Lied", "Musik"), ("Bild", "Malerei"), ("Geschichte", "Geschichten"), ("Gedanke", "Philosophie"))
             if i in a["interests"]] or ["Lied"]
    kind = w.rng.choice(kinds)
    aid = w.new_id("W")
    w.artworks[aid] = {"id": aid, "author": a["id"], "kind": kind, "title": f"{kind} Nr. {w.counters['W']} von {a['name']}",
                       "text": None, "tick": w.tick, "titled_by": "regeln"}
    a["skills"]["art"] = round(min(1.0, a["skills"]["art"] + 0.01), 4)
    a["needs"]["stress"] = clamp(a["needs"]["stress"] - 0.06)
    w.emit("wissen", "kunstwerk", f"{a['name']} hat ein neues Werk geschaffen ({kind}).", actors=[a["id"]], x=a["x"], y=a["y"],
           data={"artwork": aid})
    if w.mind is not None:
        w.mind.request_naming(w, a["id"], "kunstwerk", aid)


def _c_heal(w, a, act):
    b = w.agents.get(act["target"])
    if not b or not b["alive"] or not b.get("illness"):
        return
    used = None
    for it in ("medicine", "herbs"):
        if w.qty(("agent", a["id"]), it) > 0:
            w.consume(("agent", a["id"]), it, 1, f"behandlung:{b['id']}")
            used = it
            break
    if not used:
        return
    boost = 0.25 if used == "medicine" else 0.12
    b["illness"]["severity"] = round(clamp(b["illness"]["severity"] - boost * (0.6 + a["skills"]["healing"])), 3)
    b["illness"]["treated_until"] = w.tick + 2 * R.TICKS_PER_DAY
    a["skills"]["healing"] = round(min(1.0, a["skills"]["healing"] + 0.01), 4)
    w.adjust_rel(b["id"], a["id"], trust=0.08, affection=0.06, respect=0.05, note="behandelt")
    eid = w.emit("leben", "behandlung", f"{a['name']} behandelt {b['name']} ({b['illness']['name']}).", actors=[a["id"], b["id"]],
                 x=a["x"], y=a["y"])
    law = S.active_law(w, w.home_region(a), "gesundheitsversorgung")
    gov = S.government_of(w, w.home_region(a))
    if law and gov and w.qty(("inst", gov["id"]), "food") > 0:
        w.transfer(("inst", gov["id"]), ("agent", a["id"]), "food", 1)
    w.remember(b, "gesundheit", f"{a['name']} hat mich behandelt.", 5, event=eid, subjects=[a["id"]])


def _c_seek_care(w, a, act):
    t = act["target"]
    healer = w.agents.get(t)
    if healer and healer["alive"] and a.get("illness"):
        healer.setdefault("patients", []).append(a["id"])
    b = w.buildings.get(t)
    if b and a.get("illness"):
        staff = [h for h in w.agents_near(b["x"], b["y"], 2) if h["skills"]["healing"] > 0.25 and h["id"] != a["id"]]
        if staff:
            _c_heal(w, staff[0], {"target": a["id"]})


def _c_work(w, a, act):
    c = w.contracts.get(act["target"])
    if not c or c["status"] != "aktiv":
        return
    b = w.buildings.get(c["building"])
    if not b:
        end_contract(w, c, "beendet")
        return
    eff = efficiency(w, a, "farming" if b["type"] == "bauernhof" else "crafting")
    if b["type"] == "bauernhof":
        fert = float(w.map["fertility"][b["y"], b["x"]]) or 0.5
        n = int(round(3.5 * eff * fert * _season_factor(w) + w.rng.random() * 0.6))
        if n:
            w.produce(("building", b["id"]), "food", n, f"ernte:{b['id']}")
    else:
        if w.qty(("building", b["id"]), "wood") >= 1 and w.qty(("building", b["id"]), "stone") >= 1:
            w.consume(("building", b["id"]), "wood", 1, "handwerk")
            w.consume(("building", b["id"]), "stone", 1, "handwerk")
            w.produce(("building", b["id"]), "tools", 1, "handwerk:werkzeug")
    c["worked_today"] = True
    c["days_worked"] = c.get("days_worked", 0) + 1


def _c_hire(w, a, act):
    a["hire_day"] = w.day
    b = w.agents.get(act["target"])
    bld = w.buildings.get(act["data"]["building"])
    if not b or not b["alive"] or not bld or b.get("employer"):
        return
    wage = tuple(act["data"]["wage"])
    # the worker decides: need, trust in the employer, own alternatives
    reservation = 1.5 + 1.5 * food_days(w, b) / 4 + 0.5 * b["values"]["freedom"]
    wage_value = wage[1] * valuation(w, b, wage[0]) if not wage[0].startswith("coin") else wage[1] * valuation(w, b, wage[0])
    accept = wage_value >= reservation and w.rel(b["id"], a["id"])["trust"] > 0.35
    if accept:
        hire(w, a, b, bld, wage)
    else:
        w.emit("wirtschaft", "angebot_abgelehnt", f"{b['name']} lehnt das Arbeitsangebot von {a['name']} ab.",
               actors=[a["id"], b["id"]], x=a["x"], y=a["y"])


def _c_partner(w, a, act):
    b = w.agents.get(act["target"])
    if not b or not b["alive"] or b.get("partner") or a.get("partner"):
        return
    r = w.rel(b["id"], a["id"])
    if r["affection"] > 0.6 and r["trust"] > 0.5 and w.rng.random() < 0.4 + r["affection"] * 0.5:
        S.form_partnership(w, a, b)
    else:
        w.adjust_rel(a["id"], b["id"], affection=-0.03)
        w.remember(a, "sozial", f"{b['name']} wollte keine Partnerschaft.", 5, subjects=[b["id"]])


def _c_child(w, a, act):
    b = w.agents.get(act["target"])
    if not b or not b["alive"] or b.get("partner") != a["id"]:
        return
    goals_b = {g["type"] for g in b["goals"]}
    u_b = 0.2 + (0.4 if "familie" in goals_b else 0) + 0.2 * b["values"]["tradition"] - 0.3 * b["needs"]["stress"] \
        + 0.2 * w.rel(b["id"], a["id"])["affection"]
    if u_b > 0.35 + w.rng.random() * 0.3:
        carrier = a if w.rng.random() < 0.5 else b
        carrier["expecting"] = {"due": w.tick + R.DAYS_PER_SEASON * R.TICKS_PER_DAY, "partner": (b if carrier is a else a)["id"]}
        w.emit("leben", "nachwuchs_erwartet", f"{a['name']} und {b['name']} erwarten ein Kind.", actors=[a["id"], b["id"]],
               x=a["x"], y=a["y"])
    else:
        w.remember(a, "sozial", f"{b['name']} möchte gerade kein Kind.", 4, subjects=[b["id"]])


def _c_steal(w, a, act):
    kind = act["data"]["kind"]
    if kind == "agent":
        b = w.agents.get(act["target"])
        if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 2:
            S.steal(w, a, b, None, "food", 2)
    else:
        bld = w.buildings.get(act["target"])
        if bld and dist(a["x"], a["y"], bld["x"], bld["y"]) <= 1:
            S.steal(w, a, None, bld, "food", 2)


def _c_embezzle(w, a, act):
    gov = w.institutions.get(act["target"])
    if not gov or a["id"] not in gov.get("leaders", []):
        return
    n = min(4, w.qty(("inst", gov["id"]), "food"))
    if n <= 0:
        return
    w.transfer(("inst", gov["id"]), ("agent", a["id"]), "food", n)
    eid = w.emit("justiz", "veruntreuung", f"{a['name']} hat {n} Nahrung aus der Kasse von {gov['name']} genommen.", actors=[a["id"]],
                 x=a["x"], y=a["y"], public=False, witnesses=False, data={"offender": a["id"], "item": "food", "n": n, "inst": gov["id"]})
    a["stats"]["embezzled"] = a["stats"].get("embezzled", 0) + n
    # audits only exist if residents created a press or court
    region = gov["region"]
    auditor = S.institution_of(w, region, "zeitung") or S.institution_of(w, region, "gericht")
    if auditor and w.chance(0.25) and auditor["members"]:
        member = w.agents.get(auditor["members"][0])
        if member and member["alive"] and member["id"] != a["id"]:
            w.learn(member, f"ev:{eid}", "claim", f"{a['name']} hat aus der Gemeinschaftskasse genommen.", "beobachtet", 1.0, ref=eid)
            S.open_case(w, "machtmissbrauch", accuser=member, accused=a, event=eid, evidence=[member["id"]])


def _c_leave(w, a, act):
    region = w.region_of(a["x"], a["y"])
    # walk to the nearest tile of another region
    best = None
    for r in range(1, 30):
        for dx in (-r, r):
            for dy in range(-r, r + 1):
                for nx, ny in ((a["x"] + dx, a["y"] + dy), (a["x"] + dy, a["y"] + dx)):
                    if w.in_bounds(nx, ny) and w.passable(nx, ny) and w.region_of(nx, ny) != region and \
                            not _banned_here(w, a, nx, ny):
                        best = (nx, ny)
                        break
                if best:
                    break
            if best:
                break
        if best:
            break
    if best:
        path = find_path(w, (a["x"], a["y"]), best)
        if path:
            a["path"] = path
            a["action"] = {"type": "travel", "label": "Verlässt die Region", "target": None, "data": {}, "dur": 1, "remaining": 1,
                           "dest": list(best), "phase": "travel", "started": w.tick, "decision": None}


def _c_school(w, a, act):
    a["needs"]["social"] = clamp(a["needs"]["social"] - 0.2)


def _c_noop(w, a, act):
    return


COMPLETE = {"eat": _c_eat, "drink": _c_drink, "rest": _c_rest, "forage": _c_forage, "fish": _c_forage, "chop": _c_chop,
            "quarry": _c_quarry, "herbs": _c_herbs, "farm": _c_farm, "craft": _c_craft, "medicine": _c_medicine,
            "build_start": _c_build_start, "deliver": _c_deliver, "build": _c_build, "repair": _c_repair, "talk": _c_talk,
            "trade": _c_trade, "help": _c_help, "lend": _c_lend, "repay": _c_repay, "vote": _c_vote, "propose": _c_propose,
            "notices": _c_notices, "join": _c_join, "protest": _c_protest, "donate": _c_donate, "research": _c_research,
            "teach": _c_teach, "write": _c_write, "read": _c_read, "art": _c_art, "heal": _c_heal, "seek_care": _c_seek_care,
            "work": _c_work, "hire": _c_hire, "partner": _c_partner, "child": _c_child, "steal": _c_steal,
            "embezzle": _c_embezzle, "leave": _c_leave, "school": _c_school, "follow": _c_noop, "play": _c_noop,
            "travel": _c_noop, "think": _c_noop}



# ------------------------------------------------------------------ World 3.0 options
def _prison_options(w: World, a: dict, base: list[dict]) -> list[dict]:
    out = [o for o in base if o["type"] in ("eat", "sleep", "rest")]
    if a["needs"]["thirst"] > 0.2:
        out.append(opt("drink", "Wasser in der Zelle", 3.6 * a["needs"]["thirst"] ** 1.6, dur=1))
    for b in _nearby(w, a, 1):
        if not b.get("asleep"):
            out.append(opt("talk", f"Mit {b['name']} reden", 1.2 * a["needs"]["social"] + 0.2, target=b["id"], dur=2))
            break
    out.append(opt("rest", "In der Zelle warten", 0.3, dur=4))
    from .cognition import apply_goal_bonus
    apply_goal_bonus(w, a, out)
    return out


def _social3_options(w: World, a: dict, out: list, gov: dict | None) -> None:
    from . import justice
    from .cognition import honesty_estimate
    p = a["personality"]
    near = [b for b in _nearby(w, a, 3) if not b.get("asleep") and w.age(b) >= R.ADULT_AGE]
    targets = a.get("emo_targets", {})
    # candidacy in an open election
    for prop in w.proposals.values():
        if prop["status"] == "offen" and prop["kind"] == "wahl" and a["id"] not in prop["candidates"] and \
                prop["region"] == w.home_region(a) and f"prop:{prop['id']}" in a["facts"]:
            wants = any(g["type"] == "amt" and g["status"] == "aktiv" for g in a["agenda"])
            out.append(opt("candidate", f"Bei der Wahl kandidieren ({prop['title']})", 0.2 + 0.5 * p["ambition"] + 0.5 * wants,
                           target=prop["id"], dur=1))
            break
    # persuading someone about an open proposal I care about
    if near:
        for prop in w.proposals.values():
            if prop["status"] != "offen" or prop["kind"] == "wahl" or prop["region"] != w.home_region(a):
                continue
            mine = prop["proposer"] == a["id"] or prop["votes"].get(a["id"]) == "ja"
            if not mine:
                continue
            for b in near:
                if b["id"] not in prop["votes"] and b["id"] in {x["id"] for x in S.eligible_voters(w, prop)}:
                    out.append(opt("persuade", f"{b['name']} von „{prop['title']}“ überzeugen", 0.25 + 0.4 * a["skills"]["leadership"]
                                   + 0.3 * p["extraversion"], target=b["id"], data={"proposal": prop["id"]}, dur=2))
                    break
            break
    # anger: confront, or (dishonest) spread a false rumour
    for tid, t in targets.items():
        other = w.agents.get(tid)
        if not other or not other["alive"] or t.get("aerger", 0) < 0.45:
            continue
        if any(b["id"] == tid for b in near) and p["conflict_avoidance"] < 0.55:
            out.append(opt("confront", f"{other['name']} zur Rede stellen", 0.2 + 0.6 * t["aerger"] - 0.4 * p["conflict_avoidance"],
                           target=tid, dur=1))
        listeners = [b for b in near if b["id"] != tid]
        if listeners and a["morals"]["ehrlichkeit"] < 0.35:
            out.append(opt("spread_rumor", f"{listeners[0]['name']} etwas Schlechtes über {other['name']} erzählen",
                           0.1 + 0.5 * t["aerger"] - 0.6 * a["morals"]["ehrlichkeit"], target=listeners[0]["id"], data={"about": tid}, dur=1))
        break
    # apologise to someone who is angry with me
    for b in near:
        if b["emo_targets"].get(a["id"], {}).get("aerger", 0) > 0.3 and w.rel(a["id"], b["id"])["familiarity"] > 0.2:
            out.append(opt("apologize", f"Sich bei {b['name']} entschuldigen", 0.15 + 0.5 * p["agreeableness"]
                           + 0.4 * a["emo"].get("scham", 0), target=b["id"], dur=1))
            break
    # visiting imprisoned family or friends
    for f in a["friends"] + ([a["partner"]] if a.get("partner") else []) + a["children"]:
        x = w.agents.get(f or "")
        if x and x["alive"] and x.get("prison") and x["prison"]["building"] in w.buildings:
            b = w.buildings[x["prison"]["building"]]
            out.append(opt("visit", f"{x['name']} im Gefängnis besuchen", 0.3 + 0.4 * w.rel(a["id"], x["id"])["affection"],
                           dest=(b["x"], b["y"]), target=x["id"], dur=2))
            break
    # appeal
    for c in w.cases.values():
        if c["accused"] == a["id"] and c["status"] == "schuldig" and not c.get("appeal") and justice.appeal_possible(w, c) and \
                w.tick - (c.get("verdict") or {}).get("tick", w.tick) < 4 * R.TICKS_PER_DAY:
            innocent = c.get("true_offender") != a["id"]
            out.append(opt("appeal", "Berufung einlegen", (1.4 if innocent else 0.2 + 0.4 * (1 - a["morals"]["ehrlichkeit"])),
                           target=c["id"], dur=1))
            break
    # suspicion: avoid trading with people believed dishonest
    for o in out:
        if o["type"] == "trade" and o.get("target"):
            est, unc = honesty_estimate(a, o["target"])
            o["u"] = round(o["u"] - 0.6 * max(0.0, 0.5 - est) * (1 - unc), 3)


def _role_options(w: World, a: dict, out: list, region: int) -> None:
    """Work at institutions and businesses: teachers, watch, healers, shopkeepers."""
    if not 8 <= w.hour < 17:
        return
    p = a["personality"]
    for inst in w.institutions.values():
        if not inst["active"] or a["id"] not in inst.get("members", []) or inst["region"] != w.home_region(a):
            continue
        if inst["type"] == "schule":
            sch = next((b for b in w.buildings.values() if b["type"] == "schule" and b["region"] == inst["region"]), None)
            if sch and sch.get("teacher_day") != w.day:
                out.append(opt("unterrichten", "In der Schule unterrichten", 0.6 + 0.4 * p["conscientiousness"], dest=(sch["x"], sch["y"]),
                               target=sch["id"], dur=8))
        elif inst["type"] == "wache":
            out.append(opt("patrol", "Streife gehen", 0.35 + 0.4 * a["values"]["security"], dur=4, data={"inst": inst["id"]}))
        elif inst["type"] == "heilwesen":
            hh = next((b for b in w.buildings.values() if b["type"] in ("heilhaus", "krankenhaus") and b["region"] == inst["region"]), None)
            if hh and any(x.get("illness") for x in w.living()):
                out.append(opt("duty", f"Dienst im {R.BUILDINGS[hh['type']]['label']}", 0.5 + 0.4 * a["skills"]["healing"],
                               dest=(hh["x"], hh["y"]), target=hh["id"], dur=6))
    shop = next((b for b in w.buildings.values() if b["type"] == "laden" and b.get("owner") == a["id"]), None)
    if shop and (a.get("inv") or {}):
        out.append(opt("shopkeep", "Den Laden führen", 0.5 + 0.4 * a["values"]["wealth"], dest=(shop["x"], shop["y"]), target=shop["id"], dur=6))
    if not shop:
        for b in w.buildings.values():
            if b["type"] != "laden" or b["region"] != region:
                continue
            keeper = w.agents.get(b.get("owner") or "")
            if keeper and keeper["alive"] and (keeper["x"], keeper["y"]) == (b["x"], b["y"]) and dist(a["x"], a["y"], b["x"], b["y"]) < 14:
                need = clamp(1 - food_days(w, a) / 4)
                out.append(opt("shop", f"Im Laden von {keeper['name']} einkaufen", 0.2 + 0.7 * need, dest=(b["x"], b["y"]), target=keeper["id"], dur=1))
                break
    # paving busy paths (traffic is real movement data)
    tr = w.map.get("traffic")
    if tr is not None and tr[a["y"], a["x"]] > 30 and not w.map["road"][a["y"], a["x"]] and (a.get("inv") or {}).get("stone", 0) >= 1 \
            and w.passable(a["x"], a["y"]) and not any((s["x"], s["y"]) == (a["x"], a["y"]) for s in w.sites.values()) \
            and not any((b["x"], b["y"]) == (a["x"], a["y"]) for b in w.buildings.values()):
        out.append(opt("pave", "Den viel begangenen Weg pflastern", 0.15 + 0.4 * a["values"]["community"], dur=1))


def _plan_specific_options(w: World, a: dict, out: list, home: dict | None) -> None:
    from .cognition import current_step
    for g in a["agenda"]:
        if g["status"] != "aktiv":
            continue
        s = current_step(g)
        if not s:
            continue
        if "explore" in s["acts"]:
            out.append(opt("explore", "Ein neues Gebiet erkunden", 0.3, data={"far": True}, dur=1))
        if "build_start" in s["acts"] and not a.get("building_plan"):
            btype = (s.get("data") or {}).get("btype")
            if btype and (R.BUILDINGS[btype]["tech"] is None or R.BUILDINGS[btype]["tech"] in a["techs"]) and \
                    not any(o["type"] == "build_start" and o["data"].get("btype") == btype for o in out):
                far = bool((s.get("data") or {}).get("far"))
                out.append(opt("build_start", f"{R.BUILDINGS[btype]['label']} beginnen" + (" (neuer Ort)" if far else ""), 0.4,
                               data={"btype": btype, "far": far}, dur=1))
    resources_needed = [s for g in a["agenda"] if g["status"] == "aktiv" for s in [current_step(g)] if s and set(s["acts"]) & {"chop", "quarry"}]
    if resources_needed and not any(o["type"] in ("chop", "quarry") for o in out):
        out.append(opt("explore", "Nach Holz und Steinen suchen", 0.45, dur=1))


def _c_candidate(w, a, act):
    prop = w.proposals.get(act["target"])
    if prop and prop["status"] == "offen" and a["id"] not in prop["candidates"]:
        prop["candidates"].append(a["id"])
        a["stats"]["candidacies"] = a["stats"].get("candidacies", 0) + 1
        w.emit("politik", "kandidatur", f"{a['name']} kandidiert ({prop['title']}).", actors=[a["id"]], x=a["x"], y=a["y"],
               data={"proposal": prop["id"]})


def _c_persuade(w, a, act):
    from .social3 import persuade
    b = w.agents.get(act["target"])
    if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        persuade(w, a, b, act["data"]["proposal"])


def _c_spread_rumor(w, a, act):
    from .social3 import spread_rumor
    b, about = w.agents.get(act["target"]), w.agents.get(act["data"]["about"])
    if b and about and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        spread_rumor(w, a, b, about)


def _c_apologize(w, a, act):
    from .social3 import apologize
    b = w.agents.get(act["target"])
    if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        apologize(w, a, b)


def _c_confront(w, a, act):
    b = w.agents.get(act["target"])
    if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 4:
        S.confront(w, a, b, None)
        t = a["emo_targets"].get(b["id"], {})
        if "aerger" in t:
            t["aerger"] = round(t["aerger"] * 0.7, 3)  # venting


def _c_explore(w, a, act):
    home = _home(w, a)
    cx, cy = (home["x"], home["y"]) if home else (a["x"], a["y"])
    best = None
    for _ in range(30):
        r = w.rng.randint(10, 18)
        ang = w.rng.random() * 6.283
        import math as _m
        x, y = int(cx + r * _m.cos(ang)), int(cy + r * _m.sin(ang))
        if w.in_bounds(x, y) and w.passable(x, y) and w.terrain(x, y) not in ("mountain",):
            crowd = len(w.agents_near(x, y, 5))
            score = -crowd + w.rng.random()
            if best is None or score > best[0]:
                best = (score, x, y)
    if best:
        path = find_path(w, (a["x"], a["y"]), (best[1], best[2]))
        if path:
            a["path"] = path
            a["action"] = {"type": "travel", "label": "Erkundet die Gegend", "target": None, "data": {}, "dur": 1, "remaining": 1,
                           "dest": [best[1], best[2]], "phase": "travel", "started": w.tick, "decision": None}
            a["stats"]["explorations"] = a["stats"].get("explorations", 0) + 1


def _c_appeal(w, a, act):
    from .justice import file_appeal
    c = w.cases.get(act["target"])
    if c:
        file_appeal(w, a, c)


def _c_alliance(w, a, act):
    from .social3 import alliance_of, found_alliance
    members = [w.agents[m] for m in act["data"]["members"] if m in w.agents and w.agents[m]["alive"] and not alliance_of(w, m)]
    agree = [m for m in members if w.rel(m["id"], a["id"])["trust"] > 0.55 and w.rng.random() < 0.4 + 0.4 * m["morals"]["loyalitaet"]]
    if len(agree) >= 2 and not alliance_of(w, a["id"]):
        purpose = "gegenseitige Unterstützung und gemeinsame Abstimmungen"
        found_alliance(w, a, agree, purpose)
    else:
        w.emit("politik", "buendnis_abgelehnt", f"{a['name']} findet nicht genug Unterstützung für ein Bündnis.", actors=[a["id"]],
               x=a["x"], y=a["y"])


def _c_visit(w, a, act):
    b = w.agents.get(act["target"])
    if b and b["alive"] and dist(a["x"], a["y"], b["x"], b["y"]) <= 2:
        S.converse(w, a, b)
        b["needs"]["stress"] = clamp(b["needs"]["stress"] - 0.08)
        w.emit("sozial", "besuch", f"{a['name']} besucht {b['name']} im Gefängnis.", actors=[a["id"], b["id"]], x=a["x"], y=a["y"])


def _c_unterrichten(w, a, act):
    b = w.buildings.get(act["target"])
    if b:
        b["teacher_day"] = w.day
        a["skills"]["teaching"] = round(min(1.0, a["skills"]["teaching"] + 0.01), 4)


def _c_patrol(w, a, act):
    home = _home(w, a)
    cx, cy = (home["x"], home["y"]) if home else (a["x"], a["y"])
    x, y = cx + w.rng.randint(-5, 5), cy + w.rng.randint(-5, 5)
    if w.in_bounds(x, y) and w.passable(x, y):
        path = find_path(w, (a["x"], a["y"]), (x, y))
        if path:
            a["path"] = path
            a["action"] = {"type": "travel", "label": "Auf Streife", "target": None, "data": {}, "dur": 1, "remaining": 1,
                           "dest": [x, y], "phase": "travel", "started": w.tick, "decision": None}


def _c_duty(w, a, act):
    b = w.buildings.get(act["target"])
    if not b:
        return
    for pat in w.agents_near(b["x"], b["y"], 1):
        if pat.get("illness") and pat["id"] != a["id"] and pat["illness"].get("treated_until", -1) < w.tick:
            _c_heal(w, a, {"target": pat["id"]})


def _c_shopkeep(w, a, act):
    a["stats"]["shop_hours"] = a["stats"].get("shop_hours", 0) + 1
    for cust in w.agents_near(a["x"], a["y"], 1):
        if cust["id"] != a["id"] and not cust.get("asleep") and w.age(cust) >= R.ADULT_AGE:
            deal = propose_trade(w, cust, a)
            if deal:
                execute_trade(w, cust, a, deal)
                break


def _c_shop(w, a, act):
    keeper = w.agents.get(act["target"])
    if keeper and keeper["alive"] and dist(a["x"], a["y"], keeper["x"], keeper["y"]) <= 1:
        deal = propose_trade(w, a, keeper)
        if deal:
            execute_trade(w, a, keeper, deal)


def _c_pave(w, a, act):
    if w.map["road"][a["y"], a["x"]] or w.qty(("agent", a["id"]), "stone") < 1:
        return
    site = start_site(w, "strasse", a["x"], a["y"], owner=a["id"], by=a["id"])
    deliver(w, a, site)
    work_on(w, a, site, R.BUILDINGS["strasse"]["labor"], 1.0)


COMPLETE.update({"candidate": _c_candidate, "persuade": _c_persuade, "spread_rumor": _c_spread_rumor, "apologize": _c_apologize,
                 "confront": _c_confront, "explore": _c_explore, "appeal": _c_appeal, "alliance": _c_alliance, "visit": _c_visit,
                 "unterrichten": _c_unterrichten, "patrol": _c_patrol, "duty": _c_duty, "shopkeep": _c_shopkeep, "shop": _c_shop,
                 "pave": _c_pave})
SIGNIFICANT |= {"spread_rumor", "confront", "appeal", "alliance", "candidate", "persuade"}
CATEGORY.update({"candidate": "politik", "persuade": "politik", "spread_rumor": "gemeinschaft", "apologize": "gemeinschaft",
                 "confront": "gemeinschaft", "explore": "bauen", "appeal": "politik", "alliance": "politik", "visit": "familie",
                 "unterrichten": "wissen", "patrol": "politik", "duty": "gemeinschaft", "shopkeep": "handel", "shop": "handel",
                 "pave": "bauen"})
