"""FastAPI-Anwendung: API, Request-Logging, Sicherheits-Header und (optional) das gebaute Frontend."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from wtserver.accounts import ensure_bootstrap_admin
from wtserver.config import get_settings
from wtserver.db import SessionLocal, engine
from wtserver.logging_setup import request_id_var, setup_logging
from wtserver import backup
from wtserver.routers import account, auth, backups, conflicts, datasets, overview, projects, share, templates, tools

log = logging.getLogger("wtserver")
settings = get_settings()

_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ensure_bootstrap_admin(db, settings)
    scheduler = backup.BackupScheduler(SessionLocal, settings)
    if settings.backup_enabled:
        scheduler.start()
    log.info("UW Kabel-Master Server gestartet", extra={"env": settings.environment,
             "ldap": settings.ldap_enabled, "oidc": settings.oidc_enabled, "oauth2": settings.oauth2_enabled})
    yield
    scheduler.stop()


app = FastAPI(title="UW Kabel-Master ToolUI by Jens", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax",
                   https_only=settings.cookie_secure, max_age=600, session_cookie="wt_oauth_state")


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unbehandelter Fehler", extra={"path": request.url.path, "method": request.method})
        response = JSONResponse({"detail": "Interner Serverfehler."}, status_code=500)
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    user = getattr(request.state, "user", None)
    if request.url.path != "/api/health/live":
        log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code,
                                   "ms": elapsed, "user": user.username if user else "-"})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.url.path.startswith("/api/docs"):
        response.headers["Content-Security-Policy"] = _CSP
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    request_id_var.reset(token)
    return response


for module in (auth, projects, datasets, conflicts, tools, templates, overview, backups, share, account):
    app.include_router(module.router)


@app.get("/api/health/live", tags=["health"])
def live() -> dict:
    return {"status": "ok"}


@app.get("/api/health", tags=["health"])
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "version": app.version}


@app.get("/api/{rest:path}", include_in_schema=False)
def api_not_found(rest: str):
    raise HTTPException(404, "Nicht gefunden.")


def _mount_frontend(static_dir: Path) -> None:
    root = static_dir.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str):
        candidate = (root / path).resolve()
        if path and root in candidate.parents and candidate.is_file():
            headers = {"Cache-Control": "no-cache"} if candidate.name in ("sw.js", "index.html", "manifest.webmanifest") else {}
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


if settings.static_dir and (settings.static_dir / "index.html").is_file():
    _mount_frontend(settings.static_dir)
