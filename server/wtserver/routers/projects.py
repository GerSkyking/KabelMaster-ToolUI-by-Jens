"""Projekte (je Projekt ein Arbeitsverzeichnis mit den Excel-Dateien), Mitglieder und Dateiverwaltung."""
from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from wtserver import audit, tabular
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import BoardNote, CalendarFeed, Dataset, Project, ProjectMember, ScheduleEvent, ShopRequest, User, WorkLog, purge_datasets
from wtserver.security import PROJECT_RANK, current_user, get_project, project_role

router = APIRouter(prefix="/api/projects", tags=["projects"])

ALLOWED_UPLOADS = {".xlsx", ".xls", ".pdf", ".csv"}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class MemberIn(BaseModel):
    username: str
    role: str = Field(pattern="^(owner|editor|viewer)$")


def project_dir(settings: Settings, project: Project) -> Path:
    path = settings.projects_dir / project.slug / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip()
    base = re.sub(r"[^\w .()+-]", "_", base)
    if not base or base.startswith("."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültiger Dateiname.")
    return base[:200]


def project_file(settings: Settings, project: Project, name: str) -> Path:
    folder = project_dir(settings, project).resolve()
    path = (folder / safe_filename(name)).resolve()
    if folder not in path.parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültiger Dateiname.")
    return path


def _slug(db: Session, settings: Settings, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "projekt"
    slug = base
    while db.scalar(select(Project.id).where(Project.slug == slug)) or (settings.projects_dir / slug).exists():
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def project_out(db: Session, user: User, project: Project) -> dict:
    return {
        "id": project.id,
        "slug": project.slug,
        "name": project.name,
        "description": project.description,
        "role": project_role(db, user, project),
        "seq": project.seq,
        "created_at": project.created_at,
        "datasets": [{"id": d.id, "name": d.name} for d in project.datasets],
    }


@router.get("")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    query = select(Project).order_by(Project.name)
    if user.role != "admin":
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return [project_out(db, user, p) for p in db.scalars(query).unique()]


@router.post("", status_code=201)
def create_project(
    body: ProjectIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = Project(slug=_slug(db, settings, body.name), name=body.name.strip(), description=body.description,
                      created_by=user.id)
    project.members.append(ProjectMember(user_id=user.id, role="owner"))
    db.add(project)
    db.flush()
    project_dir(settings, project)
    audit.record(db, request, "project_created", user, f"project:{project.id}", {"slug": project.slug})
    db.commit()
    return project_out(db, user, project)


@router.get("/{project_id}")
def read_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return project_out(db, user, get_project(db, user, project_id))


@router.patch("/{project_id}")
def update_project(
    project_id: int, body: ProjectIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, user, project_id, "owner")
    project.name, project.description = body.name.strip(), body.description
    audit.record(db, request, "project_updated", user, f"project:{project.id}")
    db.commit()
    return project_out(db, user, project)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> None:
    """Entfernt Projekt, Datensätze und Zeilen aus der Datenbank. Dateien im Arbeitsverzeichnis bleiben erhalten."""
    project = get_project(db, user, project_id, "owner")
    audit.record(db, request, "project_deleted", user, f"project:{project.id}", {"slug": project.slug})
    purge_datasets(db, [d.id for d in project.datasets])
    for model in (ShopRequest, BoardNote, WorkLog, ScheduleEvent, CalendarFeed):
        db.execute(delete(model).where(model.project_id == project.id))
    db.delete(project)
    db.commit()


# ---- Mitglieder ----

@router.get("/{project_id}/members")
def list_members(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, user, project_id)
    return [{"user_id": m.user_id, "username": m.user.username, "display_name": m.user.display_name, "role": m.role}
            for m in project.members]


@router.put("/{project_id}/members")
def set_member(
    project_id: int, body: MemberIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    project = get_project(db, user, project_id, "owner")
    target = db.scalar(select(User).where(User.username == body.username.strip()))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Benutzer nicht gefunden.")
    member = next((m for m in project.members if m.user_id == target.id), None)
    if member is None:
        project.members.append(ProjectMember(user_id=target.id, role=body.role))
    else:
        member.role = body.role
    audit.record(db, request, "member_set", user, f"project:{project.id}", {"user": target.username, "role": body.role})
    db.commit()
    return {"user_id": target.id, "username": target.username, "role": body.role}


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: int, user_id: int, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> None:
    project = get_project(db, user, project_id, "owner")
    member = next((m for m in project.members if m.user_id == user_id), None)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mitglied nicht gefunden.")
    owners = [m for m in project.members if m.role == "owner"]
    if member.role == "owner" and len(owners) == 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Das Projekt braucht mindestens einen Besitzer.")
    project.members.remove(member)
    audit.record(db, request, "member_removed", user, f"project:{project.id}", {"user_id": user_id})
    db.commit()


# ---- Dateien im Arbeitsverzeichnis ----

@router.get("/{project_id}/files")
def list_files(
    project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    project = get_project(db, user, project_id)
    imported = {d.source_file for d in db.scalars(select(Dataset).where(Dataset.project_id == project.id))}
    return [
        {"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime, "imported": p.name in imported}
        for p in sorted(project_dir(settings, project).iterdir()) if p.is_file()
    ]


@router.post("/{project_id}/files", status_code=201)
async def upload_file(
    project_id: int, request: Request, file: UploadFile = File(...),
    user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = get_project(db, user, project_id, "editor")
    target = project_file(settings, project, file.filename or "")
    if target.suffix.lower() not in ALLOWED_UPLOADS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Dateityp nicht erlaubt (erlaubt: {', '.join(sorted(ALLOWED_UPLOADS))}).")
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    tmp = target.with_name(target.name + ".part")
    try:
        with tmp.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Datei größer als {settings.max_upload_mb} MB.")
                handle.write(chunk)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    audit.record(db, request, "file_uploaded", user, f"project:{project.id}", {"file": target.name, "bytes": written})
    db.commit()
    return {"name": target.name, "size": written}


@router.get("/{project_id}/files/{name}/sheets")
def file_sheets(
    project_id: int, name: str, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Blattnamen einer Excel-Datei (für die Auswahl beim Import)."""
    project = get_project(db, user, project_id)
    path = project_file(settings, project, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")
    try:
        return {"sheets": tabular.sheet_names(path)}
    except Exception as exc:  # noqa: BLE001 - defekte Datei: als Importfehler melden
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Datei nicht lesbar: {exc}") from exc


@router.get("/{project_id}/files/{name}")
def download_file(
    project_id: int, name: str, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    project = get_project(db, user, project_id)
    path = project_file(settings, project, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")
    return FileResponse(path, filename=path.name)


@router.delete("/{project_id}/files/{name}", status_code=204)
def delete_file(
    project_id: int, name: str, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    project = get_project(db, user, project_id, "editor")
    path = project_file(settings, project, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")
    trash = path.parent.parent / "trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(path), trash / f"{secrets.token_hex(3)}_{path.name}")  # Papierkorb statt endgültigem Löschen
    audit.record(db, request, "file_deleted", user, f"project:{project.id}", {"file": path.name})
    db.commit()
