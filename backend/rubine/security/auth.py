"""Single-owner authentication.

* The owner password lives in ``RUBINE_ADMIN_PASSWORD`` (.env, never committed).
* Login issues an HMAC-signed session token, delivered as an HttpOnly,
  SameSite=Strict cookie (and usable as ``Authorization: Bearer`` for scripts).
* Changing the password invalidates all sessions (token embeds a password fingerprint).
* Failed logins are rate limited per client IP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from ..config import get_settings

COOKIE_NAME = "rubine_session"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def password_configured() -> bool:
    return len(get_settings().admin_password.get_secret_value()) >= 8


def _pw_fingerprint() -> str:
    pw = get_settings().admin_password.get_secret_value().encode()
    return hmac.new(get_settings().secret_key(), b"pw:" + pw, hashlib.sha256).hexdigest()[:16]


def check_password(candidate: str) -> bool:
    if not password_configured():
        return False
    expected = get_settings().admin_password.get_secret_value().encode()
    # compare digests so length differences don't leak through timing
    return hmac.compare_digest(hashlib.sha256(candidate.encode()).digest(),
                               hashlib.sha256(expected).digest())


def issue_token() -> str:
    s = get_settings()
    payload = {"sub": "owner", "exp": int(time.time()) + s.session_hours * 3600,
               "pw": _pw_fingerprint()}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(s.secret_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token or not password_configured():
        return False
    body, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(get_settings().secret_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, json.JSONDecodeError):
        return False
    if payload.get("exp", 0) < time.time():
        return False
    return hmac.compare_digest(str(payload.get("pw", "")), _pw_fingerprint())


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_auth(request: Request) -> None:
    """FastAPI dependency protecting every private endpoint."""
    if not verify_token(token_from_request(request)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")


class LoginRateLimiter:
    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        window = get_settings().login_window_seconds
        q = self._fails[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def check(self, key: str) -> None:
        with self._lock:
            q = self._prune(key, time.time())
            if len(q) >= get_settings().login_max_failures:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    "Zu viele Fehlversuche. Bitte später erneut versuchen.")

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_limiter = LoginRateLimiter()
