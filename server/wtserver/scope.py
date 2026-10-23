"""Gemeinsame Hilfen für Funktionen, die je Projekt ODER projektübergreifend ("ohne Projekt") arbeiten."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.config import Settings
from wtserver.models import Project, ProjectMember, User
from wtserver.security import get_project


def member_project_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(db.scalars(select(Project.id)))
    return list(db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)))


def check_scope(db: Session, user: User, project_id: int | None, need: str = "viewer") -> None:
    """Projektbezug prüfen. Ohne Projekt (None) dürfen alle angemeldeten Benutzer lesen und schreiben."""
    if project_id is not None:
        get_project(db, user, project_id, need)


def project_names(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {p.id: p.name for p in db.scalars(select(Project).where(Project.id.in_(ids)))}


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_day(value: str, field: str = "Datum") -> str:
    """JJJJ-MM-TT prüfen; gibt den Wert zurück."""
    try:
        if not _DAY.match(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} muss als JJJJ-MM-TT angegeben werden.") from None
    return value


def tzinfo(settings: Settings):
    from zoneinfo import ZoneInfo

    try:
        return ZoneInfo(settings.timezone)
    except Exception:  # tzdata fehlt (z. B. unter Windows)
        return timezone.utc


def to_local(value: datetime | None, tz) -> datetime | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(tz)


def day_start(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def day_end(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
