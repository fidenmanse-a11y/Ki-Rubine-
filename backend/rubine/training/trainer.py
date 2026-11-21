"""Real LoRA fine-tuning (PEFT) with a reproducible, resumable training loop.

* deterministic data order (seeded permutation per epoch)
* loss only on the assistant response (prompt tokens are masked)
* checkpoints (adapter + optimizer + scheduler + RNG) for pause/resume and crash safety
* control hook checked every optimizer step (pause / stop)
"""
from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Settings, get_settings
from ..llm.engine import load_base_model, load_tokenizer, resolve_device


@dataclass
class TrainConfig:
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"])
    learning_rate: float = 2e-4
    epochs: float = 1.0
    max_steps: int | None = None
    batch_size: int = 4
    grad_accum: int = 1
    max_seq_len: int = 384
    warmup_ratio: float = 0.05
    weight_decay: float = 0.0
    max_grad_norm: float = 1.0
    seed: int = 42
    save_every: int = 25

    @classmethod
    def from_params(cls, p: dict, settings: Settings) -> "TrainConfig":
        known = {k: v for k, v in p.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        cfg.max_seq_len = min(cfg.max_seq_len, settings.max_seq_len)
        if cfg.max_steps is not None:
            cfg.max_steps = min(int(cfg.max_steps), settings.max_train_steps)
        if not (1 <= cfg.lora_r <= 128):
            raise ValueError("lora_r muss zwischen 1 und 128 liegen")
        if not (1e-6 <= cfg.learning_rate <= 1e-2):
            raise ValueError("learning_rate außerhalb des erlaubten Bereichs")
        if not (1 <= cfg.batch_size <= 64 and 1 <= cfg.grad_accum <= 64):
            raise ValueError("batch_size/grad_accum außerhalb des erlaubten Bereichs")
        if not (0 < cfg.epochs <= 20):
            raise ValueError("epochs muss zwischen 0 und 20 liegen")
        return cfg


class TrainingInterrupted(Exception):
    def __init__(self, kind: str, step: int) -> None:
        super().__init__(kind)
        self.kind = kind  # pause | stop
        self.step = step


def tokenize_example(tok: Any, messages: list[dict], max_len: int) -> tuple[list[int], list[int]] | None:
    """Tokenize a chat; labels = -100 everywhere except the final assistant turn."""
    if messages[-1]["role"] != "assistant":
        return None
    prompt_text = tok.apply_chat_template(messages[:-1], add_generation_prompt=True, tokenize=False)
    full_text = tok.apply_chat_template(messages, tokenize=False)
    if not full_text.startswith(prompt_text):  # template mismatch fallback
        full_text = prompt_text + messages[-1]["content"] + (tok.eos_token or "")
    p_ids = tok(prompt_text, add_special_tokens=False)["input_ids"]
    r_ids = tok(full_text[len(prompt_text):], add_special_tokens=False)["input_ids"]
    if len(p_ids) >= max_len - 8:
        return None  # prompt alone too long: skip rather than train on a truncated answer
    ids = (p_ids + r_ids)[:max_len]
    labels = ([-100] * len(p_ids) + r_ids)[:max_len]
    return ids, labels


def _collate(batch: list[tuple[list[int], list[int]]], pad_id: int) -> dict:
    import torch
    L = max(len(i) for i, _ in batch)
    ids = torch.full((len(batch), L), pad_id, dtype=torch.long)
    lab = torch.full((len(batch), L), -100, dtype=torch.long)
    att = torch.zeros((len(batch), L), dtype=torch.long)
    for k, (i, l) in enumerate(batch):
        ids[k, :len(i)] = torch.tensor(i)
        lab[k, :len(l)] = torch.tensor(l)
        att[k, :len(i)] = 1
    return {"input_ids": ids, "labels": lab, "attention_mask": att}


def _sample_order(n: int, seed: int, total_samples: int) -> list[int]:
    out: list[int] = []
    epoch = 0
    while len(out) < total_samples:
        perm = list(range(n))
        random.Random(seed * 1000 + epoch).shuffle(perm)
        out.extend(perm)
        epoch += 1
    return out[:total_samples]


def train_lora(*, rows: list[dict], cfg: TrainConfig, out_dir: Path, ckpt_dir: Path,
               init_adapter: str | None = None,
               on_step: Callable[[int, int, float, float], str | None] | None = None,
               on_status: Callable[[str], None] | None = None,
               settings: Settings | None = None) -> dict:
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import load_file

    settings = settings or get_settings()
    status = on_status or (lambda m: None)
    random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    device = resolve_device(settings.device)

    status("Lade Tokenizer und Basismodell …")
    tok = load_tokenizer(settings)
    model = load_base_model(settings, device)
    if device == "cpu":
        model.float()
    if init_adapter:
        model = PeftModel.from_pretrained(model, init_adapter, is_trainable=True)
    else:
        lcfg = LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout,
                          target_modules=cfg.target_modules, task_type="CAUSAL_LM", bias="none")
        model = get_peft_model(model, lcfg)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())

    status("Tokenisiere Datensatz …")
    data = []
    skipped = 0
    for r in rows:
        t = tokenize_example(tok, r["messages"], cfg.max_seq_len)
        if t is None:
            skipped += 1
        else:
            data.append(t)
    if not data:
        raise ValueError("Keine trainierbaren Beispiele nach der Tokenisierung")

    per_step = cfg.batch_size * cfg.grad_accum
    total_steps = max(1, math.ceil(len(data) * cfg.epochs / per_step))
    if cfg.max_steps:
        total_steps = min(total_steps, cfg.max_steps)
    total_steps = min(total_steps, settings.max_train_steps)
    order = _sample_order(len(data), cfg.seed, total_steps * per_step)

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    warmup = max(1, int(total_steps * cfg.warmup_ratio))

    def lr_lambda(step: int) -> float:
        if step < warmup:
            return (step + 1) / warmup
        return max(0.0, (total_steps - step) / max(1, total_steps - warmup))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    start_step = 0
    losses: list[float] = []

    state_file = ckpt_dir / "state.pt"
    if state_file.exists():
        status("Setze Training vom Checkpoint fort …")
        st = torch.load(state_file, map_location="cpu", weights_only=True)
        if st.get("n_data") != len(data) or st.get("total_steps") != total_steps:
            raise ValueError("Checkpoint passt nicht zu Datensatz/Konfiguration")
        set_peft_model_state_dict(model, load_file(str(ckpt_dir / "adapter" / "adapter_model.safetensors")))
        opt.load_state_dict(st["optimizer"])
        sched.load_state_dict(st["scheduler"])
        torch.set_rng_state(st["torch_rng"])
        start_step = int(st["step"])
        losses = list(st.get("losses", []))

    def save_ckpt(step: int) -> None:
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        tmp = ckpt_dir / "adapter.tmp"
        model.save_pretrained(str(tmp))
        final = ckpt_dir / "adapter"
        if final.exists():
            import shutil
            shutil.rmtree(final)
        tmp.replace(final)
        torch.save({"optimizer": opt.state_dict(), "scheduler": sched.state_dict(), "step": step,
                    "torch_rng": torch.get_rng_state(), "n_data": len(data), "total_steps": total_steps,
                    "losses": losses[-2000:]}, ckpt_dir / "state.pt.tmp")
        (ckpt_dir / "state.pt.tmp").replace(state_file)

    model.train()
    t0 = time.time()
    tokens_seen = 0
    status(f"Training: {total_steps} Schritte, {len(data)} Beispiele, Gerät {device}")
    for step in range(start_step, total_steps):
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for micro in range(cfg.grad_accum):
            base = (step * cfg.grad_accum + micro) * cfg.batch_size
            batch = [data[i] for i in order[base: base + cfg.batch_size]]
            enc = {k: v.to(device) for k, v in _collate(batch, tok.pad_token_id).items()}
            tokens_seen += int(enc["attention_mask"].sum())
            out = model(**enc)
            (out.loss / cfg.grad_accum).backward()
            step_loss += float(out.loss.detach()) / cfg.grad_accum
        torch.nn.utils.clip_grad_norm_(params, cfg.max_grad_norm)
        opt.step()
        sched.step()
        losses.append(step_loss)
        lr = sched.get_last_lr()[0]
        control = on_step(step + 1, total_steps, step_loss, lr) if on_step else None
        if control in ("pause", "stop"):
            save_ckpt(step + 1)
            raise TrainingInterrupted(control, step + 1)
        if cfg.save_every and (step + 1) % cfg.save_every == 0 and step + 1 < total_steps:
            save_ckpt(step + 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_dir))
    summary = {
        "steps": total_steps, "examples": len(data), "skipped_examples": skipped,
        "first_loss": losses[0] if losses else None,
        "final_loss": losses[-1] if losses else None,
        "mean_loss_first10": sum(losses[:10]) / max(1, len(losses[:10])),
        "mean_loss_last10": sum(losses[-10:]) / max(1, len(losses[-10:])),
        "seconds": round(time.time() - t0, 1), "tokens_seen_this_run": tokens_seen,
        "trainable_params": trainable, "total_params": total, "device": device,
        "config": asdict(cfg), "init_adapter": init_adapter,
    }
    (out_dir / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
