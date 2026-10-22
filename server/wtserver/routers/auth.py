"""Anmeldung: lokal, LDAP, OpenID Connect und generisches OAuth2 - alle gleichzeitig nutzbar."""
from __future__ import annotations

import logging

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit, ldap_auth
from wtserver.accounts import provision_external
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import User, utcnow
from wtserver.security import (
    COOKIE_NAME,
    create_session_token,
    current_user,
    hash_password,
    throttle,
    verify_password,
)

log = logging.getLogger("wtserver.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])
oauth = OAuth()
_registered = False


def register_oauth_clients(settings: Settings) -> None:
    global _registered
    if _registered:
        return
    _registered = True
    if settings.oidc_enabled:
        oauth.register(
            "oidc",
            server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            client_kwargs={"scope": settings.oidc_scopes},
        )
    if settings.oauth2_enabled:
        oauth.register(
            "oauth2",
            authorize_url=settings.oauth2_authorize_url,
            access_token_url=settings.oauth2_token_url,
            client_id=settings.oauth2_client_id,
            client_secret=settings.oauth2_client_secret,
            client_kwargs={"scope": settings.oauth2_scopes},
        )


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "email": user.email,
        "role": user.role,
        "provider": user.provider,
    }


def set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user, settings),
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.get("/config")
def auth_config(settings: Settings = Depends(get_settings)) -> dict:
    """Welche Anmeldearten das Login-Formular anbieten soll."""
    return {
        "local": settings.local_login_enabled,
        "ldap": settings.ldap_enabled,
        "oidc": settings.oidc_name if settings.oidc_enabled else None,
        "oauth2": settings.oauth2_name if settings.oauth2_enabled else None,
    }


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    ip = audit.client_ip(request)
    username = body.username.strip()
    if throttle.blocked(ip, username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Zu viele Fehlversuche. Bitte später erneut versuchen.")

    user: User | None = None
    local = db.scalar(select(User).where(User.username == username, User.provider == "local"))
    if local is not None and settings.local_login_enabled and verify_password(body.password, local.password_hash):
        user = local
    elif local is None and settings.ldap_enabled:
        identity = ldap_auth.authenticate(settings, username, body.password)
        if identity is not None:
            user = provision_external(
                db, settings, "ldap", identity.dn, identity.username, identity.email,
                identity.display_name, identity.is_admin if settings.ldap_admin_group_dn else None,
            )

    if user is None or not user.is_active:
        throttle.fail(ip, username)
        audit.record(db, request, "login_failed", username=username)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Benutzername oder Passwort falsch.")

    throttle.reset(ip, username)
    user.last_login_at = utcnow()
    audit.record(db, request, "login", user, detail={"provider": user.provider})
    db.commit()
    set_session_cookie(response, user, settings)
    return user_payload(user)


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_payload(user)


@router.post("/password")
def change_password(
    body: PasswordBody,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if user.provider != "local":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Das Passwort wird beim externen Anbieter verwaltet.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aktuelles Passwort falsch.")
    if len(body.new_password) < 10:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Das neue Passwort muss mindestens 10 Zeichen lang sein.")
    user.password_hash = hash_password(body.new_password)
    audit.record(db, request, "password_changed", user)
    db.commit()
    return {"ok": True}


# ---- OpenID Connect / OAuth2 ----

def _client(name: str, settings: Settings):
    register_oauth_clients(settings)
    enabled = settings.oidc_enabled if name == "oidc" else settings.oauth2_enabled
    if name not in ("oidc", "oauth2") or not enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anmeldeart nicht aktiviert.")
    return getattr(oauth, name)


@router.get("/{provider}/login")
async def external_login(provider: str, request: Request, settings: Settings = Depends(get_settings)):
    client = _client(provider, settings)
    return await client.authorize_redirect(request, f"{settings.base_url.rstrip('/')}/api/auth/{provider}/callback")


@router.get("/{provider}/callback")
async def external_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    client = _client(provider, settings)
    try:
        token = await client.authorize_access_token(request)
        if provider == "oidc":
            info = token.get("userinfo") or await client.userinfo(token=token)
            groups = info.get(settings.oidc_groups_claim) or []
            user = provision_external(
                db, settings, "oidc", str(info["sub"]),
                info.get("preferred_username") or info.get("email") or str(info["sub"]),
                info.get("email", ""), info.get("name", ""),
                (settings.oidc_admin_group in groups) if settings.oidc_admin_group else None,
            )
        else:
            resp = await client.get(settings.oauth2_userinfo_url, token=token)
            resp.raise_for_status()
            info = resp.json()
            user = provision_external(
                db, settings, "oauth2", str(info[settings.oauth2_id_field]),
                str(info.get(settings.oauth2_username_field) or info[settings.oauth2_id_field]),
                info.get(settings.oauth2_email_field) or "", info.get(settings.oauth2_name_field) or "",
            )
    except (OAuthError, KeyError, ValueError) as exc:
        log.warning("%s-Anmeldung fehlgeschlagen: %s", provider, exc)
        audit.record(db, request, "login_failed", username=provider, detail={"error": str(exc)[:200]})
        db.commit()
        return RedirectResponse("/login?error=extern", status_code=302)

    if user is None or not user.is_active:
        audit.record(db, request, "login_denied", username=provider)
        db.commit()
        return RedirectResponse("/login?error=gesperrt", status_code=302)
    audit.record(db, request, "login", user, detail={"provider": provider})
    db.commit()
    redirect = RedirectResponse("/", status_code=302)
    set_session_cookie(redirect, user, settings)
    return redirect
