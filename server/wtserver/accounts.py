"""Benutzerverwaltung: Bootstrap-Admin und Anlegen/Verknüpfen externer Identitäten (LDAP/OIDC/OAuth2)."""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.config import Settings
from wtserver.models import User, utcnow
from wtserver.security import hash_password

log = logging.getLogger("wtserver.accounts")


def _slugify_username(raw: str) -> str:
    cleaned = re.sub(r"[^\w.@-]+", "_", raw.strip().lower())
    return cleaned[:140] or "user"


def unique_username(db: Session, wanted: str) -> str:
    base = _slugify_username(wanted)
    name, counter = base, 2
    while db.scalar(select(User.id).where(User.username == name)) is not None:
        name, counter = f"{base}{counter}", counter + 1
    return name


def ensure_bootstrap_admin(db: Session, settings: Settings) -> None:
    """Legt beim ersten Start den Admin an, sofern ADMIN_PASSWORD gesetzt ist und noch kein Admin existiert."""
    if db.scalar(select(User.id).where(User.role == "admin")) is not None:
        return
    if not settings.admin_password:
        log.warning("Kein Administrator vorhanden und ADMIN_PASSWORD nicht gesetzt - Anmeldung als Admin nicht möglich.")
        return
    db.add(
        User(
            username=settings.admin_username,
            email=settings.admin_email,
            display_name="Administrator",
            password_hash=hash_password(settings.admin_password),
            provider="local",
            role="admin",
        )
    )
    db.commit()
    log.info("Bootstrap-Administrator '%s' angelegt.", settings.admin_username)


def provision_external(
    db: Session,
    settings: Settings,
    provider: str,
    external_id: str,
    username: str,
    email: str = "",
    display_name: str = "",
    is_admin: bool | None = None,
) -> User | None:
    """Findet oder erstellt den Benutzer zu einer externen Identität. None, wenn Auto-Anlage deaktiviert ist.

    is_admin=None lässt die Rolle unverändert; True/False wird bei jedem Login aus der Gruppenmitgliedschaft übernommen."""
    user = db.scalar(select(User).where(User.provider == provider, User.external_id == external_id))
    if user is None:
        if not settings.auto_create_users:
            return None
        user = User(
            username=unique_username(db, username),
            provider=provider,
            external_id=external_id,
            role="admin" if is_admin else "user",
        )
        db.add(user)
    if email:
        user.email = email
    if display_name:
        user.display_name = display_name
    if is_admin is not None and user.id is not None:
        user.role = "admin" if is_admin else "user"
    user.last_login_at = utcnow()
    db.commit()
    return user
