"""Test setup: isolated data dir + a tiny randomly-initialised Qwen2 model.

The tiny model uses the real Qwen2.5 tokenizer (must be in the local HF cache,
which scripts/setup downloads) but only ~10M random weights, so training and
generation are fast. It produces gibberish – tests check mechanics (streaming,
LoRA training, checkpoints, gates), never answer quality.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="rubine-test-"))
os.environ.update({
    "RUBINE_DATA_DIR": str(_TMP / "data"),
    "RUBINE_ADMIN_PASSWORD": "test-password-123",
    "RUBINE_SIM_ENABLED": "false",
    "RUBINE_EVAL_SET_SIZE": "16",
    "RUBINE_EVAL_SIM_SIZE": "8",
    "RUBINE_EVAL_SIM_DAYS": "8",
    "RUBINE_WORLD2_LLM": "false",
    "RUBINE_WORLD2_AUTOSTART": "false",
    "RUBINE_MAX_NEW_TOKENS": "24",
    "RUBINE_FRONTEND_DIR": str(_TMP / "no-frontend"),
    "HF_HUB_OFFLINE": "1",
})
for k in ("RUBINE_ANTHROPIC_API_KEY", "RUBINE_TEACHER_OPENAI_BASE_URL", "RUBINE_DATABASE_URL"):
    os.environ.pop(k, None)

TOKENIZER_SOURCE = os.environ.get("RUBINE_TEST_TOKENIZER", "Qwen/Qwen2.5-0.5B-Instruct")


def _make_tiny_model(path: Path) -> None:
    import torch
    from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM
    tok = AutoTokenizer.from_pretrained(TOKENIZER_SOURCE)
    cfg = Qwen2Config(vocab_size=len(tok), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=2048,
                      tie_word_embeddings=True, bos_token_id=tok.bos_token_id, eos_token_id=tok.eos_token_id)
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(cfg)
    model.generation_config.eos_token_id = tok.eos_token_id
    model.save_pretrained(path)
    tok.save_pretrained(path)


_MODEL_DIR = _TMP / "tiny-model"
_make_tiny_model(_MODEL_DIR)
os.environ["RUBINE_BASE_MODEL"] = str(_MODEL_DIR)
os.environ["RUBINE_BASE_MODEL_REVISION"] = ""

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def tiny_model_dir() -> Path:
    return _MODEL_DIR


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from rubine.db import init_db, session_scope
    from rubine.llm.registry import ensure_base_version
    init_db()
    with session_scope() as s:
        ensure_base_version(s)
    yield
