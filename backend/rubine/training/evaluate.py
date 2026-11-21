"""Evaluation on the frozen held-out set + promotion gate."""
from __future__ import annotations

import math
from collections import defaultdict
from contextlib import nullcontext
from typing import Any, Callable

from ..config import Settings, get_settings
from ..llm.engine import SYSTEM_PROMPT, build_chat_prompt
from . import curriculum as cur
from .trainer import _collate, tokenize_example


def _is_peft(model: Any) -> bool:
    return type(model).__name__.startswith("Peft")


def evaluate_items(model: Any, tok: Any, items: list[dict], device: str, *, batch_size: int = 8,
                   max_new_tokens: int = 96, use_adapter: bool = True,
                   progress: Callable[[int, int], bool] | None = None) -> dict:
    """Greedy-decode every eval prompt and verify with the programmatic checker."""
    import torch
    tok.padding_side = "left"
    results = []
    ctx_factory = (lambda: model.disable_adapter()) if (not use_adapter and _is_peft(model)) \
        else (lambda: nullcontext())
    model.eval()
    for b in range(0, len(items), batch_size):
        chunk = items[b:b + batch_size]
        prompts = [build_chat_prompt(tok, [{"role": "user", "content": t["prompt"]}], SYSTEM_PROMPT) for t in chunk]
        enc = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to(device)
        with torch.inference_mode(), ctx_factory():
            out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False, temperature=None,
                                 top_p=None, top_k=None, pad_token_id=tok.pad_token_id)
        for t, row in zip(chunk, out[:, enc["input_ids"].shape[1]:]):
            text = tok.decode(row, skip_special_tokens=True).strip()
            ok, got = cur.verify(t, text)
            results.append({"prompt": t["prompt"], "family": t["family"], "difficulty": t["difficulty"],
                            "expected": t["answer"], "extracted": got, "correct": ok, "output": text})
        if progress and progress(min(b + batch_size, len(items)), len(items)):
            raise InterruptedError("stop")
    tok.padding_side = "right"
    fam: dict[str, dict] = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in results:
        fam[r["family"]]["n"] += 1
        fam[r["family"]]["correct"] += int(r["correct"])
    per_family = {k: {**v, "accuracy": v["correct"] / v["n"]} for k, v in sorted(fam.items())}
    acc = sum(r["correct"] for r in results) / max(1, len(results))
    return {"accuracy": acc, "n": len(results), "per_family": per_family, "results": results}


def eval_loss(model: Any, tok: Any, items: list[dict], device: str, *, use_adapter: bool = True,
              max_len: int = 384, batch_size: int = 8) -> float:
    """Mean token loss of the gold solutions (lower = model finds correct answers more likely)."""
    import torch
    rows = []
    for t in items:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": t["prompt"]},
                {"role": "assistant", "content": t["solution"]}]
        ex = tokenize_example(tok, msgs, max_len)
        if ex:
            rows.append(ex)
    total, count = 0.0, 0
    ctx = model.disable_adapter() if (not use_adapter and _is_peft(model)) else nullcontext()
    with torch.inference_mode(), ctx:
        for b in range(0, len(rows), batch_size):
            enc = {k: v.to(device) for k, v in _collate(rows[b:b + batch_size], tok.pad_token_id).items()}
            logits = model(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"]).logits
            shift_logits = logits[:, :-1].float()
            shift_labels = enc["labels"][:, 1:]
            loss = torch.nn.functional.cross_entropy(shift_logits.reshape(-1, shift_logits.size(-1)),
                                                     shift_labels.reshape(-1), ignore_index=-100,
                                                     reduction="sum")
            total += float(loss)
            count += int((shift_labels != -100).sum())
    return total / count if count else math.nan


def promotion_gate(candidate: dict, parent: dict, settings: Settings | None = None) -> tuple[bool, list[str]]:
    """Decide whether a candidate may be *proposed* for activation (never auto-activated)."""
    st = settings or get_settings()
    reasons: list[str] = []
    ok = True
    if candidate["n"] != parent["n"] or candidate["n"] == 0:
        return False, ["Evaluationsmengen sind nicht identisch oder leer."]
    need = parent["accuracy"] + st.gate_min_delta
    if candidate["accuracy"] + 1e-9 < need:
        ok = False
        reasons.append(f"Genauigkeit {candidate['accuracy']:.1%} < benötigt {need:.1%} (Elternversion {parent['accuracy']:.1%}).")
    else:
        reasons.append(f"Genauigkeit {candidate['accuracy']:.1%} ≥ {need:.1%} (Elternversion {parent['accuracy']:.1%}).")
    for fam, pv in parent["per_family"].items():
        cv = candidate["per_family"].get(fam)
        if cv is None:
            continue
        drop = pv["accuracy"] - cv["accuracy"]
        if drop > st.gate_max_family_drop + 1e-9:
            ok = False
            reasons.append(f"Rückschritt in '{fam}': {pv['accuracy']:.0%} → {cv['accuracy']:.0%}.")
    return ok, reasons
