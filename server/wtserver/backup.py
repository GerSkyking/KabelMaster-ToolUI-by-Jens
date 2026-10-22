"""Sicherungen (ZIP mit JSON), Versionsvergleich und Wiederherstellung je Projekt.

Eine Sicherung enthält Projekte, Mitglieder (nach Benutzername), Listen mit allen Zeilen, Vorlagen und optional die
Excel-Dateien der Projektordner. Zeilen werden beim Vergleich über (Projekt, Liste, Zeilennummer) zugeordnet.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.config import Settings
from wtserver.models import Backup, Dataset, Note, Project, ProjectMember, Row, Template, User, utcnow

log = logging.getLogger("wtserver.backup")
FORMAT_VERSION = 1
MAX_DIFF_ITEMS = 1000


class BackupError(ValueError):
    pass


# ---- Erzeugen ----

def snapshot(db: Session, project_ids: list[int] | None = None) -> dict[str, Any]:
    query = select(Project).order_by(Project.id)
    if project_ids is not None:
        query = query.where(Project.id.in_(project_ids))
    projects = []
    for project in db.scalars(query):
        members = db.execute(select(User.username, ProjectMember.role).join(
            ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project.id)).all()
        datasets = []
        for dataset in project.datasets:
            rows = db.scalars(select(Row).where(Row.dataset_id == dataset.id, Row.deleted.is_(False))
                              .order_by(Row.idx, Row.id))
            datasets.append({"name": dataset.name, "source_file": dataset.source_file, "columns": dataset.columns,
                             "settings": dataset.settings,
                             "rows": [{"idx": r.idx, "data": r.data} for r in rows]})
        projects.append({"slug": project.slug, "name": project.name, "description": project.description,
                         "members": [{"username": u, "role": r} for u, r in members], "datasets": datasets,
                         "notes": [{"title": n.title, "body": n.body, "by": n.updated_by} for n in project.notes]})
    templates = [{"owner": t.owner_name, "tab_id": t.tab_id, "name": t.name, "data": t.data}
                 for t in db.scalars(select(Template).order_by(Template.id))] if project_ids is None else []
    return {"projects": projects, "templates": templates}


def summarize(data: dict[str, Any]) -> dict[str, Any]:
    datasets = [d for p in data["projects"] for d in p["datasets"]]
    return {"projects": len(data["projects"]), "datasets": len(datasets),
            "rows": sum(len(d["rows"]) for d in datasets), "templates": len(data.get("templates", [])),
            "notes": sum(len(p.get("notes", [])) for p in data["projects"])}


def create_backup(db: Session, settings: Settings, kind: str, actor: str, include_files: bool | None = None,
                  project_ids: list[int] | None = None) -> Backup:
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    include_files = settings.backup_include_files if include_files is None else include_files
    data = snapshot(db, project_ids)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"wt-backup-{stamp}-{kind}.zip"
    counter = 1
    while (settings.backups_dir / filename).exists():
        counter += 1
        filename = f"wt-backup-{stamp}-{kind}-{counter}.zip"
    path = settings.backups_dir / filename
    summary = summarize(data)
    manifest = {"format": FORMAT_VERSION, "created": utcnow().isoformat(), "kind": kind, "by": actor,
                "files_included": include_files, "summary": summary}
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("data.json", json.dumps(data, ensure_ascii=False))
        if include_files:
            for project in data["projects"]:
                folder = settings.projects_dir / project["slug"] / "files"
                if folder.is_dir():
                    for file in folder.iterdir():
                        if file.is_file():
                            archive.write(file, f"files/{project['slug']}/{file.name}")
    backup = Backup(filename=filename, kind=kind, created_by=actor, size=path.stat().st_size, summary=summary)
    db.add(backup)
    db.commit()
    log.info("backup_created", extra={"file": filename, "kind": kind, **summary})
    return backup


def prune(db: Session, settings: Settings) -> int:
    old = list(db.scalars(select(Backup).where(Backup.kind == "auto").order_by(Backup.created_at.desc())))[settings.backup_keep:]
    for backup in old:
        (settings.backups_dir / backup.filename).unlink(missing_ok=True)
        db.delete(backup)
    db.commit()
    return len(old)


def backup_path(settings: Settings, backup: Backup) -> Path:
    path = (settings.backups_dir / backup.filename).resolve()
    if settings.backups_dir.resolve() not in path.parents or not path.is_file():
        raise BackupError("Sicherungsdatei nicht gefunden.")
    return path


def load_archive(path: Path) -> dict[str, Any]:
    try:
        with ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            data = json.loads(archive.read("data.json"))
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise BackupError("Keine gültige Sicherungsdatei.") from exc
    if manifest.get("format") != FORMAT_VERSION or "projects" not in data:
        raise BackupError("Unbekanntes Sicherungsformat.")
    return {"manifest": manifest, **data}


# ---- Vergleich ----

def _index(data: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(p["slug"], d["name"]): d for p in data["projects"] for d in p["datasets"]}


def compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Unterschiede zwischen zwei Ständen: neue/entfernte Listen, Zeilen und geänderte Zellen."""
    a, b = _index(old), _index(new)
    result: dict[str, Any] = {"datasets": [], "added_datasets": [], "removed_datasets": [], "truncated": False,
                              "totals": {"added": 0, "removed": 0, "changed_cells": 0}}
    result["added_datasets"] = [f"{p}/{n}" for p, n in b if (p, n) not in a]
    result["removed_datasets"] = [f"{p}/{n}" for p, n in a if (p, n) not in b]
    budget = MAX_DIFF_ITEMS
    for key in a.keys() & b.keys():
        before, after = {r["idx"]: r["data"] for r in a[key]["rows"]}, {r["idx"]: r["data"] for r in b[key]["rows"]}
        added = sorted(after.keys() - before.keys())
        removed = sorted(before.keys() - after.keys())
        changes: list[dict[str, Any]] = []
        count = 0
        for idx in sorted(before.keys() & after.keys()):
            for column in dict.fromkeys([*a[key]["columns"], *b[key]["columns"]]):
                x, y = before[idx].get(column), after[idx].get(column)
                if x != y and not (x in (None, "") and y in (None, "")):
                    count += 1
                    if budget > 0:
                        budget -= 1
                        changes.append({"row": idx + 1, "field": column, "old": x, "new": y})
                    else:
                        result["truncated"] = True
        cols_added = [c for c in b[key]["columns"] if c not in a[key]["columns"]]
        cols_removed = [c for c in a[key]["columns"] if c not in b[key]["columns"]]
        if added or removed or count or cols_added or cols_removed:
            result["datasets"].append({"project": key[0], "dataset": key[1], "rows_added": len(added),
                                       "rows_removed": len(removed), "changed_cells": count, "changes": changes,
                                       "columns_added": cols_added, "columns_removed": cols_removed})
        result["totals"]["added"] += len(added)
        result["totals"]["removed"] += len(removed)
        result["totals"]["changed_cells"] += count
    return result


# ---- Wiederherstellen ----

def restore_project(db: Session, settings: Settings, data: dict[str, Any], slug: str, actor: str,
                    archive_path: Path | None = None) -> dict[str, Any]:
    """Stellt die Listen eines Projekts aus der Sicherung wieder her. Vorhandene Zeilen werden als gelöscht markiert
    (Clients entfernen sie beim nächsten Abgleich), die gesicherten Zeilen werden neu angelegt."""
    saved = next((p for p in data["projects"] if p["slug"] == slug), None)
    if saved is None:
        raise BackupError("Projekt ist in dieser Sicherung nicht enthalten.")
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise BackupError("Das Projekt existiert nicht mehr; bitte zuerst ein Projekt mit diesem Namen anlegen.")
    create_backup(db, settings, "pre-restore", actor, project_ids=[project.id])
    project = db.scalar(select(Project).where(Project.id == project.id).with_for_update())
    seq = project.seq + 1
    restored = 0
    for item in saved["datasets"]:
        dataset = next((d for d in project.datasets if d.name == item["name"]), None)
        if dataset is None:
            dataset = Dataset(project_id=project.id, name=item["name"], source_file=item["source_file"],
                              columns=item["columns"], settings=item["settings"])
            db.add(dataset)
            db.flush()
        else:
            for row in db.scalars(select(Row).where(Row.dataset_id == dataset.id, Row.deleted.is_(False))):
                row.deleted, row.rev, row.seq, row.updated_by, row.updated_at = True, row.rev + 1, seq, actor, utcnow()
            dataset.columns, dataset.settings = item["columns"], item["settings"]
        db.add_all(Row(dataset_id=dataset.id, idx=r["idx"], data=r["data"], rev=1, seq=seq, updated_by=actor)
                   for r in item["rows"])
        restored += len(item["rows"])
    project.seq = seq
    have = {(n.title, n.body) for n in project.notes}
    for note in saved.get("notes", []):  # nur fehlende Notizen zurückholen, vorhandene bleiben unangetastet
        if (note["title"], note["body"]) not in have:
            project.notes.append(Note(title=note["title"], body=note["body"], created_by=note.get("by", ""),
                                      updated_by=note.get("by", "")))
    if archive_path is not None:
        with ZipFile(archive_path) as archive:
            for name in archive.namelist():
                m = re.fullmatch(rf"files/{re.escape(slug)}/([^/\\]+)", name)
                if m:
                    target = settings.projects_dir / slug / "files" / m.group(1)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
    db.commit()
    return {"project": slug, "rows": restored}


def current_snapshot(db: Session) -> dict[str, Any]:
    return snapshot(db)


# ---- Zeitplan ----

def due_for_auto(db: Session, settings: Settings, now: datetime) -> bool:
    if not settings.backup_enabled:
        return False
    try:
        hour, minute = (int(x) for x in settings.backup_time.split(":"))
    except ValueError:
        return False
    if now < now.replace(hour=hour, minute=minute, second=0, microsecond=0):
        return False
    last = db.scalar(select(Backup.created_at).where(Backup.kind == "auto").order_by(Backup.created_at.desc()).limit(1))
    return last is None or last.astimezone().date() < now.astimezone().date()


class BackupScheduler(threading.Thread):
    def __init__(self, session_factory, settings: Settings) -> None:
        super().__init__(daemon=True, name="backup-scheduler")
        self._factory, self._settings = session_factory, settings
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(60):
            try:
                with self._factory() as db:
                    if due_for_auto(db, self._settings, datetime.now().astimezone()):
                        create_backup(db, self._settings, "auto", "system")
                        prune(db, self._settings)
            except Exception:  # noqa: BLE001 - der Zeitplan darf nie den Server beenden
                log.exception("Automatische Sicherung fehlgeschlagen")

    def stop(self) -> None:
        self._halt.set()
