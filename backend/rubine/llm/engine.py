"""Inference engine: loads the base model once and serves LoRA adapters per version.

All text in the chat is produced here by the selected model – there is no
fallback that fabricates answers. If the model is not loaded, callers get an
``EngineUnavailable`` error that the UI shows to the user.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..config import Settings, get_settings

log = logging.getLogger("rubine.engine")

SYSTEM_PROMPT = (
    "Du bist Rubine, eine eigenständige KI, die lokal auf dem Computer ihres Besitzers läuft. "
    "Du antwortest hilfsbereit, ehrlich und präzise auf Deutsch (oder in der Sprache des Nutzers). "
    "Wenn du etwas nicht weißt, sagst du das offen. Nutze Markdown, wenn es die Antwort klarer macht."
)


class EngineUnavailable(RuntimeError):
    pass


def resolve_device(pref: str = "auto") -> str:
    import torch
    if pref != "auto":
        return pref
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def pick_dtype(device: str) -> Any:
    import torch
    if device == "cuda":
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if device == "mps":
        return torch.float16
    return torch.float32


def _is_local_path(name: str) -> bool:
    return Path(name).exists()


def load_tokenizer(settings: Settings) -> Any:
    from transformers import AutoTokenizer
    kw: dict[str, Any] = {}
    if settings.base_model_revision and not _is_local_path(settings.base_model):
        kw["revision"] = settings.base_model_revision
    tok = AutoTokenizer.from_pretrained(settings.base_model, **kw)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def load_base_model(settings: Settings, device: str) -> Any:
    from transformers import AutoModelForCausalLM
    kw: dict[str, Any] = {"dtype": pick_dtype(device)}
    if settings.base_model_revision and not _is_local_path(settings.base_model):
        kw["revision"] = settings.base_model_revision
    model = AutoModelForCausalLM.from_pretrained(settings.base_model, **kw)
    model.to(device)
    model.eval()
    return model


def build_chat_prompt(tok: Any, messages: list[dict], system: str | None = SYSTEM_PROMPT) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    return tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)


@dataclass
class GenStats:
    tokens: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0

    @property
    def tok_per_s(self) -> float:
        return self.tokens / self.seconds if self.seconds > 0 else 0.0


class ModelEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.status = "idle"  # idle | loading | ready | error | disabled
        self.error: str | None = None
        self.device: str | None = None
        self.tok: Any = None
        self.base: Any = None
        self.peft: Any = None  # PeftModel wrapping self.base once an adapter is loaded
        self._adapters: OrderedDict[str, str] = OrderedDict()  # version_id -> path
        self._lock = threading.Lock()
        self._meta = threading.Lock()
        self._chat_waiting = 0
        self.loaded_at: float | None = None
        self.last_stats: GenStats | None = None

    # ------------------------------------------------------------ loading
    def start_loading(self) -> None:
        if self.status in ("loading", "ready"):
            return
        self.status = "loading"
        threading.Thread(target=self._load, name="rubine-model-load", daemon=True).start()

    def load_blocking(self) -> None:
        self.status = "loading"
        self._load()
        if self.status != "ready":
            raise EngineUnavailable(self.error or "Modell konnte nicht geladen werden")

    def _load(self) -> None:
        try:
            import torch
            torch.set_num_threads(max(1, torch.get_num_threads()))
            self.device = resolve_device(self.settings.device)
            log.info("Lade Basismodell %s auf %s ...", self.settings.base_model, self.device)
            t = time.time()
            self.tok = load_tokenizer(self.settings)
            self.base = load_base_model(self.settings, self.device)
            self.loaded_at = time.time()
            self.status = "ready"
            log.info("Basismodell geladen in %.1fs", time.time() - t)
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            log.exception("Modell konnte nicht geladen werden")

    def info(self) -> dict:
        return {
            "status": self.status, "error": self.error, "device": self.device,
            "base_model": self.settings.base_model, "license": self.settings.base_model_license,
            "loaded_adapters": list(self._adapters), "busy": self._lock.locked(),
            "last_tok_per_s": round(self.last_stats.tok_per_s, 2) if self.last_stats else None,
        }

    # ------------------------------------------------------------ adapters
    def _model_for(self, version_id: str, adapter_path: str | None) -> tuple[Any, str | None]:
        """Return (model, adapter_name). Must be called with self._lock held."""
        if self.status != "ready":
            raise EngineUnavailable(self.error or f"Modell nicht bereit (Status: {self.status})")
        if not adapter_path:
            return (self.peft or self.base), None
        if not Path(adapter_path).exists():
            raise EngineUnavailable(f"Adapter für {version_id} nicht gefunden")
        name = version_id.replace("-", "_").replace(".", "_")
        if name not in self._adapters:
            from peft import PeftModel
            if self.peft is None:
                self.peft = PeftModel.from_pretrained(self.base, adapter_path, adapter_name=name)
            else:
                self.peft.load_adapter(adapter_path, adapter_name=name)
            self.peft.eval()
            self._adapters[name] = adapter_path
            while len(self._adapters) > self.settings.max_loaded_adapters:
                old, _ = self._adapters.popitem(last=False)
                self.peft.delete_adapter(old)
        self._adapters.move_to_end(name)
        self.peft.set_adapter(name)
        return self.peft, name

    def unload_adapter(self, version_id: str) -> None:
        name = version_id.replace("-", "_").replace(".", "_")
        with self._lock:
            if self.peft is not None and name in self._adapters:
                self._adapters.pop(name)
                self.peft.delete_adapter(name)

    # ------------------------------------------------------------ prompts
    def _encode(self, messages: list[dict], system: str | None, max_new_tokens: int) -> Any:
        budget = max(256, self.settings.max_context_tokens - max_new_tokens)
        msgs = list(messages)
        while True:
            prompt = build_chat_prompt(self.tok, msgs, system)
            enc = self.tok(prompt, return_tensors="pt", add_special_tokens=False)
            if enc["input_ids"].shape[1] <= budget or len(msgs) <= 1:
                break
            msgs = msgs[1:]  # drop oldest turn
            while msgs and msgs[0]["role"] != "user":
                msgs = msgs[1:]
        return enc.to(self.device)

    def _gen_kwargs(self, max_new_tokens: int, temperature: float, top_p: float) -> dict:
        kw: dict[str, Any] = {"max_new_tokens": max_new_tokens, "pad_token_id": self.tok.pad_token_id,
                              "repetition_penalty": 1.08}
        if temperature > 0:
            kw.update(do_sample=True, temperature=temperature, top_p=top_p)
        else:
            kw.update(do_sample=False, temperature=None, top_p=None, top_k=None)
        return kw

    # ------------------------------------------------------------ generation
    def stream(self, messages: list[dict], *, version_id: str, adapter_path: str | None,
               max_new_tokens: int | None = None, temperature: float = 0.7, top_p: float = 0.9,
               system: str | None = SYSTEM_PROMPT, stop_event: threading.Event | None = None
               ) -> Iterator[str]:
        """Yield text chunks. Chat requests have priority over simulation work."""
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        if self.status != "ready":
            raise EngineUnavailable(self.error or f"Modell nicht bereit (Status: {self.status})")
        max_new = min(max_new_tokens or self.settings.max_new_tokens, 2048)
        stop_event = stop_event or threading.Event()

        class _Stop(StoppingCriteria):
            def __call__(self, input_ids: Any, scores: Any, **kw: Any) -> bool:  # type: ignore[override]
                return stop_event.is_set()

        with self._meta:
            self._chat_waiting += 1
        self._lock.acquire()
        with self._meta:
            self._chat_waiting -= 1
        thread: threading.Thread | None = None
        try:
            model, adapter = self._model_for(version_id, adapter_path)
            enc = self._encode(messages, system, max_new)
            streamer = TextIteratorStreamer(self.tok, skip_prompt=True, skip_special_tokens=True, timeout=300)
            errors: list[BaseException] = []
            stats = GenStats(prompt_tokens=int(enc["input_ids"].shape[1]))

            def run() -> None:
                t0 = time.time()
                try:
                    ctx = model.disable_adapter() if (self.peft is not None and adapter is None) else nullcontext()
                    with torch.inference_mode(), ctx:
                        out = model.generate(**enc, streamer=streamer,
                                             stopping_criteria=StoppingCriteriaList([_Stop()]),
                                             **self._gen_kwargs(max_new, temperature, top_p))
                    stats.tokens = int(out.shape[1] - enc["input_ids"].shape[1])
                except BaseException as e:  # noqa: BLE001
                    errors.append(e)
                    streamer.text_queue.put(streamer.stop_signal)
                finally:
                    stats.seconds = time.time() - t0

            thread = threading.Thread(target=run, name="rubine-generate", daemon=True)
            thread.start()
            for chunk in streamer:
                if chunk:
                    yield chunk
            thread.join()
            if errors:
                raise EngineUnavailable(f"Generierung fehlgeschlagen: {errors[0]}")
            self.last_stats = stats
        finally:
            stop_event.set()
            if thread is not None:
                thread.join(timeout=600)
            self._lock.release()

    def generate(self, messages: list[dict], *, version_id: str, adapter_path: str | None,
                 max_new_tokens: int = 128, temperature: float = 0.7, top_p: float = 0.9,
                 system: str | None = SYSTEM_PROMPT, background: bool = False,
                 wait_timeout: float = 0.5) -> str | None:
        """Non-streaming generation. ``background=True`` (simulation) yields to chat
        traffic and returns ``None`` instead of waiting when the model is busy."""
        import torch
        if self.status != "ready":
            raise EngineUnavailable(self.error or f"Modell nicht bereit (Status: {self.status})")
        if background:
            if self._chat_waiting > 0 or not self._lock.acquire(timeout=wait_timeout):
                return None
        else:
            self._lock.acquire()
        try:
            model, adapter = self._model_for(version_id, adapter_path)
            enc = self._encode(messages, system, max_new_tokens)
            ctx = model.disable_adapter() if (self.peft is not None and adapter is None) else nullcontext()
            t0 = time.time()
            with torch.inference_mode(), ctx:
                out = model.generate(**enc, **self._gen_kwargs(max_new_tokens, temperature, top_p))
            new = out[0][enc["input_ids"].shape[1]:]
            self.last_stats = GenStats(tokens=int(new.shape[0]), seconds=time.time() - t0,
                                       prompt_tokens=int(enc["input_ids"].shape[1]))
            return self.tok.decode(new, skip_special_tokens=True).strip()
        finally:
            self._lock.release()


_engine: ModelEngine | None = None


def get_engine() -> ModelEngine:
    global _engine
    if _engine is None:
        _engine = ModelEngine()
    return _engine


def set_engine(engine: ModelEngine | None) -> None:
    global _engine
    _engine = engine
