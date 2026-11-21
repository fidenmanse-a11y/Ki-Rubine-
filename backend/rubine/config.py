"""Central configuration for Rubine AI.

All settings can be overridden with environment variables prefixed with
``RUBINE_`` or via a ``.env`` file in the repository root.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RUBINE_",
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths & storage -------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    # Default: SQLite in data_dir. Set to e.g. postgresql+psycopg://user:pw@host/db
    database_url: str | None = None
    frontend_dir: Path = REPO_ROOT / "frontend" / "out"

    # --- Server ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None

    # --- Security ----------------------------------------------------------
    admin_password: SecretStr = SecretStr("")
    session_hours: int = 24 * 14
    # Extra origins allowed for state-changing requests (e.g. https://pc.tailnet.ts.net
    # when a reverse proxy rewrites the Host header). Same-origin is always allowed.
    allowed_origins: list[str] = []
    login_max_failures: int = 5
    login_window_seconds: int = 300

    # --- Base model --------------------------------------------------------
    # Qwen2.5-0.5B-Instruct: Apache-2.0, multilingual (incl. German), runs on CPU.
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    # Pinned revision for reproducible training (None = latest).
    base_model_revision: str | None = "7ae557604adf67be50417f59c2c2f167def9a775"
    base_model_license: str = "Apache-2.0"
    load_model_on_startup: bool = True
    device: str = "auto"  # auto | cpu | cuda | mps
    max_new_tokens: int = 512
    max_context_tokens: int = 3072
    max_loaded_adapters: int = 4

    # --- Rubine World 2.0 (society simulation) --------------------------------
    world2_enabled: bool = True
    world2_autostart: bool = True
    world2_llm: bool = True  # residents may use the Rubine model for significant decisions

    # --- Classic simulation (v0.1 Smallville town; opt-in since 0.2) --------
    sim_enabled: bool = False
    sim_autostart: bool = True
    sim_tick_seconds: float = 2.0
    sim_minutes_per_tick: int = 10
    sim_llm_enabled: bool = True
    sim_llm_max_tokens: int = 80
    sim_task_interval_ticks: int = 18  # ~3 simulated hours
    # Which backend the agents think with: "rubine" (active Rubine model) or
    # "openai_compatible" (e.g. a local Ollama / llama.cpp / vLLM server).
    agent_backend: str = "rubine"

    # --- Teachers ----------------------------------------------------------
    teacher_openai_base_url: str | None = None  # e.g. http://localhost:11434/v1 (Ollama)
    teacher_openai_model: str | None = None  # e.g. qwen2.5:7b-instruct
    teacher_openai_api_key: SecretStr = SecretStr("")
    teacher_local_hf_model: str | None = None  # e.g. Qwen/Qwen2.5-1.5B-Instruct
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-opus-5-5"

    # --- Training limits ---------------------------------------------------
    max_concurrent_jobs: int = 1
    max_queued_jobs: int = 5
    max_train_steps: int = 5000
    max_train_examples: int = 50000
    max_seq_len: int = 512
    job_timeout_hours: float = 24.0
    # Self-generated (agent_verified) examples may make up at most this
    # fraction of a dataset. The rest must come from independent sources.
    max_self_generated_fraction: float = 0.5
    eval_set_size: int = 64
    # Frozen evaluation sets used for every comparison. eval-sim-v1 comes from a held-out
    # simulation world (separate seed) and tests simulation-grounded skills.
    eval_sets: str = "eval-v1,eval-sim-v1"
    eval_sim_size: int = 32
    eval_sim_days: int = 40
    # Promotion gate: candidate must reach >= parent accuracy + min_delta
    gate_min_delta: float = 0.0
    # ... and no task family may drop by more than this (absolute).
    gate_max_family_drop: float = 0.15

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'rubine.db').as_posix()}"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.models_dir, self.datasets_dir, self.eval_dir,
                  self.jobs_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)

    def secret_key(self) -> bytes:
        """Return the server signing key, creating it on first use.

        Stored in ``data/secret.key`` (never committed, never logged).
        """
        self.ensure_dirs()
        path = self.data_dir / "secret.key"
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_text(secrets.token_hex(32), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(path)
        return bytes.fromhex(path.read_text(encoding="utf-8").strip())


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings_cache() -> None:
    get_settings.cache_clear()


# Field kept for documentation tooling
__all__ = ["Settings", "get_settings", "reset_settings_cache", "REPO_ROOT", "Field"]
