"""Environment: seasons, weather, temperature, river level & floods, regrowth, decay, spoilage, heating."""
from __future__ import annotations

import numpy as np

from . import rules as R
from .mapgen import T
from .state import World, clamp

SEASON_TEMP = [11.0, 21.0, 10.0, -1.0]
RAIN_P = [0.35, 0.2, 0.4, 0.3]
WEATHER_LABEL = {"sonnig": "sonnig", "bewoelkt": "bewölkt", "regen": "Regen", "starkregen": "Starkregen",
                 "sturm": "Sturm", "schnee": "Schnee", "hitze": "Hitze"}


def region_temperature_offset(w: World, r: int) -> float:
    mask = w.map["region"] == r
    ys = np.nonzero(mask)[0]
    lat = (ys.mean() / w.h - 0.5) if len(ys) else 0.0
    elev = float(w.map["elev"][mask].mean()) if mask.any() else 0.5
    return lat * 10.0 - (elev - 0.5) * 8.0  # north (small y) colder, higher colder


def daily_weather(w: World) -> None:
    season = w.season
    for r in range(len(w.region_names)):
        key = str(r)
        prev = w.weather.get(key, {"dry_days": 0})
        base = SEASON_TEMP[season] + region_temperature_offset(w, r) + w.rng.gauss(0, 2.5)
        p_rain = RAIN_P[season] + (0.15 if prev.get("type") in ("regen", "starkregen") else 0)
        roll = w.rng.random()
        if roll < 0.03 and season != 3:
            kind = "sturm"
        elif roll < p_rain:
            kind = "starkregen" if w.rng.random() < 0.2 else "regen"
            if base < 1.0:
                kind = "schnee"
        elif season == 1 and base > 24 and w.rng.random() < 0.5:
            kind = "hitze"
        else:
            kind = "sonnig" if w.rng.random() < 0.6 else "bewoelkt"
        dry = 0 if kind in ("regen", "starkregen", "schnee") else prev.get("dry_days", 0) + 1
        w.weather[key] = {"type": kind, "temp": round(base, 1), "dry_days": dry, "drought": dry >= 8 and season == 1}
    # river level rises with rain in the upland/northern regions
    rain = sum(1 for v in w.weather.values() if v["type"] in ("regen", "schnee"))
    heavy = sum(1 for v in w.weather.values() if v["type"] in ("starkregen", "sturm"))
    w.river_level = round(clamp(w.river_level * 0.8 + 0.04 * rain + 0.12 * heavy, 0.0, 2.0), 3)


def temperature(w: World, x: int, y: int) -> float:
    wd = w.weather.get(str(w.region_of(x, y)), {"temp": 10.0})
    hour = w.hour
    diurnal = 4.0 * np.sin((hour - 9) / 24 * 2 * np.pi)
    return float(wd["temp"] + diurnal)


def weather_at(w: World, x: int, y: int) -> dict:
    return w.weather.get(str(w.region_of(x, y)), {"type": "sonnig", "temp": 10})


def daily_environment(w: World) -> None:
    """Called once per simulated day (00:00)."""
    m = w.map
    rng = np.random.default_rng(w.rng.randint(0, 2**31 - 1))
    growing = w.season in (0, 1, 2)
    # regrowth (bounded by each tile's capacity)
    for res, cap in (("wood", "wood_cap"), ("fish", "fish_cap"), ("forage", "forage_cap"), ("herbs", "herbs_cap")):
        if res in ("forage", "herbs") and not growing:
            continue
        p = R.REGROWTH[res]
        if res == "forage" and any(v.get("drought") for v in w.weather.values()):
            p *= 0.3
        grow = (rng.random(m[res].shape) < p) & (m[res] < m[cap])
        m[res] = m[res] + grow.astype(m[res].dtype)
    # clearings slowly become forest again
    clear = m["terrain"] == T["clearing"]
    m["clearing_age"][clear] += 1
    back = clear & (m["clearing_age"] >= R.CLEARING_TO_FOREST_DAYS) & (m["wood_cap"] > 0)
    if back.any():
        m["terrain"][back] = T["forest"]
        m["clearing_age"][back] = 0
    w.config["map_version"] = w.config.get("map_version", 0) + 1  # resource levels changed
    # floods
    m["flooded"][:] = 0
    if w.river_level > 1.0:
        river = (m["terrain"] == T["river"]) & (m["bridge"] == 0)
        near = np.zeros_like(river)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                near |= np.roll(np.roll(river, dy, 0), dx, 1)
        flooded = near & ~river & (m["terrain"] != T["water"])
        protected = np.zeros_like(flooded)
        for b in w.buildings.values():
            if b["type"] == "damm" and b["condition"] > 0.3:
                protected[max(0, b["y"] - 5):b["y"] + 6, max(0, b["x"] - 5):b["x"] + 6] = True
        flooded &= ~protected
        m["flooded"][flooded] = 1
        damaged = []
        for b in list(w.buildings.values()):
            if flooded[b["y"], b["x"]]:
                b["condition"] = round(max(0.0, b["condition"] - 0.3), 3)
                damaged.append(b["id"])
        n_tiles = int(flooded.sum())
        if n_tiles:
            w.emit("umwelt", "hochwasser", f"Hochwasser: Der Fluss ist über die Ufer getreten ({n_tiles} Felder überflutet, "
                   f"{len(damaged)} Gebäude beschädigt).", data={"tiles": n_tiles, "buildings": damaged,
                                                                 "river_level": w.river_level}, witnesses=False)
            for a in w.living():
                if near[a["y"], a["x"]] or any(abs(w.buildings[b]["x"] - a["x"]) < 8 for b in damaged if b in w.buildings):
                    w.learn(a, f"flood:{w.day}", "event", "Der Fluss hat Felder überflutet.", "beobachtet", 1.0)
                    w.remember(a, "beobachtung", "Hochwasser hat die Gegend am Fluss überflutet.", 6, tags=["hochwasser"])
    # building decay & storm damage
    storms = {int(k) for k, v in w.weather.items() if v["type"] == "sturm"}
    for b in list(w.buildings.values()):
        dec = R.BUILDINGS[b["type"]]["decay"]
        if w.region_of(b["x"], b["y"]) in storms:
            dec += 0.04
        b["condition"] = round(max(0.0, b["condition"] - dec), 4)
        if b["condition"] <= 0.0:
            collapse_building(w, b)
    # food spoilage (stochastic rounding keeps integers)
    for coll, kind in ((w.agents, "agent"), (w.buildings, "building"), (w.institutions, "inst")):
        for oid, obj in coll.items():
            n = int((obj.get("inv") or {}).get("food", 0))
            if n <= 0:
                continue
            rate = R.FOOD_SPOIL_STOREHOUSE if (kind == "building" and obj["type"] == "lagerhaus") else R.FOOD_SPOIL_PER_DAY
            spoil = int(n * rate) + (1 if w.rng.random() < (n * rate) % 1 else 0)
            if spoil:
                w.consume((kind, oid), "food", min(spoil, n), "verderb")


def nightly_heating(w: World) -> None:
    """At 22:00 occupied shelters burn 1 wood when it is cold; without wood occupants get cold."""
    for b in w.buildings.values():
        if b["type"] not in R.SHELTER_TYPES:
            continue
        if temperature(w, b["x"], b["y"]) - 4 >= R.COLD_THRESHOLD_C:
            b["heated"] = True
            continue
        occupants = [a for a in w.living() if a.get("home") == b["id"]]
        if not occupants:
            continue
        src = ("building", b["id"]) if (b.get("inv") or {}).get("wood", 0) > 0 else None
        if src is None:
            donor = next((a for a in occupants if (a.get("inv") or {}).get("wood", 0) > 0), None)
            src = ("agent", donor["id"]) if donor else None
        if src:
            w.consume(src, "wood", 1, "heizen")
            b["heated"] = True
        else:
            b["heated"] = False


def collapse_building(w: World, b: dict) -> None:
    from .construction import release_building
    w.emit("bau", "einsturz", f"{R.BUILDINGS[b['type']]['label']} ({b['id']}) ist verfallen und eingestürzt.",
           x=b["x"], y=b["y"], actors=[b.get("owner") or ""], data={"building": b["id"]})
    # stored goods are lost with the structure (documented sink)
    for it, n in list((b.get("inv") or {}).items()):
        w.consume(("building", b["id"]), it, n, "einsturz")
    release_building(w, b)
    w.buildings.pop(b["id"], None)
