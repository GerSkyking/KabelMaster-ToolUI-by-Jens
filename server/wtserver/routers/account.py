"""API-Keys (für die Windows-App/Skripte), Benutzerverwaltung und Audit-Log."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.models import ApiKey, AuditLog, User, utcnow
from wtserver.security import current_user, hash_password, new_api_key, require_admin

router = APIRouter(prefix="/api", tags=["account"])


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    days: int | None = Field(default=None, ge=1, le=3650)


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=10)
    email: str = ""
    display_name: str = ""
    role: str = Field(default="user", pattern="^(admin|user)$")


class UserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10)


def _key_out(key: ApiKey) -> dict:
    return {"id": key.id, "name": key.name, "prefix": key.prefix, "created_at": key.created_at,
            "last_used_at": key.last_used_at, "expires_at": key.expires_at, "revoked": key.revoked}


@router.get("/api-keys")
def list_keys(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [_key_out(k) for k in db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc()))]


@router.post("/api-keys", status_code=201)
def create_key(
    body: ApiKeyIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    if getattr(request.state, "auth_method", "") == "api_key":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API-Keys können nicht mit einem API-Key erstellt werden.")
    plain, prefix, key_hash = new_api_key()
    key = ApiKey(user_id=user.id, name=body.name, prefix=prefix, key_hash=key_hash,
                 expires_at=utcnow() + timedelta(days=body.days) if body.days else None)
    db.add(key)
    db.flush()
    audit.record(db, request, "api_key_created", user, f"api_key:{key.id}", {"name": body.name})
    db.commit()
    return {**_key_out(key), "key": plain}  # Klartext nur jetzt sichtbar


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(
    key_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    key = db.get(ApiKey, key_id)
    if key is None or (key.user_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API-Key nicht gefunden.")
    key.revoked = True
    audit.record(db, request, "api_key_revoked", user, f"api_key:{key.id}")
    db.commit()


@router.get("/users/lookup")
def lookup_users(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """Benutzernamen-Suche für das Hinzufügen von Projektmitgliedern (nur Name, min. 2 Zeichen)."""
    if len(q.strip()) < 2:
        return []
    like = f"%{q.strip().lower()}%"
    found = db.scalars(select(User).where(User.is_active.is_(True), User.username.like(like)).limit(10))
    return [{"username": u.username, "display_name": u.display_name} for u in found]


# ---- Admin ----

@router.get("/admin/users")
def admin_list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": u.id, "username": u.username, "email": u.email, "display_name": u.display_name,
             "provider": u.provider, "role": u.role, "is_active": u.is_active, "last_login_at": u.last_login_at}
            for u in db.scalars(select(User).order_by(User.username))]


@router.post("/admin/users", status_code=201)
def admin_create_user(
    body: UserIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Benutzername bereits vergeben.")
    user = User(username=body.username, email=body.email, display_name=body.display_name, role=body.role,
                password_hash=hash_password(body.password), provider="local")
    db.add(user)
    db.flush()
    audit.record(db, request, "user_created", admin, f"user:{user.id}", {"role": body.role})
    db.commit()
    return {"id": user.id, "username": user.username}


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: int, body: UserPatch, request: Request,
    admin: User = Depends(require_admin), db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Benutzer nicht gefunden.")
    if user.id == admin.id and (body.is_active is False or body.role == "user"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Du kannst dir nicht selbst die Admin-Rechte entziehen.")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        if user.provider != "local":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passwort wird beim externen Anbieter verwaltet.")
        user.password_hash = hash_password(body.password)
    audit.record(db, request, "user_updated", admin, f"user:{user.id}",
                 {"role": body.role, "is_active": body.is_active, "password": bool(body.password)})
    db.commit()
    return {"id": user.id, "role": user.role, "is_active": user.is_active}


@router.get("/admin/audit")
def admin_audit(
    limit: int = 200, action: str = "", _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[dict]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))
    if action:
        query = query.where(AuditLog.action == action)
    return [{"id": a.id, "ts": a.ts, "username": a.username, "action": a.action, "target": a.target,
             "ip": a.ip, "detail": a.detail} for a in db.scalars(query)]
