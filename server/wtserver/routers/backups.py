"""Sicherungen verwalten (nur Administratoren): erstellen, herunterladen, hochladen, vergleichen, wiederherstellen."""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit, backup as engine
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import Backup, User
from wtserver.security import require_admin

router = APIRouter(prefix="/api/admin/backups", tags=["backups"])


class CreateIn(BaseModel):
    include_files: bool | None = None


class CompareIn(BaseModel):
    old: int
    new: int | None = None  # None = aktueller Stand


class RestoreIn(BaseModel):
    project: str  # slug


def _out(b: Backup) -> dict[str, Any]:
    return {"id": b.id, "filename": b.filename, "kind": b.kind, "created_by": b.created_by,
            "created_at": b.created_at, "size": b.size, "summary": b.summary}


def _get(db: Session, backup_id: int) -> Backup:
    backup = db.get(Backup, backup_id)
    if backup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sicherung nicht gefunden.")
    return backup


def _data(db: Session, settings: Settings, backup_id: int | None) -> dict[str, Any]:
    if backup_id is None:
        return engine.current_snapshot(db)
    try:
        return engine.load_archive(engine.backup_path(settings, _get(db, backup_id)))
    except engine.BackupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("")
def list_backups(_: User = Depends(require_admin), db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> dict:
    items = db.scalars(select(Backup).order_by(Backup.created_at.desc()))
    return {"backups": [_out(b) for b in items],
            "schedule": {"enabled": settings.backup_enabled, "time": settings.backup_time,
                         "keep": settings.backup_keep, "include_files": settings.backup_include_files}}


@router.post("", status_code=201)
def create(body: CreateIn, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings)) -> dict:
    backup = engine.create_backup(db, settings, "manual", user.username, body.include_files)
    audit.record(db, request, "backup_created", user, f"backup:{backup.id}")
    db.commit()
    return _out(backup)


@router.post("/upload", status_code=201)
def upload(request: Request, file: UploadFile = File(...), user: User = Depends(require_admin),
           db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", Path(file.filename or "upload.zip").name)[:120] or "upload.zip"
    name = f"wt-upload-{safe}"
    target = settings.backups_dir / name
    if target.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Eine Sicherung mit diesem Namen existiert bereits.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
    try:
        data = engine.load_archive(Path(tmp.name))
    except engine.BackupError as exc:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    shutil.move(tmp.name, target)
    backup = Backup(filename=name, kind="upload", created_by=user.username, size=target.stat().st_size,
                    summary=engine.summarize(data))
    db.add(backup)
    audit.record(db, request, "backup_uploaded", user, f"backup:{name}")
    db.commit()
    return _out(backup)


@router.get("/{backup_id}/download")
def download(backup_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings)) -> FileResponse:
    backup = _get(db, backup_id)
    try:
        path = engine.backup_path(settings, backup)
    except engine.BackupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    audit.record(db, request, "backup_downloaded", user, f"backup:{backup.id}")
    db.commit()
    return FileResponse(path, media_type="application/zip", filename=backup.filename)


@router.delete("/{backup_id}", status_code=204)
def delete(backup_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db),
           settings: Settings = Depends(get_settings)) -> None:
    backup = _get(db, backup_id)
    (settings.backups_dir / backup.filename).unlink(missing_ok=True)
    audit.record(db, request, "backup_deleted", user, f"backup:{backup.id}")
    db.delete(backup)
    db.commit()


@router.post("/compare")
def compare(body: CompareIn, _: User = Depends(require_admin), db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings)) -> dict:
    return engine.compare(_data(db, settings, body.old), _data(db, settings, body.new))


@router.post("/{backup_id}/restore")
def restore(backup_id: int, body: RestoreIn, request: Request, user: User = Depends(require_admin),
            db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    backup = _get(db, backup_id)
    try:
        path = engine.backup_path(settings, backup)
        result = engine.restore_project(db, settings, engine.load_archive(path), body.project, user.username, path)
    except engine.BackupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    audit.record(db, request, "backup_restored", user, f"backup:{backup.id}", result)
    db.commit()
    return result
