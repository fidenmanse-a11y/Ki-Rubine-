"""Logging that never writes secrets."""
from __future__ import annotations

import logging
import re

from ..config import get_settings

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|password|passwort|token)(\"?\s*[:=]\s*\"?)([^\s\",]+)"),
    re.compile(r"rubine_session=[^;\s]+"),
]


def _secret_values() -> list[str]:
    s = get_settings()
    vals = [s.admin_password.get_secret_value(), s.anthropic_api_key.get_secret_value(),
            s.teacher_openai_api_key.get_secret_value()]
    return [v for v in vals if v and len(v) >= 6]


def redact(text: str) -> str:
    for v in _secret_values():
        text = text.replace(v, "[REDACTED]")
    for p in _PATTERNS:
        if p.groups >= 3:
            text = p.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = p.sub("[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        red = redact(msg)
        if red != msg:
            record.msg, record.args = red, None
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            h.addFilter(RedactingFilter())
