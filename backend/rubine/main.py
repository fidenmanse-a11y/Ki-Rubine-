"""FastAPI application: API + static PWA frontend on a single port."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .chat.router import models_router
from .chat.router import router as chat_router
from .config import get_settings
from .db import backup_sqlite, init_db, session_scope
from .jobs.manager import get_manager
from .lab.router import router as lab_router
from .llm import registry
from .llm.engine import get_engine
from .security.auth import (COOKIE_NAME, check_password, issue_token, login_limiter, password_configured,
                            require_auth, token_from_request, verify_token)
from .security.logging_setup import setup_logging
from .world.router import router as world_router

log = logging.getLogger("rubine")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    st = get_settings()
    setup_logging()
    if not password_configured():
        log.warning("RUBINE_ADMIN_PASSWORD ist nicht gesetzt (mind. 8 Zeichen) – Anmeldung unmöglich. "
                    "Führe scripts/setup aus oder setze das Passwort in .env.")
    backup_sqlite("startup")
    init_db()
    with session_scope() as s:
        registry.ensure_base_version(s)
    from .training.evalset import ensure_eval_set
    ensure_eval_set()
    eng = get_engine()
    if st.load_model_on_startup:
        eng.start_loading()
    else:
        eng.status = "disabled"
    manager = get_manager()
    manager.start()
    world = None
    if st.sim_enabled:
        from .world.simulation import get_world
        world = get_world()
        world.start()
        if not st.sim_autostart:
            world.running = False
    yield
    if world is not None:
        await world.shutdown()
    await asyncio.to_thread(manager.shutdown)


class SecurityHeaders(BaseHTTPMiddleware):
    """Security headers + same-origin check for state-changing requests (CSRF defence)."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin:
                host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
                if urlparse(origin).netloc != host and origin.rstrip("/") not in get_settings().allowed_origins:
                    return JSONResponse({"detail": "Ungültige Herkunft (Origin)"}, status_code=403)
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp


class Login(BaseModel):
    password: str


def create_app() -> FastAPI:
    st = get_settings()
    app = FastAPI(title="Rubine AI", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeaders)

    @app.get("/api/health")
    def health() -> dict:
        # Public, minimal: no private data.
        return {"ok": True, "version": __version__, "auth_configured": password_configured(),
                "model_status": get_engine().status}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response) -> dict:
        key = request.client.host if request.client else "unknown"
        login_limiter.check(key)
        if not check_password(body.password):
            login_limiter.fail(key)
            raise HTTPException(401, "Falsches Passwort")
        login_limiter.reset(key)
        token = issue_token()
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", secure=secure,
                            max_age=st.session_hours * 3600, path="/")
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request) -> dict:
        return {"authenticated": verify_token(token_from_request(request))}

    @app.get("/api/info", dependencies=[Depends(require_auth)])
    def info() -> dict:
        return {"version": __version__, "engine": get_engine().info(), "base_model": st.base_model,
                "base_model_revision": st.base_model_revision, "license": st.base_model_license,
                "sim_enabled": st.sim_enabled, "agent_backend": st.agent_backend}

    app.include_router(chat_router)
    app.include_router(models_router)
    app.include_router(world_router)
    app.include_router(lab_router)

    # ---- static PWA (Next.js export) ----
    front = Path(st.frontend_dir)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404)
        if not front.exists():
            return JSONResponse({"detail": "Frontend nicht gebaut. Führe 'npm run build' in frontend/ aus."},
                                status_code=503)
        root = front.resolve()
        cand = (root / path).resolve()
        if root not in cand.parents and cand != root:
            raise HTTPException(404)
        for c in (cand, cand / "index.html", cand.with_suffix(".html")):
            if c.is_file():
                headers = {}
                if c.name == "sw.js":
                    headers = {"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"}
                elif "/_next/static/" in c.as_posix():
                    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
                return FileResponse(c, headers=headers)
        return FileResponse(root / "404.html", status_code=404) if (root / "404.html").exists() \
            else JSONResponse({"detail": "Nicht gefunden"}, status_code=404)

    return app


app = create_app()
