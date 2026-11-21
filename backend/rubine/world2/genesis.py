"""Creation of a new world: terrain + 25 initial residents.

No government, no laws, no money, no buildings, no hierarchy. Residents differ in
origin (which shapes initial skills/knowledge), personality, values and a small random
starting inventory. Randomness is seeded, so a world can be recreated exactly.
"""
from __future__ import annotations

import random

import numpy as np

from . import rules as R
from .mapgen import T, generate
from .state import World

GIVEN = ["Aleksa", "Bente", "Cem", "Daria", "Emil", "Fenja", "Goran", "Hana", "Ilias", "Jule", "Kofi", "Lina",
         "Malik", "Nora", "Oskar", "Pia", "Quentin", "Rana", "Sami", "Tilda", "Umut", "Vera", "Wanja", "Xaver",
         "Yasmin", "Zeno", "Amira", "Bruno", "Carla", "Dario", "Esra", "Finn", "Greta", "Henrik", "Ida", "Jonas",
         "Kaja", "Levin", "Mila", "Noah", "Olga", "Paul", "Ronja", "Siena", "Theo", "Ula", "Vito", "Wilma", "Yara",
         "Zora", "Anton", "Bela", "Clara", "David", "Elif", "Frida", "Gabriel", "Helga", "Ivo", "Juna"]
FAMILY = ["Ahrens", "Brandt", "Celik", "Dorn", "Eder", "Falk", "Graf", "Hoxha", "Iwanow", "Jansen", "Kaya", "Lund",
          "Moreau", "Nowak", "Okafor", "Petrov", "Quast", "Rossi", "Sommer", "Tanaka", "Ulrich", "Vogel", "Wolff",
          "Yilmaz", "Zimmer", "Berger", "Hahn", "Lorenz", "Mendes", "Storm"]
INTERESTS = ["Handwerk", "Musik", "Pflanzen", "Sterne", "Geschichten", "Tiere", "Handel", "Rätsel", "Kochen",
             "Wasser", "Steine", "Gemeinschaft", "Heilkunst", "Bauen", "Malerei", "Philosophie"]
ORIGINS = {
    "Flussbauern": {"techs": ["ackerbau"], "skills": {"farming": 0.4, "gathering": 0.3}},
    "Bergvolk": {"techs": ["werkzeugbau"], "skills": {"masonry": 0.4, "crafting": 0.3}},
    "Waldleute": {"techs": ["kraeuterkunde", "holzbau"], "skills": {"woodcutting": 0.4, "healing": 0.3}},
    "Küstenfischer": {"techs": [], "skills": {"gathering": 0.4, "trading": 0.35}},
}
GOAL_TYPES = {
    "haus": "Ein eigenes, sicheres Zuhause haben",
    "wohlstand": "Vorräte und Wohlstand aufbauen",
    "wissen": "Neues Wissen entdecken und weitergeben",
    "familie": "Eine Familie gründen",
    "gemeinschaft": "Die Gemeinschaft stärken",
    "ansehen": "Anerkennung und Einfluss gewinnen",
    "freiheit": "Unabhängig und frei leben",
}


def _trait(rng: random.Random, mean: float = 0.5, sd: float = 0.18) -> float:
    return round(min(0.98, max(0.02, rng.gauss(mean, sd))), 3)


def make_agent(w: World, rng: random.Random, *, name: str, family: str, origin: str, birth_tick: int,
               x: int, y: int, personality: dict | None = None, values: dict | None = None,
               generation: int = 0, parents: list[str] | None = None) -> dict:
    aid = w.new_id("A")
    pers = personality or {k: _trait(rng) for k in R.PERSONALITY}
    vals = values or {k: _trait(rng) for k in R.VALUES}
    skills = {s: round(rng.uniform(0.0, 0.12), 3) for s in R.SKILLS}
    techs = list(R.BASE_TECHS)
    if origin in ORIGINS:
        for s, v in ORIGINS[origin]["skills"].items():
            skills[s] = round(min(1.0, v + rng.uniform(-0.1, 0.15)), 3)
        techs += ORIGINS[origin]["techs"]
    # goals emerge from personality/values (motivations, not a script)
    weights = {"haus": 0.6 + vals["security"], "wohlstand": vals["wealth"] + pers["ambition"],
               "wissen": pers["curiosity"] + pers["openness"], "familie": vals["tradition"] + pers["agreeableness"] * 0.5,
               "gemeinschaft": vals["community"] + pers["agreeableness"] * 0.5, "ansehen": pers["ambition"] + pers["extraversion"] * 0.5,
               "freiheit": vals["freedom"] + pers["risk"] * 0.5}
    goals = sorted(weights, key=lambda g: weights[g] + rng.random() * 0.4, reverse=True)[:3]
    a = {
        "id": aid, "name": name, "family": family, "origin": origin, "birth_tick": birth_tick, "alive": True,
        "death_tick": None, "death_cause": None, "generation": generation, "x": x, "y": y, "path": [],
        "personality": pers, "values": vals, "interests": rng.sample(INTERESTS, 3), "skills": skills,
        "techs": sorted(set(techs)),
        "needs": {"hunger": round(rng.uniform(0.1, 0.3), 3), "thirst": round(rng.uniform(0.1, 0.3), 3),
                  "energy": round(rng.uniform(0.7, 0.95), 3), "social": 0.3, "stress": 0.15},
        "health": 1.0, "max_health": 1.0, "illness": None, "chronic": False, "exposure": 0.0, "asleep": False,
        "inv": {}, "home": None, "partner": None, "parents": parents or [], "children": [], "employer": None,
        "action": None, "intention": None,
        "goals": [{"type": g, "text": GOAL_TYPES[g], "since": w.tick} for g in goals],
        "plans": [], "stm": [], "ltm": [], "facts": {}, "known": {"res": {}, "bld": []}, "research": {},
        "bio": [], "decisions": [], "stats": {}, "banned": {}, "arrest_until": None,
        "llm_day": -1, "llm_calls": 0, "model": None, "pending": None, "satisfaction": 0.6,
        "expecting": None,
    }
    w.agents[aid] = a
    from .cognition import init_agent
    init_agent(w, a)
    return a


def create_world(world_id: str, name: str, seed: int, population: int = 25) -> World:
    w = World()
    w.world_id, w.name, w.seed = world_id, name, seed
    w.rng = random.Random(seed)
    m = generate(seed)
    w.w, w.h = m["w"], m["h"]
    w.region_names = m["region_names"]
    for k in ("terrain", "elev", "moist", "wood", "stone", "fish", "forage", "herbs", "fertility", "region"):
        w.map[k] = m[k]
    w.map["wood_cap"] = m["wood"].copy()
    w.map["fish_cap"] = m["fish"].copy()
    w.map["forage_cap"] = m["forage"].copy()
    w.map["herbs_cap"] = m["herbs"].copy()
    w.map["clearing_age"] = np.zeros((w.h, w.w), dtype=np.int32)
    w.map["flooded"] = np.zeros((w.h, w.w), dtype=np.int8)
    w.map["road"] = np.zeros((w.h, w.w), dtype=np.int8)
    w.map["bridge"] = np.zeros((w.h, w.w), dtype=np.int8)
    w.map["traffic"] = np.zeros((w.h, w.w), dtype=np.int32)
    w.config = {"max_memories": 250, "max_population": 120, "llm": {"enabled": True, "mode": "async",
                "calls_per_agent_day": 4, "timeout_ticks": 4}, "model": {"default": "base", "canary": None}, "schema": 3, "follow": []}
    rng = w.rng
    sx, sy = m["start"]
    names = rng.sample(GIVEN, population)
    origins = list(ORIGINS)
    for i in range(population):
        # spawn on a passable land tile near the start
        for _ in range(200):
            x = min(w.w - 1, max(0, sx + rng.randint(-4, 4)))
            y = min(w.h - 1, max(0, sy + rng.randint(-4, 4)))
            if w.passable(x, y) and int(w.map["terrain"][y, x]) not in (T["mountain"],):
                break
        age = rng.randint(18, 58)
        origin = origins[i % len(origins)]
        a = make_agent(w, rng, name=names[i], family=rng.choice(FAMILY), origin=origin,
                       birth_tick=-int(age * R.TICKS_PER_YEAR + rng.randint(0, R.TICKS_PER_YEAR - 1)), x=x, y=y)
        if rng.random() < 0.12:
            a["techs"] = sorted(set(a["techs"] + ["schrift"]))
        start_inv = {"food": rng.randint(5, 10), "wood": rng.randint(0, 3), "herbs": rng.randint(0, 2)}
        if rng.random() < 0.3:
            start_inv["tools"] = 1
        for it, n in start_inv.items():
            if n:
                a["inv"][it] = n
                w.ledger["initial"][it] += n
        w.remember(a, "biografie", f"Ich bin {a['name']} {a['family']}, {int(age)} Jahre alt, aufgewachsen bei den "
                   f"{origin}. Ich bin mit anderen in dieses Tal gekommen, um neu anzufangen.", 9, tags=["herkunft"])
        a["bio"].append([0, f"Kam mit {population - 1} anderen ins Tal ({origin})."])
    w.emit("system", "welt_erstellt", f"Neue Welt '{name}' (Seed {seed}) mit {population} Bewohnern erstellt. "
           "Es gibt keine Regierung, keine Gesetze, kein Geld und keine Gebäude.", x=sx, y=sy, witnesses=False)
    from . import env
    env.daily_weather(w)
    for a in w.living():
        from .perception import perceive
        perceive(w, a, radius=7)
    return w
