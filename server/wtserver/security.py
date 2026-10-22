"""Passwörter, Sitzungs-Token, API-Keys, Share-Tokens und die Zugriffs-Abhängigkeiten der Routen."""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import ApiKey, Dataset, Project, ProjectMember, ShareLink, User, utcnow

COOKIE_NAME = "wt_session"
API_KEY_PREFIX = "wtk_"
_hasher = PasswordHasher()

# Rolle -> Rang; ein Recht verlangt mindestens den angegebenen Rang
PROJECT_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_session_token(user: User, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(hours=settings.session_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_session_token(token: str, settings: Settings) -> int | None:
    try:
        return int(jwt.decode(token, settings.secret_key, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_api_key() -> tuple[str, str, str]:
    """Liefert (Klartext, Prefix, Hash). Der Klartext wird nur einmalig angezeigt."""
    plain = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plain, plain[:12], sha256(plain)


def new_share_token() -> tuple[str, str]:
    plain = secrets.token_urlsafe(24)
    return plain, sha256(plain)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _user_from_api_key(db: Session, plain: str) -> User | None:
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256(plain)))
    if key is None or key.revoked:
        return None
    if key.expires_at and _as_aware(key.expires_at) < utcnow():
        return None
    key.last_used_at = utcnow()
    db.commit()
    return key.user if key.user.is_active else None


def current_user(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> User:
    """Erkennt den Benutzer aus X-API-Key, Bearer-Token oder Sitzungs-Cookie."""
    api_key = request.headers.get("x-api-key")
    auth_header = request.headers.get("authorization", "")
    bearer = auth_header[7:] if auth_header.lower().startswith("bearer ") else ""
    if not api_key and bearer.startswith(API_KEY_PREFIX):
        api_key, bearer = bearer, ""

    user: User | None = None
    if api_key:
        user = _user_from_api_key(db, api_key)
        request.state.auth_method = "api_key"
    else:
        token = bearer or request.cookies.get(COOKIE_NAME, "")
        user_id = decode_session_token(token, settings) if token else None
        user = db.get(User, user_id) if user_id else None
        request.state.auth_method = "session"
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet.")
    request.state.user = user
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administratorrechte erforderlich.")
    return user


def project_role(db: Session, user: User, project: Project) -> str | None:
    if user.role == "admin":
        return "owner"
    member = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
    )
    return member.role if member else None


def get_project(db: Session, user: User, project_id: int, need: str = "viewer") -> Project:
    project = db.get(Project, project_id)
    role = project_role(db, user, project) if project else None
    # Unberechtigte erfahren nicht, ob ein Projekt existiert
    if project is None or role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projekt nicht gefunden.")
    if PROJECT_RANK[role] < PROJECT_RANK[need]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Keine ausreichende Berechtigung im Projekt.")
    return project


def get_dataset(db: Session, user: User, dataset_id: int, need: str = "viewer") -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datensatz nicht gefunden.")
    get_project(db, user, dataset.project_id, need)
    return dataset


def share_from_token(db: Session, token: str) -> ShareLink:
    link = db.scalar(select(ShareLink).where(ShareLink.token_hash == sha256(token)))
    if link is None or link.revoked or _as_aware(link.expires_at) < utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link ungültig oder abgelaufen.")
    return link


class LoginThrottle:
    """Einfacher Schutz gegen Passwort-Raten: zu viele Fehlversuche sperren (IP, Benutzername) kurz."""

    def __init__(self, max_failures: int = 8, window_s: int = 300) -> None:
        self.max_failures, self.window_s = max_failures, window_s
        self._failures: dict[tuple[str, str], list[float]] = {}

    def _recent(self, key: tuple[str, str]) -> list[float]:
        cutoff = time.monotonic() - self.window_s
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return recent

    def blocked(self, ip: str, username: str) -> bool:
        return len(self._recent((ip, username.lower()))) >= self.max_failures

    def fail(self, ip: str, username: str) -> None:
        self._recent((ip, username.lower())).append(time.monotonic())

    def reset(self, ip: str, username: str) -> None:
        self._failures.pop((ip, username.lower()), None)


throttle = LoginThrottle()
