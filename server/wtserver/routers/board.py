"""Whiteboard aus Haftnotizen: eines je Projekt und ein gemeinsames für alle Projekte (project_id fehlt)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.db import get_db
from wtserver.models import BoardNote, User, utcnow
from wtserver.scope import check_scope
from wtserver.security import current_user

router = APIRouter(prefix="/api/board", tags=["board"])

COLORS = "^(yellow|green|blue|pink|orange|gray)$"
LIMIT = 2000.0  # Zeichenfläche in Pixeln; hält verirrte Notizen im sichtbaren Bereich


class NoteIn(BaseModel):
    project_id: int | None = None
    text: str = Field(default="", max_length=4000)
    color: str = Field(default="yellow", pattern=COLORS)
    x: float = Field(default=20, ge=0, le=LIMIT)
    y: float = Field(default=20, ge=0, le=LIMIT)
    w: float = Field(default=200, ge=100, le=800)
    h: float = Field(default=140, ge=80, le=800)


class NotePatch(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    color: str | None = Field(default=None, pattern=COLORS)
    x: float | None = Field(default=None, ge=0, le=LIMIT)
    y: float | None = Field(default=None, ge=0, le=LIMIT)
    w: float | None = Field(default=None, ge=100, le=800)
    h: float | None = Field(default=None, ge=80, le=800)


def note_out(n: BoardNote) -> dict:
    return {"id": n.id, "project_id": n.project_id, "text": n.text, "color": n.color, "x": n.x, "y": n.y,
            "w": n.w, "h": n.h, "created_by": n.created_by, "updated_by": n.updated_by, "updated_at": n.updated_at}


@router.get("")
def list_notes(project_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    check_scope(db, user, project_id)
    stmt = select(BoardNote).where(BoardNote.project_id == project_id if project_id is not None
                                   else BoardNote.project_id.is_(None)).order_by(BoardNote.id)
    return [note_out(n) for n in db.scalars(stmt)]


@router.post("", status_code=201)
def create_note(body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    check_scope(db, user, body.project_id, "editor")
    note = BoardNote(**body.model_dump(), created_by=user.username, updated_by=user.username)
    db.add(note)
    db.commit()
    return note_out(note)


def _get(db: Session, user: User, note_id: int) -> BoardNote:
    note = db.get(BoardNote, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notiz nicht gefunden.")
    check_scope(db, user, note.project_id, "editor")
    return note


@router.patch("/{note_id}")
def patch_note(note_id: int, body: NotePatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    note = _get(db, user, note_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(note, key, value)
    note.updated_by, note.updated_at = user.username, utcnow()
    db.commit()
    return note_out(note)


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_get(db, user, note_id))
    db.commit()
