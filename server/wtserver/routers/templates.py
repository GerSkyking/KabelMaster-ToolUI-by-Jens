"""Globale Vorlagen: Pfad Vorlagen/<Benutzer>/<Name>. Alle angemeldeten Benutzer sehen und nutzen sie,
ändern und löschen dürfen nur der Besitzer und Administratoren."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.models import Template, User, utcnow
from wtserver.security import current_user

router = APIRouter(prefix="/api/templates", tags=["templates"])

TAB_IDS = {"single_search", "batch_search", "highlight", "kmk", "cabinet", "cable", "translate"}
MAX_BYTES = 200_000


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tab_id: str
    data: dict[str, Any]


def _out(t: Template, user: User, full: bool = False) -> dict[str, Any]:
    out = {"id": t.id, "name": t.name, "tab_id": t.tab_id, "owner": t.owner_name,
           "path": f"Vorlagen/{t.owner_name}/{t.name}", "updated_at": t.updated_at,
           "editable": user.role == "admin" or t.owner_id == user.id}
    if full:
        out["data"] = t.data
    return out


def _clean(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    if not cleaned:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ungültiger Vorlagenname.")
    return cleaned


def _check(body: TemplateIn) -> None:
    if body.tab_id not in TAB_IDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unbekannter Reiter.")
    if len(str(body.data)) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Vorlage ist zu groß.")


def _get(db: Session, template_id: int) -> Template:
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vorlage nicht gefunden.")
    return template


def _own(template: Template, user: User) -> None:
    if user.role != "admin" and template.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur der Besitzer darf diese Vorlage ändern.")


@router.get("")
def list_templates(tab_id: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    query = select(Template).order_by(Template.owner_name, Template.name)
    if tab_id:
        query = query.where(Template.tab_id == tab_id)
    return [_out(t, user) for t in db.scalars(query)]


@router.get("/{template_id}")
def read_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _out(_get(db, template_id), user, full=True)


@router.post("", status_code=201)
def save_template(
    body: TemplateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """Legt eine Vorlage an; gleicher Name des gleichen Benutzers im gleichen Reiter überschreibt."""
    _check(body)
    name = _clean(body.name)
    template = db.scalar(select(Template).where(
        Template.owner_id == user.id, Template.tab_id == body.tab_id, Template.name == name))
    if template is None:
        template = Template(owner_id=user.id, owner_name=user.username, tab_id=body.tab_id, name=name, data=body.data)
        db.add(template)
    else:
        template.data, template.updated_at = body.data, utcnow()
    db.flush()
    audit.record(db, request, "template_saved", user, f"template:{template.id}", {"path": f"Vorlagen/{user.username}/{name}"})
    db.commit()
    return _out(template, user, full=True)


@router.put("/{template_id}")
def update_template(
    template_id: int, body: TemplateIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    template = _get(db, template_id)
    _own(template, user)
    _check(body)
    name = _clean(body.name)
    clash = db.scalar(select(Template.id).where(
        Template.owner_id == template.owner_id, Template.tab_id == body.tab_id, Template.name == name,
        Template.id != template.id))
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Es gibt bereits eine Vorlage mit diesem Namen.")
    template.name, template.tab_id, template.data = name, body.tab_id, body.data
    audit.record(db, request, "template_updated", user, f"template:{template.id}")
    db.commit()
    return _out(template, user, full=True)


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    template = _get(db, template_id)
    _own(template, user)
    audit.record(db, request, "template_deleted", user, f"template:{template.id}",
                 {"path": f"Vorlagen/{template.owner_name}/{template.name}"})
    db.delete(template)
    db.commit()
