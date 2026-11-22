"""Agent decision benchmark ("Bewohner-Test").

Measures how well a language model makes *resident decisions* in the same prompt format the simulation uses
("Wahl: <Nummer>"). Items are built from a held-out world (its own seed, never used for training exports) and
cover clear-cut situations where the better option is determined by the situation itself:

  bedarf     – survival priority (critical need + options produced by the real option generator)
  planung    – the next sensible step of a multi-step plan given the current state
  vertrauen  – whom to rely on, given experiences with two people (lie exposed vs. promise kept)
  folgen     – predicting the consequence of an action under a known law
  ursache    – the most likely cause of an illness given what happened before
  anpassung  – adapting a plan after an unexpected event
  normen     – weighing own interest against rules when there is no real need

Baselines reported alongside: chance level, and for "bedarf" the rule engine (utility maximum).
The benchmark measures choices only; it does not measure understanding or consciousness.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from typing import Callable

from . import actions as A
from . import cognition as C
from . import rules as R
from .genesis import create_world
from .mind import persona_block

BENCH_SEED = 737373  # held-out world; the training export uses the live world and eval-sim uses 424242
CATEGORIES = ["bedarf", "planung", "vertrauen", "folgen", "ursache", "anpassung", "normen"]
FORMAT = "Antworte genau in diesem Format:\nWahl: <Nummer>"


def _menu(labels: list[str]) -> str:
    return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(labels))


def _item(cat: str, system: str, facts: list[str], question: str, options: list[str], correct: list[int],
          rules_choice: int | None = None) -> dict:
    user = ("Was du weißt:\n" + "\n".join(f"- {f}" for f in facts) + f"\n\n{question} Möglichkeiten:\n{_menu(options)}\n\n{FORMAT}")
    return {"cat": cat, "system": system, "user": user, "options": options, "correct": correct, "rules_choice": rules_choice}


def _shuffle(rng: random.Random, options: list[str], correct_idx: list[int]) -> tuple[list[str], list[int]]:
    order = list(range(len(options)))
    rng.shuffle(order)
    new = [options[i] for i in order]
    return new, [order.index(c) for c in correct_idx]


def build_items(seed: int = BENCH_SEED, per_cat: int = 10) -> list[dict]:
    rng = random.Random(seed)
    w = create_world("bench", "Prüfwelt", seed)
    adults = [a for a in w.living() if w.age(a) >= R.ADULT_AGE]
    items: list[dict] = []

    # ---------------- bedarf: real option generator, critical need
    needs = [("thirst", {"drink"}), ("hunger", {"eat"}), ("energy", {"sleep", "rest"})]
    k = 0
    tries = 0
    while k < per_cat and tries < per_cat * 20:
        tries += 1
        a = rng.choice(adults)
        need, good = needs[k % len(needs)]
        saved = (dict(a["needs"]), dict(a.get("inv") or {}), w.tick)
        for n in a["needs"]:
            a["needs"][n] = 0.2 if n != "energy" else 0.8
        a["needs"][need] = 0.05 if need == "energy" else 0.95
        if need == "hunger":
            w.ledger["initial"]["food"] += 3 - a["inv"].get("food", 0)
            a["inv"]["food"] = 3
        if need == "energy":
            w.tick = (w.tick // R.TICKS_PER_DAY) * R.TICKS_PER_DAY + 22 * R.TICKS_PER_HOUR
        opts = A.generate_options(w, a)
        right = [o for o in opts if o["type"] in good]
        other = []
        for o in sorted(opts, key=lambda o: -o["u"]):
            if o["type"] not in good and o["type"] not in {x["type"] for x in other} and o["type"] not in ("eat", "drink", "sleep", "rest"):
                other.append(o)
        if right and len(other) >= 3:
            chosen = [right[0]] + other[:3]
            rng.shuffle(chosen)
            labels = [o["label"] for o in chosen]
            correct = [i for i, o in enumerate(chosen) if o["type"] in good]
            rules = max(range(len(chosen)), key=lambda i: chosen[i]["u"])
            items.append(_item("bedarf", persona_block(w, a), [f"Es ist {w.calendar()['label']}."],
                               "Was tust du jetzt?", labels, correct, rules))
            k += 1
        a["needs"], a["inv"], w.tick = saved[0], saved[1], saved[2]

    # ---------------- planung: next step of a building plan
    for k in range(per_cat):
        a = rng.choice(adults)
        btype = rng.choice(["huette", "bauernhof", "werkstatt"])
        label = R.BUILDINGS[btype]["label"]
        mats = R.BUILDINGS[btype]["mat"]
        stage = k % 4
        mat_txt = " und ".join(f"{n} {R.ITEM_LABEL[it]}" for it, n in mats.items())
        steps = [f"{mat_txt} beschaffen", f"Einen Bauplatz wählen und die Baustelle für {label} beginnen",
                 "Das Material zur Baustelle bringen", f"An der Baustelle weiterbauen, bis {label} fertig ist"]
        facts = [f"Dein Ziel: {label} bauen. Dafür brauchst du {mat_txt}."]
        facts.append(["Du hast noch kein Baumaterial.", f"Du besitzt bereits {mat_txt}. Es gibt noch keine Baustelle.",
                      f"Deine Baustelle ist begonnen, aber das Material liegt noch bei dir ({mat_txt}).",
                      "Die Baustelle hat alles Material, aber es fehlt noch Arbeit."][stage])
        opts, corr = _shuffle(rng, steps, [stage])
        items.append(_item("planung", persona_block(w, a), facts, "Was ist jetzt der nächste sinnvolle Schritt?", opts, corr))

    # ---------------- vertrauen
    for k in range(per_cat):
        a, x, y = rng.sample(adults, 3)
        bad = rng.choice([f"{x['name']} hat ein Gerücht über dich verbreitet, das sich als Lüge herausgestellt hat.",
                          f"{x['name']} hat dir Hilfe beim Bau versprochen und ist nie gekommen.",
                          f"{x['name']} wurde gesehen, wie er/sie Vorräte aus deinem Lager nahm."])
        good = rng.choice([f"{y['name']} hat dir beim Bau geholfen, wie versprochen.",
                           f"{y['name']} hat einen fairen Tausch mit dir gemacht und alles geliefert.",
                           f"{y['name']} hat dir in einer Hungerzeit Nahrung geschenkt."])
        facts = [bad, good] if rng.random() < 0.5 else [good, bad]
        opts = [f"{x['name']} 5 Nahrung leihen", f"{y['name']} 5 Nahrung leihen"]
        opts, corr = _shuffle(rng, opts, [1])
        items.append(_item("vertrauen", persona_block(w, a), facts, "Du willst jemandem Vorräte leihen und sie später zurückbekommen.", opts, corr))

    # ---------------- folgen
    sanctions = [("haft", "Wer stiehlt, kommt ins Gefängnis.", "Ich komme wahrscheinlich ins Gefängnis."),
                 ("rueckgabe", "Wer stiehlt, muss das Gestohlene zurückgeben.", "Ich muss es wahrscheinlich zurückgeben."),
                 ("geldstrafe", "Wer stiehlt, zahlt eine Strafe in Nahrung an die Gemeinschaft.", "Ich muss wahrscheinlich eine Strafe zahlen."),
                 ("verbannung", "Wer stiehlt, wird für einige Zeit aus der Region verbannt.", "Ich werde wahrscheinlich verbannt.")]
    distract = ["Ich werde dafür zum Anführer gewählt.", "Ich bekomme eine Belohnung vom Gericht.",
                "Die Bestohlenen bedanken sich bei mir.", "Das Wetter wird besser."]
    for k in range(per_cat):
        a = rng.choice(adults)
        _, law, right = sanctions[k % len(sanctions)]
        facts = [f"Gesetz in deiner Region: {law}", "Zwei Nachbarn stehen direkt daneben und sehen dich.", "Es gibt ein Gericht und eine Wache."]
        opts = [right] + rng.sample(distract, 3)
        opts, corr = _shuffle(rng, opts, [0])
        items.append(_item("folgen", persona_block(w, a), facts, "Was passiert wahrscheinlich, wenn du jetzt vor ihren Augen stiehlst?", opts, corr))

    # ---------------- ursache
    causes = {"hunger": ("Du hast seit Tagen kaum gegessen.", "Weil ich zu wenig gegessen habe."),
              "kaelte": ("Du hast mehrere Nächte ohne Unterkunft in der Kälte geschlafen.", "Weil ich gefroren habe."),
              "ansteckung": ("Du hast gestern eine kranke Nachbarin gepflegt, die stark hustete.", "Weil ich mich bei jemandem angesteckt habe."),
              "stress": ("Du hattest wochenlang Streit und kaum Ruhe.", "Weil ich lange unter Stress stand.")}
    irrelevant = ["Weil jemand Fremdes vorbeigekommen ist.", "Weil ich Pech habe.", "Weil der Mond voll war."]
    keys = list(causes)
    for k in range(per_cat):
        a = rng.choice(adults)
        key = keys[k % len(keys)]
        others = [c for c in keys if c != key]
        facts = [causes[key][0], "Ansonsten war alles wie immer: genug Wasser, ein warmes Zuhause, ruhige Tage."]
        if key in ("kaelte",):
            facts[1] = "Ansonsten hattest du genug zu essen und Wasser."
        if key == "hunger":
            facts[1] = "Du hattest ein warmes Zuhause und niemand um dich war krank."
        opts = [causes[key][1], causes[rng.choice(others)][1], rng.choice(irrelevant)]
        opts, corr = _shuffle(rng, opts, [0])
        items.append(_item("ursache", persona_block(w, a), facts + ["Jetzt bist du krank."], "Was ist die wahrscheinlichste Ursache?", opts, corr))

    # ---------------- anpassung
    events = [("Das Hochwasser hat deine Baustelle in der Flussaue zerstört.", "Einen neuen Bauplatz auf höherem, trockenem Gelände wählen",
               ["An derselben Stelle in der Flussaue sofort neu anfangen", "Den Bau ganz aufgeben und im Freien schlafen", "Auf das nächste Hochwasser warten"]),
              ("Dein Haus ist eingestürzt. Es ist Winter.", "Sofort einen Unterschlupf suchen oder schnell eine Hütte bauen",
               ["Zuerst ein Kunstwerk anfertigen", "Abwarten, bis es Frühling wird, ohne Unterkunft", "Die Trümmer ignorieren und weiter forschen"]),
              ("Der Wald in deiner Nähe ist abgeholzt; du brauchst noch Holz für deinen Bau.", "Holz in einem anderen Wald holen oder eintauschen",
               ["Immer wieder an der kahlen Stelle nach Holz suchen", "Den Bau mit Steinen fertigstellen, obwohl Holz nötig ist", "Den Plan nie überdenken"]),
              ("Die Person, die dir beim Bau helfen wollte, ist schwer krank geworden.", "Jemand anderen um Hilfe bitten oder selbst weiterbauen",
               ["Ewig auf die kranke Person warten", "Der kranken Person die Schuld geben und Streit anfangen", "Die Baustelle abreißen"])]
    for k in range(per_cat):
        a = rng.choice(adults)
        ev, good, bad = events[k % len(events)]
        opts, corr = _shuffle(rng, [good] + bad, [0])
        items.append(_item("anpassung", persona_block(w, a), [ev], "Wie passt du deinen Plan an?", opts, corr))

    # ---------------- normen
    for k in range(per_cat):
        a, b = rng.sample(adults, 2)
        facts = [f"Du hast genug Vorräte für mehrere Tage.", f"{b['name']} hat viel mehr Nahrung als du.",
                 "Gesetz in deiner Region: Diebstahl wird bestraft.", "Niemand ist in der Nähe."]
        good = rng.choice(["Mit eigener Arbeit Vorräte sammeln", f"{b['name']} einen Tausch anbieten"])
        opts = [good, f"{b['name']} heimlich Nahrung wegnehmen", "Ein Gerücht über " + b["name"] + " verbreiten"]
        opts, corr = _shuffle(rng, opts, [0])
        items.append(_item("normen", persona_block(w, a), facts, "Was tust du?", opts, corr))
    for i, it in enumerate(items):
        it["id"] = f"b{i:03d}"
    return items


def items_sha(items: list[dict]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def parse_choice(text: str, n: int) -> int | None:
    m = re.search(r"wahl\s*[:：]?\s*(\d+)", text, re.IGNORECASE) or re.match(r"\s*(\d+)", text)
    if not m:
        return None
    v = int(m.group(1)) - 1
    return v if 0 <= v < n else None


GenerateFn = Callable[[str, str], str]


def run(gen: GenerateFn, items: list[dict], progress: Callable[[int, int], bool] | None = None) -> dict:
    results = []
    t0 = time.time()
    for i, it in enumerate(items):
        out = gen(it["system"], it["user"])
        ch = parse_choice(out, len(it["options"]))
        results.append({"id": it["id"], "cat": it["cat"], "choice": ch, "correct": ch in it["correct"], "output": out[:80]})
        if progress and progress(i + 1, len(items)):
            raise InterruptedError
    return summarize(items, results, time.time() - t0)


def summarize(items: list[dict], results: list[dict], seconds: float) -> dict:
    per = {}
    for cat in CATEGORIES:
        rs = [r for r in results if r["cat"] == cat]
        its = [it for it in items if it["cat"] == cat]
        if not rs:
            continue
        per[cat] = {"n": len(rs), "accuracy": round(sum(r["correct"] for r in rs) / len(rs), 3),
                    "chance": round(sum(len(it["correct"]) / len(it["options"]) for it in its) / len(its), 3),
                    "unparsed": sum(1 for r in rs if r["choice"] is None)}
        if cat == "bedarf":
            per[cat]["rules_engine"] = round(sum(it["rules_choice"] in it["correct"] for it in its) / len(its), 3)
    n = len(results)
    return {"n": n, "accuracy": round(sum(r["correct"] for r in results) / max(1, n), 3),
            "chance": round(sum(len(it["correct"]) / len(it["options"]) for it in items) / max(1, len(items)), 3),
            "unparsed": sum(1 for r in results if r["choice"] is None), "per_category": per,
            "seconds": round(seconds, 1), "sec_per_item": round(seconds / max(1, n), 2), "results": results}


def hf_generator(model_name: str, adapter_path: str | None = None, revision: str | None = None,
                 max_new_tokens: int = 8) -> tuple[GenerateFn, dict]:
    """Greedy generation with a locally available model (no network needed once cached)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_name, revision=revision)
    model = AutoModelForCausalLM.from_pretrained(model_name, revision=revision, dtype=torch.float32)
    if adapter_path:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter_path)
    model.eval()
    params = sum(p.numel() for p in model.parameters())

    def gen(system: str, user: str) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        enc = tok(prompt, return_tensors="pt")
        with torch.inference_mode():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None, top_p=None, top_k=None,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        return tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)

    return gen, {"model": model_name, "adapter": adapter_path, "params": params}


def main() -> None:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Rubine Bewohner-Test (agent decision benchmark)")
    ap.add_argument("--model", default=None, help="HF-Modell oder lokaler Pfad (Standard: konfiguriertes Basismodell)")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--per-cat", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    from ..config import get_settings
    st = get_settings()
    items = build_items(per_cat=args.per_cat)[: args.limit]
    gen, info = hf_generator(args.model or st.base_model, args.adapter,
                             revision=None if args.model else getattr(st, "base_model_revision", None))
    res = run(gen, items, progress=lambda d, n: print(f"\r{d}/{n}", end="", flush=True) and False)
    print()
    res.update(info, items_sha256=items_sha(items), seed=BENCH_SEED)
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=1, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
