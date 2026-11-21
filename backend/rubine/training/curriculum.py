"""Verifiable training tasks.

Every task family has
  * a deterministic generator (seeded RNG -> prompt + ground-truth answer),
  * a gold solution written by code (short reasoning + ``Antwort: ...``),
  * a programmatic verifier that checks a model answer against the ground truth.

Because correctness is decided by code, not by a model, answers produced by
Rubine itself or by the agents can be filtered reliably before they become
training data. New families can be registered with ``register_family``.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

ANSWER_INSTRUCTION = "Denke kurz Schritt für Schritt und schreibe am Ende genau eine Zeile 'Antwort: <Ergebnis>'."


@dataclass
class Task:
    family: str
    difficulty: int
    prompt: str
    answer: str
    solution: str  # gold response (reasoning + final answer line)
    kind: str = "exact"  # exact | number | list
    meta: dict = field(default_factory=dict)

    @property
    def prompt_hash(self) -> str:
        return prompt_hash(self.prompt)

    def to_dict(self) -> dict:
        return asdict(self)


def prompt_hash(prompt: str) -> str:
    norm = re.sub(r"\s+", " ", prompt.strip().lower())
    return hashlib.sha256(norm.encode()).hexdigest()


# ------------------------------------------------------------- answer parsing
_ANSWER_RE = re.compile(r"(?:antwort|answer|ergebnis|lösung)\s*[:：]\s*(.+)", re.IGNORECASE)


def extract_answer(text: str) -> str | None:
    """Return the content of the last 'Antwort: ...' line, if any."""
    matches = _ANSWER_RE.findall(text or "")
    if not matches:
        return None
    ans = matches[-1].strip()
    ans = ans.split("\n")[0].strip()
    return ans or None


def _norm(s: str) -> str:
    s = s.strip().strip("*_`\"'„“”").strip()
    s = re.sub(r"[.!。]+$", "", s).strip()
    return re.sub(r"\s+", " ", s).lower()


def _parse_number(s: str) -> float | None:
    s = _norm(s)
    s = s.replace("€", "").replace("euro", "").strip()
    m = re.search(r"-?\d[\d.\s]*(?:,\d+)?|-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    raw = m.group(0).replace(" ", "")
    if "," in raw:  # German decimal comma, dots as thousands separators
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def verify(task: Task | dict, model_output: str) -> tuple[bool, str | None]:
    """Check a model's full response against the ground truth."""
    t = task if isinstance(task, dict) else task.to_dict()
    got = extract_answer(model_output)
    if got is None:
        return False, None
    kind, expected = t["kind"], t["answer"]
    if kind == "number":
        a, b = _parse_number(got), _parse_number(expected)
        # The answer line must not contain several competing numbers.
        nums = re.findall(r"\d+(?:[.,]\d+)?", got)
        if a is None or b is None or len(set(nums)) > 2:
            return False, got
        return abs(a - b) < 1e-6, got
    if kind == "list":
        g = [x.strip().lower() for x in re.split(r"[,;]\s*|\s+", _norm(got)) if x.strip()]
        e = [x.strip().lower() for x in re.split(r"[,;]\s*|\s+", _norm(expected)) if x.strip()]
        return g == e, got
    return _norm(got) == _norm(expected), got


# ------------------------------------------------------------- families
Generator = Callable[[random.Random, int], Task]
FAMILIES: dict[str, Generator] = {}


def register_family(name: str) -> Callable[[Generator], Generator]:
    def deco(fn: Generator) -> Generator:
        FAMILIES[name] = fn
        return fn
    return deco


def _fmt(n: float) -> str:
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.2f}".rstrip("0").rstrip(".").replace(".", ",")


@register_family("arithmetic")
def gen_arithmetic(rng: random.Random, d: int) -> Task:
    if d == 1:
        a, b = rng.randint(10, 99), rng.randint(10, 99)
        op = rng.choice(["+", "-"])
        res = a + b if op == "+" else a - b
        prompt = f"Berechne {a} {op} {b}."
        sol = f"{a} {op} {b} = {res}.\nAntwort: {res}"
    elif d == 2:
        a, b = rng.randint(3, 25), rng.randint(3, 25)
        res = a * b
        prompt = f"Berechne {a} · {b}."
        tens, ones = (b // 10) * 10, b % 10
        steps = f"{a} · {tens} = {a * tens}, {a} · {ones} = {a * ones}, zusammen {res}." if tens and ones else f"{a} · {b} = {res}."
        sol = f"{steps}\nAntwort: {res}"
    else:
        a, b, c = rng.randint(2, 30), rng.randint(2, 12), rng.randint(2, 12)
        res = a + b * c
        prompt = f"Berechne {a} + {b} · {c}. Beachte Punkt vor Strich."
        sol = f"Punkt vor Strich: {b} · {c} = {b * c}. Dann {a} + {b * c} = {res}.\nAntwort: {res}"
    return Task("arithmetic", d, f"{prompt} {ANSWER_INSTRUCTION}", str(res), sol, "number")


_NAMES = ["Lena", "Jonas", "Mia", "Elias", "Emma", "Noah", "Sofia", "Paul", "Lea", "Finn", "Hanna", "Ben"]
_ITEMS = [("Äpfel", "Apfel"), ("Bücher", "Buch"), ("Stifte", "Stift"), ("Kekse", "Keks"), ("Murmeln", "Murmel")]


@register_family("word_problem")
def gen_word_problem(rng: random.Random, d: int) -> Task:
    name = rng.choice(_NAMES)
    items, _ = rng.choice(_ITEMS)
    start = rng.randint(3, 20)
    if d == 1:
        add = rng.randint(2, 15)
        res = start + add
        prompt = f"{name} hat {start} {items} und bekommt {add} dazu. Wie viele {items} hat {name} jetzt?"
        sol = f"{start} + {add} = {res}.\nAntwort: {res}"
    elif d == 2:
        packs, per = rng.randint(2, 6), rng.randint(2, 9)
        res = start + packs * per
        prompt = (f"{name} hat {start} {items}. Dann kauft {name} {packs} Packungen mit je {per} {items}. "
                  f"Wie viele {items} hat {name} insgesamt?")
        sol = f"{packs} · {per} = {packs * per} neue {items}. {start} + {packs * per} = {res}.\nAntwort: {res}"
    else:
        packs, per = rng.randint(2, 6), rng.randint(2, 9)
        give = rng.randint(1, start)
        res = start + packs * per - give
        prompt = (f"{name} hat {start} {items}, kauft {packs} Packungen mit je {per} {items} "
                  f"und verschenkt danach {give}. Wie viele {items} bleiben übrig?")
        sol = (f"{packs} · {per} = {packs * per}. {start} + {packs * per} = {start + packs * per}. "
               f"{start + packs * per} - {give} = {res}.\nAntwort: {res}")
    return Task("word_problem", d, f"{prompt} {ANSWER_INSTRUCTION}", str(res), sol, "number")


_UNITS = [
    ("Kilometer", "Meter", 1000), ("Meter", "Zentimeter", 100), ("Stunden", "Minuten", 60),
    ("Minuten", "Sekunden", 60), ("Kilogramm", "Gramm", 1000), ("Liter", "Milliliter", 1000),
    ("Euro", "Cent", 100), ("Tage", "Stunden", 24),
]


@register_family("unit_conversion")
def gen_units(rng: random.Random, d: int) -> Task:
    big, small, f = rng.choice(_UNITS)
    if d == 1:
        v = rng.randint(2, 12)
        res = v * f
        prompt = f"Wie viele {small} sind {v} {big}?"
        sol = f"Umrechnungsfaktor {big} → {small}: {f}. {v} · {f} = {res}.\nAntwort: {res}"
    elif d == 2:
        res_small = rng.randint(2, 9) * f + rng.choice([0, f // 2])
        res = res_small / f
        prompt = f"Wie viele {big} sind {res_small} {small}?"
        sol = f"{res_small} : {f} = {_fmt(res)}.\nAntwort: {_fmt(res)}"
    else:
        v1, v2 = rng.randint(1, 5), rng.randint(1, f - 1)
        res = v1 * f + v2
        prompt = f"Wie viele {small} sind {v1} {big} und {v2} {small} zusammen?"
        sol = f"{v1} · {f} = {v1 * f}. {v1 * f} + {v2} = {res}.\nAntwort: {res}"
    return Task("unit_conversion", d, f"{prompt} {ANSWER_INSTRUCTION}", _fmt(res), sol, "number")


@register_family("sorting")
def gen_sorting(rng: random.Random, d: int) -> Task:
    n = {1: 4, 2: 6, 3: 8}[d]
    nums = rng.sample(range(1, 100 if d < 3 else 1000), n)
    desc = d == 3 and rng.random() < 0.5
    res = sorted(nums, reverse=desc)
    order = "absteigend (größte zuerst)" if desc else "aufsteigend (kleinste zuerst)"
    prompt = f"Sortiere diese Zahlen {order}: {', '.join(map(str, nums))}."
    ans = ", ".join(map(str, res))
    sol = f"{'Größte' if desc else 'Kleinste'} Zahl zuerst, dann der Reihe nach.\nAntwort: {ans}"
    return Task("sorting", d, f"{prompt} {ANSWER_INSTRUCTION}", ans, sol, "list")


_WORDS = ["Erdbeere", "Banane", "Rubine", "Mississippi", "Kaffeetasse", "Schneemann", "Programmierer",
          "Ananas", "Bibliothek", "Regenbogen", "Abenteuer", "Wassermelone", "Eisenbahn", "Sonnenblume",
          "Haselnuss", "Teekanne", "Papagei", "Elefant", "Taschenlampe", "Kartoffel"]


@register_family("letter_count")
def gen_letter_count(rng: random.Random, d: int) -> Task:
    word = rng.choice(_WORDS)
    letters = sorted(set(word.lower()) - {" "})
    letter = rng.choice(letters)
    if d >= 2 and rng.random() < 0.3:  # sometimes ask for absent letters
        absent = sorted(set("abcdefghijklmnoprstuz") - set(word.lower()))
        letter = rng.choice(absent)
    cnt = word.lower().count(letter)
    spelled = "-".join(word.upper())
    prompt = f"Wie oft kommt der Buchstabe '{letter}' im Wort '{word}' vor (Groß-/Kleinschreibung egal)?"
    sol = f"Buchstabiert: {spelled}. Der Buchstabe '{letter}' kommt {cnt}-mal vor.\nAntwort: {cnt}"
    return Task("letter_count", d, f"{prompt} {ANSWER_INSTRUCTION}", str(cnt), sol, "number")


@register_family("ordering_logic")
def gen_logic(rng: random.Random, d: int) -> Task:
    n = {1: 3, 2: 4, 3: 5}[d]
    people = rng.sample(_NAMES, n)  # oldest -> youngest
    pairs = [(people[i], people[i + 1]) for i in range(n - 1)]
    rng.shuffle(pairs)
    facts = " ".join(f"{a} ist älter als {b}." for a, b in pairs)
    ask_young = rng.random() < 0.5
    res = people[-1] if ask_young else people[0]
    q = "Wer ist am jüngsten?" if ask_young else "Wer ist am ältesten?"
    prompt = f"{facts} {q}"
    chain = " > ".join(people)
    sol = f"Reihenfolge nach Alter: {chain}.\nAntwort: {res}"
    return Task("ordering_logic", d, f"{prompt} {ANSWER_INSTRUCTION}", res, sol, "exact")


_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


@register_family("weekday_math")
def gen_weekday(rng: random.Random, d: int) -> Task:
    start = rng.randrange(7)
    k = {1: rng.randint(1, 6), 2: rng.randint(7, 20), 3: rng.randint(21, 100)}[d]
    back = d == 3 and rng.random() < 0.4
    idx = (start - k) % 7 if back else (start + k) % 7
    res = _DAYS[idx]
    rel = "vor" if back else "nach"
    prompt = f"Heute ist {_DAYS[start]}. Welcher Wochentag ist {k} Tage {rel} heute?"
    sol = f"{k} mod 7 = {k % 7}. {_DAYS[start]} {'-' if back else '+'} {k % 7} Tage = {res}.\nAntwort: {res}"
    return Task("weekday_math", d, f"{prompt} {ANSWER_INSTRUCTION}", res, sol, "exact")


@register_family("string_reverse")
def gen_reverse(rng: random.Random, d: int) -> Task:
    word = rng.choice(_WORDS)
    if d == 1:
        word = word[:5]
    res = word[::-1].lower()
    prompt = f"Schreibe das Wort '{word.lower()}' rückwärts (in Kleinbuchstaben)."
    sol = f"Buchstaben: {'-'.join(word.lower())}. Rückwärts: {'-'.join(res)}.\nAntwort: {res}"
    return Task("string_reverse", d, f"{prompt} {ANSWER_INSTRUCTION}", res, sol, "exact")


# ------------------------------------------------------------- curriculum
@dataclass
class CurriculumStage:
    name: str
    difficulty_weights: dict[int, float]
    families: list[str]
    unlock_accuracy: float  # accuracy on the previous stage required to unlock


CURRICULUM: list[CurriculumStage] = [
    CurriculumStage("Grundlagen", {1: 1.0}, list(FAMILIES), 0.0),
    CurriculumStage("Aufbau", {1: 0.4, 2: 0.6}, list(FAMILIES), 0.5),
    CurriculumStage("Fortgeschritten", {1: 0.2, 2: 0.4, 3: 0.4}, list(FAMILIES), 0.6),
]


def stage_for(accuracy: float | None) -> CurriculumStage:
    """Highest stage whose unlock threshold is reached."""
    acc = accuracy or 0.0
    current = CURRICULUM[0]
    for st in CURRICULUM:
        if acc >= st.unlock_accuracy:
            current = st
    return current


def sample_task(rng: random.Random, families: list[str] | None = None,
                difficulty_weights: dict[int, float] | None = None) -> Task:
    fams = families or list(FAMILIES)
    weights = difficulty_weights or {1: 1.0}
    fam = rng.choice(fams)
    d = rng.choices(list(weights), weights=list(weights.values()))[0]
    return FAMILIES[fam](rng, d)


def generate_tasks(n: int, seed: int | str, families: list[str] | None = None,
                   difficulty_weights: dict[int, float] | None = None,
                   exclude_hashes: set[str] | None = None, max_tries: int = 50) -> list[Task]:
    """Generate ``n`` unique tasks, skipping any whose prompt hash is excluded."""
    rng = random.Random(f"rubine-{seed}")
    seen = set(exclude_hashes or ())
    out: list[Task] = []
    tries = 0
    while len(out) < n and tries < n * max_tries:
        tries += 1
        t = sample_task(rng, families, difficulty_weights)
        h = t.prompt_hash
        if h in seen:
            continue
        seen.add(h)
        out.append(t)
    return out
