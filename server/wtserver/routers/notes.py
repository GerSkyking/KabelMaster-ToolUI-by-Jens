"""Notizen je Projekt (Markdown). Lesen: alle Mitglieder; Schreiben: Bearbeiter; Löschen: Bearbeiter."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.models import Note, User, utcnow
from wtserver.security import current_user, get_project

router = APIRouter(prefix="/api/projects/{project_id}/notes", tags=["notes"])

MAX_BODY = 200_000


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=MAX_BODY)
    version: int | None = None  # Stand, auf dem die Änderung beruht (nur beim Speichern)


def note_out(note: Note, with_body: bool = True) -> dict:
    out = {"id": note.id, "title": note.title or "Ohne Titel", "version": note.version,
           "created_by": note.created_by, "updated_by": note.updated_by,
           "created_at": note.created_at, "updated_at": note.updated_at}
    if with_body:
        out["body"] = note.body
    else:
        out["preview"] = note.body[:160]
    return out


def _get(db: Session, project_id: int, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None or note.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notiz nicht gefunden.")
    return note


@router.get("")
def list_notes(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    get_project(db, user, project_id)
    notes = db.scalars(select(Note).where(Note.project_id == project_id).order_by(Note.updated_at.desc()))
    return [note_out(n, with_body=False) for n in notes]


@router.post("", status_code=201)
def create_note(
    project_id: int, body: NoteIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    get_project(db, user, project_id, "editor")
    note = Note(project_id=project_id, title=body.title.strip(), body=body.body,
                created_by=user.username, updated_by=user.username)
    db.add(note)
    db.flush()
    audit.record(db, request, "note_created", user, f"project:{project_id}", {"note": note.id})
    db.commit()
    return note_out(note)


@router.get("/{note_id}")
def read_note(project_id: int, note_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_project(db, user, project_id)
    return note_out(_get(db, project_id, note_id))


@router.put("/{note_id}")
def save_note(
    project_id: int, note_id: int, body: NoteIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    get_project(db, user, project_id, "editor")
    note = _get(db, project_id, note_id)
    if body.version is not None and body.version != note.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Die Notiz wurde inzwischen von {note.updated_by or 'jemand anderem'} geändert. "
            "Bitte neu laden (eigenen Text vorher kopieren).")
    note.title, note.body = body.title.strip(), body.body
    note.version += 1
    note.updated_by, note.updated_at = user.username, utcnow()
    audit.record(db, request, "note_updated", user, f"project:{project_id}", {"note": note.id})
    db.commit()
    return note_out(note)


@router.delete("/{note_id}", status_code=204)
def delete_note(
    project_id: int, note_id: int, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> None:
    get_project(db, user, project_id, "editor")
    note = _get(db, project_id, note_id)
    audit.record(db, request, "note_deleted", user, f"project:{project_id}", {"note": note.id, "title": note.title})
    db.delete(note)
    db.commit()
