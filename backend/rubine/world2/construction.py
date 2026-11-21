"""Construction: sites need a valid plot, delivered materials, labor and time. Only then a building exists."""
from __future__ import annotations

from . import rules as R
from .mapgen import T
from .state import World, dist


def occupied(w: World, x: int, y: int) -> bool:
    return any(b["x"] == x and b["y"] == y for b in w.buildings.values()) or \
        any(s["x"] == x and s["y"] == y for s in w.sites.values())


def valid_plot(w: World, btype: str, x: int, y: int) -> bool:
    if not w.in_bounds(x, y) or occupied(w, x, y):
        return False
    terr = w.terrain(x, y)
    spec = R.BUILDINGS[btype]
    if "needs_terrain" in spec:
        if terr not in spec["needs_terrain"]:
            return False
        if btype == "bruecke":
            # must connect land on two opposite sides
            return (w.passable(x - 1, y) and w.passable(x + 1, y)) or (w.passable(x, y - 1) and w.passable(x, y + 1)) \
                if w.in_bounds(x - 1, y) and w.in_bounds(x + 1, y) and w.in_bounds(x, y - 1) and w.in_bounds(x, y + 1) else False
        return True
    if terr in ("water", "river", "mountain"):
        return False
    if btype == "wassermuehle":
        return w.near_water(x, y, 1)
    if btype == "damm":
        sub = w.map["terrain"][max(0, y - 2):y + 3, max(0, x - 2):x + 3]
        return bool((sub == T["river"]).any())
    if btype == "brunnen":
        return not w.near_water(x, y, 2)
    return True


def choose_plot(w: World, a: dict, btype: str, near: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Pick a plot near the agent's home (or given point). Bounded rationality: searches a small area."""
    cx, cy = near or ((w.buildings[a["home"]]["x"], w.buildings[a["home"]]["y"]) if a.get("home") in w.buildings
                      else (a["x"], a["y"]))
    best, best_score = None, -1e9
    for r in range(0, 9):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if abs(dx) != r else range(-r, r + 1):
                x, y = cx + dx, cy + dy
                if not valid_plot(w, btype, x, y):
                    continue
                score = -dist(x, y, cx, cy) * 0.3
                if btype in R.SHELTER_TYPES or btype in ("markt", "versammlungshalle", "bauernhof"):
                    score += 2.0 if w.near_water(x, y, 3) else 0.0
                    score -= 3.0 if w.map["flooded"][y, x] or _floodplain(w, x, y) else 0.0
                if btype == "bauernhof":
                    score += 3.0 * float(w.map["fertility"][y, x])
                score += w.rng.random() * 0.5
                if score > best_score:
                    best, best_score = (x, y), score
        if best and r >= 3:
            break
    return best


def _floodplain(w: World, x: int, y: int) -> bool:
    sub = w.map["terrain"][max(0, y - 1):y + 2, max(0, x - 1):x + 2]
    return bool((sub == T["river"]).any())


def start_site(w: World, btype: str, x: int, y: int, *, owner: str, owner_kind: str = "agent",
               cause: int | None = None, by: str | None = None) -> dict:
    spec = R.BUILDINGS[btype]
    sid = w.new_id("S")
    site = {"id": sid, "type": btype, "x": x, "y": y, "owner": owner, "owner_kind": owner_kind,
            "need": dict(spec["mat"]), "inv": {}, "labor_needed": float(spec["labor"]), "labor_done": 0.0,
            "started": w.tick, "workers": [], "cause": None}
    w.sites[sid] = site
    who = w.agents[by]["name"] if by in w.agents else (w.institutions.get(owner, {}).get("name") or owner)
    site["cause"] = w.emit("bau", "baustelle", f"{who} beginnt den Bau: {spec['label']}.", actors=[by] if by else [],
                           x=x, y=y, data={"site": sid, "type": btype}, cause=cause)
    return site


def missing_materials(site: dict) -> dict:
    return {it: n - int(site["inv"].get(it, 0)) for it, n in site["need"].items() if int(site["inv"].get(it, 0)) < n}


def deliver(w: World, a: dict, site: dict) -> int:
    moved = 0
    for it, n in missing_materials(site).items():
        give = min(n, w.qty(("agent", a["id"]), it))
        if give > 0:
            w.transfer(("agent", a["id"]), ("site", site["id"]), it, give)
            moved += give
    return moved


def work_on(w: World, a: dict, site: dict, hours: float, efficiency: float) -> dict | None:
    if missing_materials(site):
        return None
    site["labor_done"] += hours * efficiency
    if a["id"] not in site["workers"]:
        site["workers"].append(a["id"])
    a["skills"]["building"] = round(min(1.0, a["skills"]["building"] + 0.004), 4)
    if site["labor_done"] >= site["labor_needed"]:
        return complete(w, site)
    return None


def complete(w: World, site: dict) -> dict:
    for it, n in site["need"].items():
        w.consume(("site", site["id"]), it, n, f"verbaut:{site['type']}")
    leftovers = dict(site["inv"])
    bid = w.new_id("B")
    b = {"id": bid, "type": site["type"], "x": site["x"], "y": site["y"], "owner": site["owner"],
         "owner_kind": site["owner_kind"], "condition": 1.0, "inv": {}, "built": w.tick, "builders": site["workers"],
         "region": w.region_of(site["x"], site["y"]), "name": None}
    w.buildings[bid] = b
    for it, n in leftovers.items():
        if n > 0:
            w.transfer(("site", site["id"]), ("building", bid), it, n)
    w.sites.pop(site["id"], None)
    if b["type"] == "bruecke":
        w.map["bridge"][b["y"], b["x"]] = 1
    if b["type"] == "strasse":
        w.map["road"][b["y"], b["x"]] = 1
    if b["type"] in ("strasse", "bruecke"):
        w.config["map_version"] = w.config.get("map_version", 0) + 1
    label = R.BUILDINGS[b["type"]]["label"]
    owner_name = w.agents[b["owner"]]["name"] if b["owner"] in w.agents else w.institutions.get(b["owner"], {}).get("name", b["owner"])
    eid = w.emit("bau", "gebaeude_fertig", f"{label} fertiggestellt (Eigentum: {owner_name}).",
                 actors=site["workers"][:6], x=b["x"], y=b["y"], data={"building": bid, "type": b["type"]},
                 cause=site.get("cause"))
    w.totals[f"built:{b['type']}"] += 1
    if b["owner_kind"] == "agent" and b["owner"] in w.agents:
        o = w.agents[b["owner"]]
        o["bio"].append([w.tick, f"{label} gebaut."])
        if b["type"] in R.SHELTER_TYPES and (not o.get("home") or _shelter_rank(w, b["type"]) > _shelter_rank(w, _home_type(w, o))):
            old = o.get("home")
            o["home"] = bid
            for pid in [o.get("partner")] + o["children"]:
                p = w.agents.get(pid or "")
                if p and p["alive"] and (p.get("home") in (None, old)):
                    p["home"] = bid
            w.remember(o, "biografie", f"Ich habe ein eigenes Zuhause gebaut ({label}).", 8, event=eid, tags=["haus"])
    for wid in site["workers"]:
        if wid in w.agents:
            w.agents[wid]["known"]["bld"].append(bid)
    return b


def _home_type(w: World, a: dict) -> str | None:
    h = w.buildings.get(a.get("home") or "")
    return h["type"] if h else None


def _shelter_rank(w: World, t: str | None) -> int:
    return {"huette": 1, "haus": 2, "steinhaus": 3}.get(t or "", 0)


def repair(w: World, a: dict, b: dict) -> bool:
    need = "stone" if b["type"] in ("steinhaus", "damm", "brunnen", "strasse") else "wood"
    if w.qty(("agent", a["id"]), need) < 1:
        return False
    w.consume(("agent", a["id"]), need, 1, f"reparatur:{b['id']}")
    b["condition"] = round(min(1.0, b["condition"] + 0.3), 3)
    return True


def release_building(w: World, b: dict) -> None:
    if b["type"] == "bruecke":
        w.map["bridge"][b["y"], b["x"]] = 0
    if b["type"] == "strasse":
        w.map["road"][b["y"], b["x"]] = 0
    for a in w.agents.values():
        if a.get("home") == b["id"]:
            a["home"] = None
            if a["alive"]:
                a["stressors"] = min(1.0, a.get("stressors", 0) + 0.3)
                w.remember(a, "verlust", f"Mein Zuhause ({R.BUILDINGS[b['type']]['label']}) ist verloren.", 8,
                           tags=["haus", "verlust"])
    for inst in w.institutions.values():
        if inst.get("seat") == b["id"]:
            inst["seat"] = None


def detect_settlements(w: World) -> None:
    """A settlement exists where >= 3 shelters stand within 5 tiles of each other (engine rule)."""
    shelters = [b for b in w.buildings.values() if b["type"] in R.SHELTER_TYPES]
    parent = {b["id"]: b["id"] for b in shelters}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, b1 in enumerate(shelters):
        for b2 in shelters[i + 1:]:
            if dist(b1["x"], b1["y"], b2["x"], b2["y"]) <= 5:
                parent[find(b1["id"])] = find(b2["id"])
    clusters: dict[str, list[dict]] = {}
    for b in shelters:
        clusters.setdefault(find(b["id"]), []).append(b)
    seen = set()
    for members in clusters.values():
        if len(members) < 3:
            continue
        ids = {b["id"] for b in members}
        match = next((s for s in w.settlements.values() if s["active"] and ids & set(s["buildings"])), None)
        cx = round(sum(b["x"] for b in members) / len(members))
        cy = round(sum(b["y"] for b in members) / len(members))
        if match is None:
            sid = w.new_id("T")
            first = min(members, key=lambda b: b["built"])
            founder = first["owner"] if first["owner"] in w.agents else None
            name = f"Siedlung {w.counters['T']} ({w.region_name(w.region_of(cx, cy))})"
            match = {"id": sid, "name": name, "named_by": None, "founded": w.tick, "founder": founder, "active": True,
                     "buildings": [], "x": cx, "y": cy, "region": w.region_of(cx, cy), "peak_pop": 0}
            w.settlements[sid] = match
            match["event"] = w.emit("bau", "siedlung", f"Eine neue Siedlung ist entstanden: {name} ({len(members)} Wohngebäude).",
                                    x=cx, y=cy, actors=[founder] if founder else [], data={"settlement": sid})
            if founder and w.mind is not None:
                w.mind.request_naming(w, founder, "siedlung", sid)
        match["buildings"] = sorted(ids)
        match["x"], match["y"] = cx, cy
        residents = sum(1 for a in w.living() if a.get("home") in ids)
        match["peak_pop"] = max(match.get("peak_pop", 0), residents)
        seen.add(match["id"])
    for s in w.settlements.values():
        if s["active"] and s["id"] not in seen:
            s["active"] = False
            w.emit("bau", "siedlung_aufgegeben", f"{s['name']} ist aufgegeben (weniger als 3 Wohngebäude).", x=s["x"], y=s["y"],
                   data={"settlement": s["id"]})


def settlement_of(w: World, x: int, y: int) -> dict | None:
    for s in w.settlements.values():
        if s["active"] and dist(s["x"], s["y"], x, y) <= 7:
            return s
    return None
