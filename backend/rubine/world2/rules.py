"""Rubine World 2.0 – the 'physics' of the simulation.

Everything here is a *rule of the world* (how resources, bodies, buildings and
institutions work). Nothing here describes what the residents will do or which
society will emerge. Values are deliberately simple and documented so that every
state change can be traced back to a rule.
"""
from __future__ import annotations

# ------------------------------------------------------------------ time
TICK_MINUTES = 15
TICKS_PER_HOUR = 60 // TICK_MINUTES
TICKS_PER_DAY = 24 * TICKS_PER_HOUR          # 96
DAYS_PER_SEASON = 7
SEASONS = ["Frühling", "Sommer", "Herbst", "Winter"]
DAYS_PER_YEAR = DAYS_PER_SEASON * len(SEASONS)  # 28 – compressed calendar (documented)
TICKS_PER_YEAR = DAYS_PER_YEAR * TICKS_PER_DAY
START_HOUR = 6

# real seconds per tick at each speed (1× = one simulated minute per real second)
SPEEDS = {0: None, 1: 15.0, 5: 3.0, 20: 0.75, 100: 0.15}

ADULT_AGE = 18
SCHOOL_AGE = (6, 15)

# ------------------------------------------------------------------ items
ITEMS = ["food", "wood", "stone", "herbs", "tools", "medicine"]
ITEM_LABEL = {"food": "Nahrung", "wood": "Holz", "stone": "Stein", "herbs": "Kräuter", "tools": "Werkzeug",
              "medicine": "Medizin"}
# intrinsic usefulness in food-equivalents; personal valuations derive from this
BASE_VALUE = {"food": 1.0, "wood": 1.2, "stone": 1.5, "herbs": 1.0, "tools": 6.0, "medicine": 4.0}
FOOD_SPOIL_PER_DAY = 0.03       # fraction of food that spoils per day outside a storehouse
FOOD_SPOIL_STOREHOUSE = 0.005

# ------------------------------------------------------------------ needs (0 = satisfied, 1 = critical)
NEED_RATE = {  # increase per tick
    "hunger": 0.0075, "thirst": 0.012, "social": 0.0025,
}
ENERGY_DRAIN_IDLE = 0.006
ENERGY_DRAIN_WORK = 0.013
ENERGY_SLEEP_SHELTER = 0.045
ENERGY_SLEEP_OUTSIDE = 0.025
MEAL_RELIEF = 0.38          # hunger reduction per food unit
COLD_THRESHOLD_C = 6.0       # below this, being without shelter causes exposure

# ------------------------------------------------------------------ terrain
TERRAINS = {
    # name: (label, passable, move_cost)
    "water": ("See", False, 99), "river": ("Fluss", False, 99), "mountain": ("Gebirge", True, 4),
    "hill": ("Hügel", True, 2), "forest": ("Wald", True, 2), "meadow": ("Wiese", True, 1),
    "fertile": ("Flussaue", True, 1), "steppe": ("Steppe", True, 1), "tundra": ("Tundra", True, 2),
    "clearing": ("Rodung", True, 1),
}
REGROWTH = {  # per day, probability that a tile regains one unit (up to its cap)
    "wood": 0.10, "fish": 0.45, "forage": 0.35, "herbs": 0.12,
}
CLEARING_TO_FOREST_DAYS = 84  # a fully cut forest tile turns into a clearing; regrows to forest after ~3 years

# ------------------------------------------------------------------ technologies (per-person knowledge)
TECHS: dict[str, dict] = {
    "sammeln":       {"label": "Sammeln & Fischen", "prereq": [], "cost": 0},
    "huettenbau":    {"label": "Hüttenbau", "prereq": [], "cost": 0},
    "ackerbau":      {"label": "Ackerbau", "prereq": [], "cost": 40},
    "werkzeugbau":   {"label": "Werkzeugbau", "prereq": [], "cost": 30},
    "kraeuterkunde": {"label": "Kräuterkunde", "prereq": [], "cost": 30},
    "holzbau":       {"label": "Holzbau", "prereq": ["huettenbau"], "cost": 25},
    "steinbau":      {"label": "Steinbau", "prereq": ["werkzeugbau", "holzbau"], "cost": 50},
    "lagerhaltung":  {"label": "Lagerhaltung", "prereq": ["holzbau"], "cost": 30},
    "schrift":       {"label": "Schrift", "prereq": [], "cost": 80},
    "rechnen":       {"label": "Rechnen & Geldwesen", "prereq": ["schrift"], "cost": 60},
    "bewaesserung":  {"label": "Bewässerung", "prereq": ["ackerbau", "werkzeugbau"], "cost": 60},
    "brueckenbau":   {"label": "Brückenbau", "prereq": ["steinbau"], "cost": 70},
    "dammbau":       {"label": "Dammbau", "prereq": ["steinbau"], "cost": 70},
    "medizin":       {"label": "Medizin", "prereq": ["kraeuterkunde", "schrift"], "cost": 90},
    "wassermuehle":  {"label": "Wassermühle", "prereq": ["werkzeugbau", "brueckenbau"], "cost": 90},
}
BASE_TECHS = ["sammeln", "huettenbau"]

# ------------------------------------------------------------------ buildings
BUILDINGS: dict[str, dict] = {
    # materials, labor (work-hours), tech, shelter capacity, storage, special
    "huette":       {"label": "Hütte", "mat": {"wood": 5}, "labor": 10, "tech": "huettenbau", "shelter": 2, "storage": 20, "decay": 0.006},
    "haus":         {"label": "Wohnhaus", "mat": {"wood": 12, "stone": 2}, "labor": 28, "tech": "holzbau", "shelter": 4, "storage": 40, "decay": 0.003},
    "steinhaus":    {"label": "Steinhaus", "mat": {"stone": 14, "wood": 4}, "labor": 40, "tech": "steinbau", "shelter": 5, "storage": 50, "decay": 0.0012},
    "bauernhof":    {"label": "Bauernhof", "mat": {"wood": 8}, "labor": 18, "tech": "ackerbau", "storage": 40, "decay": 0.003, "needs_terrain": ["fertile", "meadow", "steppe", "clearing"]},
    "brunnen":      {"label": "Brunnen", "mat": {"stone": 6}, "labor": 12, "tech": "werkzeugbau", "decay": 0.002},
    "lagerhaus":    {"label": "Lagerhaus", "mat": {"wood": 12, "stone": 4}, "labor": 24, "tech": "lagerhaltung", "storage": 300, "decay": 0.002},
    "werkstatt":    {"label": "Werkstatt", "mat": {"wood": 8, "stone": 4}, "labor": 20, "tech": "werkzeugbau", "storage": 40, "decay": 0.003},
    "markt":        {"label": "Marktplatz", "mat": {"wood": 6}, "labor": 10, "tech": None, "decay": 0.003},
    "versammlungshalle": {"label": "Versammlungshalle", "mat": {"wood": 14, "stone": 6}, "labor": 30, "tech": "holzbau", "decay": 0.002},
    "schule":       {"label": "Schule", "mat": {"wood": 12, "stone": 4}, "labor": 26, "tech": "schrift", "decay": 0.002},
    "heilhaus":     {"label": "Heilhaus", "mat": {"wood": 10, "stone": 2}, "labor": 22, "tech": "kraeuterkunde", "storage": 30, "decay": 0.003},
    "krankenhaus":  {"label": "Krankenhaus", "mat": {"wood": 14, "stone": 12}, "labor": 50, "tech": "medizin", "storage": 60, "decay": 0.0015},
    "gericht":      {"label": "Gerichtshaus", "mat": {"wood": 10, "stone": 8}, "labor": 30, "tech": "schrift", "decay": 0.002},
    "bibliothek":   {"label": "Bibliothek/Forschung", "mat": {"wood": 10, "stone": 6}, "labor": 28, "tech": "schrift", "decay": 0.002},
    "strasse":      {"label": "Straße", "mat": {"stone": 1}, "labor": 2, "tech": None, "decay": 0.001},
    "bruecke":      {"label": "Brücke", "mat": {"wood": 10, "stone": 6}, "labor": 30, "tech": "brueckenbau", "decay": 0.002, "needs_terrain": ["river"]},
    "damm":         {"label": "Damm", "mat": {"stone": 12}, "labor": 30, "tech": "dammbau", "decay": 0.001},
    "wassermuehle": {"label": "Wassermühle", "mat": {"wood": 12, "stone": 8}, "labor": 40, "tech": "wassermuehle", "decay": 0.002},
}
SHELTER_TYPES = {"huette", "haus", "steinhaus"}

# ------------------------------------------------------------------ society
LAW_EFFECTS: dict[str, dict] = {
    "eigentumsschutz": {"label": "Eigentumsschutz", "params": {"sanktion": ["rueckgabe", "doppelte_rueckgabe", "verbannung"]}},
    "gewaltverbot": {"label": "Gewaltverbot", "params": {"sanktion": ["busse", "arrest", "verbannung"]}},
    "steuer": {"label": "Abgabe auf Handel & Löhne", "params": {"satz": [0.05, 0.1, 0.2]}},
    "grundversorgung": {"label": "Grundversorgung aus Gemeinschaftskasse", "params": {}},
    "ressourcenschutz": {"label": "Ressourcenschutz", "params": {"ressource": ["wood", "fish", "forage"]}},
    "erbrecht": {"label": "Erbrecht", "params": {"regel": ["familie", "kinder", "gemeinschaft"]}},
    "schulpflicht": {"label": "Schulpflicht", "params": {}},
    "gesundheitsversorgung": {"label": "Öffentliche Gesundheitsversorgung", "params": {}},
}
GOVERNMENT_FORMS = {
    "versammlung": "Versammlungsdemokratie (alle Erwachsenen stimmen ab)",
    "rat": "Rat (gewählte Mitglieder entscheiden)",
    "oberhaupt_wahl": "Gewähltes Oberhaupt",
    "oberhaupt_erblich": "Erbliches Oberhaupt (Monarchie)",
}
PUBLIC_INSTITUTIONS = {"gericht": "Gericht", "wache": "Wache", "schule": "Schulträger", "heilwesen": "Gesundheitsamt"}
PRIVATE_ORGS = {"unternehmen": "Unternehmen", "zeitung": "Zeitung", "hilfsverein": "Hilfsverein"}

# Engine bootstrap rule used ONLY while a region has no government of its own:
# a proposal made in public is adopted when yes > no and yes >= max(BOOTSTRAP_MIN_YES, BOOTSTRAP_QUORUM * adults in region).
BOOTSTRAP_MIN_YES = 3
BOOTSTRAP_QUORUM = 0.3
VOTE_DURATION_TICKS = TICKS_PER_DAY
COUNCIL_TERM_YEARS = 2
LEADER_TERM_YEARS = 3

# ------------------------------------------------------------------ health
ILLNESSES = {
    # name: (base daily chance factor, severity range, contagious, typical days)
    "Fieber": (1.0, (0.2, 0.5), True, (3, 8)),
    "Erkältung": (1.5, (0.1, 0.25), True, (2, 5)),
    "Magenleiden": (0.7, (0.2, 0.45), False, (2, 6)),
    "Auszehrung": (0.3, (0.3, 0.6), False, (6, 14)),
}
ACCIDENT_RISK = {"chop": 0.0015, "quarry": 0.002, "build": 0.001}  # per completed action, reduced by tools

SKILLS = ["farming", "gathering", "woodcutting", "masonry", "building", "crafting", "healing", "trading",
          "teaching", "research", "leadership", "art"]
SKILL_LABEL = {"farming": "Ackerbau", "gathering": "Sammeln", "woodcutting": "Holzfällen", "masonry": "Steinbruch",
               "building": "Bauen", "crafting": "Handwerk", "healing": "Heilkunde", "trading": "Handel",
               "teaching": "Lehren", "research": "Forschen", "leadership": "Führung", "art": "Kunst"}
PERSONALITY = ["openness", "conscientiousness", "agreeableness", "risk", "ambition", "patience", "trust",
               "conflict_avoidance", "self_control", "curiosity", "extraversion"]
PERSONALITY_LABEL = {"openness": "Offenheit", "conscientiousness": "Gewissenhaftigkeit",
                     "agreeableness": "Hilfsbereitschaft", "risk": "Risikobereitschaft", "ambition": "Ehrgeiz",
                     "patience": "Geduld", "trust": "Vertrauensbereitschaft", "conflict_avoidance": "Konfliktvermeidung",
                     "self_control": "Selbstkontrolle", "curiosity": "Neugier", "extraversion": "Geselligkeit"}
VALUES = ["fairness", "tradition", "freedom", "security", "wealth", "community"]
VALUE_LABEL = {"fairness": "Gerechtigkeit", "tradition": "Tradition", "freedom": "Freiheit",
               "security": "Sicherheit", "wealth": "Wohlstand", "community": "Gemeinschaft"}

EVENT_CATEGORIES = {
    "umwelt": "Umwelt & Wetter", "leben": "Leben & Gesundheit", "wirtschaft": "Wirtschaft",
    "bau": "Bau & Siedlungen", "politik": "Politik & Gesetze", "justiz": "Justiz & Konflikte",
    "sozial": "Beziehungen", "wissen": "Wissen & Kultur", "system": "System",
}
