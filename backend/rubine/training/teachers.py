"""Teacher models that produce training data for Rubine.

* ``openai_compatible`` – any local OpenAI-compatible server (Ollama, llama.cpp,
  LM Studio, vLLM) running an open-weight model. No cloud needed.
* ``local_hf``          – a (larger) open-weight Hugging Face model loaded in the job process.
* ``anthropic``         – optional, uses *your own* paid Anthropic API key
  (``RUBINE_ANTHROPIC_API_KEY``). A Claude subscription does NOT include API access;
  Rubine never tries to work around that.
* Manual import         – JSONL files (e.g. written by Claude Code during development),
  see ``data.import_jsonl``.

Teacher answers on curriculum tasks are verified against ground truth before
they are approved. Free-form teacher answers stay ``pending`` for human review.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings
from ..llm.engine import SYSTEM_PROMPT

log = logging.getLogger("rubine.teachers")


class Teacher(Protocol):
    name: str
    source: str

    def available(self) -> tuple[bool, str]: ...
    def generate(self, messages: list[dict], max_tokens: int = 400) -> str: ...


class OpenAICompatibleTeacher:
    name = "openai_compatible"
    source = "teacher_local"

    def __init__(self, settings: Settings) -> None:
        self.base_url = (settings.teacher_openai_base_url or "").rstrip("/")
        self.model = settings.teacher_openai_model
        self.key = settings.teacher_openai_api_key.get_secret_value()

    def available(self) -> tuple[bool, str]:
        if not self.base_url or not self.model:
            return False, "RUBINE_TEACHER_OPENAI_BASE_URL und RUBINE_TEACHER_OPENAI_MODEL setzen (z. B. Ollama)."
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=3)
            if r.status_code >= 400:
                return False, f"Server antwortet mit HTTP {r.status_code}"
        except httpx.HTTPError as e:
            return False, f"Nicht erreichbar: {type(e).__name__}"
        return True, f"{self.model} @ {self.base_url}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def generate(self, messages: list[dict], max_tokens: int = 400) -> str:
        r = httpx.post(f"{self.base_url}/chat/completions", headers=self._headers(), timeout=300,
                       json={"model": self.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                             "max_tokens": max_tokens, "temperature": 0.3})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class LocalHFTeacher:
    name = "local_hf"
    source = "teacher_local"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.teacher_local_hf_model
        self.settings = settings
        self._model: Any = None
        self._tok: Any = None

    def available(self) -> tuple[bool, str]:
        if not self.model_name:
            return False, "RUBINE_TEACHER_LOCAL_HF_MODEL setzen (z. B. Qwen/Qwen2.5-1.5B-Instruct)."
        return True, self.model_name

    def _load(self) -> None:
        if self._model is None:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from ..llm.engine import pick_dtype, resolve_device
            self.device = resolve_device(self.settings.device)
            self._tok = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForCausalLM.from_pretrained(self.model_name, dtype=pick_dtype(self.device))
            self._model.to(self.device).eval()

    def generate(self, messages: list[dict], max_tokens: int = 400) -> str:
        import torch
        self._load()
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        prompt = self._tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        enc = self._tok(prompt, return_tensors="pt", add_special_tokens=False).to(self.device)
        with torch.inference_mode():
            out = self._model.generate(**enc, max_new_tokens=max_tokens, do_sample=False, temperature=None,
                                       top_p=None, top_k=None)
        return self._tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()


class AnthropicTeacher:
    name = "anthropic"
    source = "teacher_api"

    def __init__(self, settings: Settings) -> None:
        self.key = settings.anthropic_api_key.get_secret_value()
        self.model = settings.anthropic_model
        self._client: Any = None

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "Optional: eigenen API-Schlüssel in RUBINE_ANTHROPIC_API_KEY hinterlegen (kostenpflichtig)."
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "Paket 'anthropic' nicht installiert (pip install -r backend/requirements-optional.txt)."
        return True, self.model

    def generate(self, messages: list[dict], max_tokens: int = 400) -> str:
        import anthropic
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.key)
        # Server-side refusal fallback is enabled so a policy decline on the
        # primary model is retried on a fallback model inside the same call.
        resp = self._client.beta.messages.create(
            model=self.model, max_tokens=max(max_tokens, 1024), system=SYSTEM_PROMPT,
            messages=[m for m in messages if m["role"] in ("user", "assistant")],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Lehrer-Modell hat die Anfrage abgelehnt")
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def get_teacher(name: str, settings: Settings | None = None) -> Teacher:
    st = settings or get_settings()
    teachers = {"openai_compatible": OpenAICompatibleTeacher, "local_hf": LocalHFTeacher,
                "anthropic": AnthropicTeacher}
    if name not in teachers:
        raise ValueError(f"Unbekannter Lehrer: {name}")
    return teachers[name](st)


def list_teachers(settings: Settings | None = None, probe: bool = True) -> list[dict]:
    st = settings or get_settings()
    out = []
    for name, label in [("openai_compatible", "Lokales Open-Weight-Modell (Ollama/llama.cpp/vLLM)"),
                        ("local_hf", "Lokales Hugging-Face-Modell"),
                        ("anthropic", "Anthropic API (optional, eigener Schlüssel)")]:
        t = get_teacher(name, st)
        ok, detail = t.available() if probe else (False, "nicht geprüft")
        out.append({"name": name, "label": label, "available": ok, "detail": detail, "source": t.source})
    out.append({"name": "manual_import", "label": "Manueller Import (JSONL, z. B. von Claude Code erstellt)",
                "available": True, "detail": "Upload im AI Lab oder CLI", "source": "manual_import"})
    return out
