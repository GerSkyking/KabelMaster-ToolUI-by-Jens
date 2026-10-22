"""Audit-Trail: sicherheits- und datenrelevante Aktionen werden in der DB und im Log festgehalten."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from wtserver.models import AuditLog, User

log = logging.getLogger("wtserver.audit")


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def record(
    db: Session,
    request: Request | None,
    action: str,
    user: User | None = None,
    target: str = "",
    detail: dict[str, Any] | None = None,
    username: str = "",
) -> None:
    """Schreibt einen Audit-Eintrag in die laufende Transaktion (Commit macht der Aufrufer)."""
    name = user.username if user else username
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=name,
            action=action,
            target=target,
            ip=client_ip(request),
            detail=detail or {},
        )
    )
    log.info(action, extra={"audit": True, "user": name, "target": target, "ip": client_ip(request)})
