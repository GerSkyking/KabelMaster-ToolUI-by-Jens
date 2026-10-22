"""Datensätze (importierte Excel-Listen): Metadaten, Zeilen, Synchronisation, Analyse, Export, Share-Links."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from core.cable.cable_analysis import CableColumns, analyze
from core.io.excel_reader import ExcelImportError
from wtserver import audit, tabular
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import Dataset, Row, ShareLink, User, purge_datasets, utcnow
from wtserver.routers.projects import project_file
from wtserver.security import current_user, get_dataset, get_project, new_share_token, project_role
from wtserver.sync import SyncRequest, apply_ops, row_out, rows_since

router = APIRouter(prefix="/api", tags=["datasets"])

_SETTING_KEYS = {"mapping", "ignore_short", "min_length", "auto_date"}
MAPPING_KEYS = ("cable_id", "cross_section", "target_length", "start", "end", "pulled_length", "date")


class ImportIn(BaseModel):
    file: str
    name: str = ""


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    settings: dict[str, Any] | None = None
    add_columns: list[str] = Field(default_factory=list, max_length=50)


class ShareIn(BaseModel):
    label: str = ""
    mode: str = Field(default="view", pattern="^(view|edit)$")
    hours: int | None = Field(default=None, ge=1, le=24 * 365)


def dataset_out(db: Session, user: User, dataset: Dataset) -> dict:
    return {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "name": dataset.name,
        "source_file": dataset.source_file,
        "columns": dataset.columns,
        "settings": dataset.settings,
        "seq": dataset.project.seq,
        "role": project_role(db, user, dataset.project),
        "updated_at": dataset.updated_at,
    }


@router.post("/projects/{project_id}/datasets", status_code=201)
def import_dataset(
    project_id: int, body: ImportIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = get_project(db, user, project_id, "editor")
    path = project_file(settings, project, body.file)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Datei nicht gefunden.")
    try:
        columns, rows = tabular.read_rows(path)
    except ExcelImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    dataset = Dataset(project_id=project.id, name=body.name.strip() or path.stem, source_file=path.name,
                      columns=columns, settings={})
    db.add(dataset)
    db.flush()
    project.seq += 1
    now = utcnow()
    db.execute(insert(Row), [  # ein Bulk-INSERT statt tausender Einzelobjekte
        {"dataset_id": dataset.id, "idx": i, "data": row, "rev": 1, "seq": project.seq, "deleted": False,
         "updated_at": now, "updated_by": user.username}
        for i, row in enumerate(rows)
    ])
    audit.record(db, request, "dataset_imported", user, f"dataset:{dataset.id}", {"file": path.name, "rows": len(rows)})
    db.commit()
    return dataset_out(db, user, dataset)


@router.get("/datasets/{dataset_id}")
def read_dataset(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return dataset_out(db, user, get_dataset(db, user, dataset_id))


@router.patch("/datasets/{dataset_id}")
def update_dataset(
    dataset_id: int, body: DatasetPatch, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "editor")
    if body.name:
        dataset.name = body.name.strip()
    if body.settings is not None:
        merged = {**dataset.settings, **{k: v for k, v in body.settings.items() if k in _SETTING_KEYS}}
        dataset.settings = merged
    new = [c.strip() for c in body.add_columns if c.strip() and c.strip() not in dataset.columns]
    if new:
        dataset.columns = [*dataset.columns, *dict.fromkeys(new)]
        dataset.project.seq += 1  # Clients erkennen so die geänderte Spaltenliste
    audit.record(db, request, "dataset_updated", user, f"dataset:{dataset.id}", {"new_columns": new})
    db.commit()
    return dataset_out(db, user, dataset)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    dataset = get_dataset(db, user, dataset_id, "owner")
    audit.record(db, request, "dataset_deleted", user, f"dataset:{dataset.id}", {"name": dataset.name})
    purge_datasets(db, [dataset.id])
    db.delete(dataset)
    db.commit()


@router.get("/datasets/{dataset_id}/rows")
def read_rows(
    dataset_id: int, since: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    dataset = get_dataset(db, user, dataset_id)
    return {"seq": dataset.project.seq, "columns": dataset.columns,
            "rows": [row_out(r) for r in rows_since(db, dataset, since)]}


@router.post("/datasets/{dataset_id}/sync")
def sync_dataset(
    dataset_id: int, body: SyncRequest, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "editor")
    outcome = apply_ops(db, dataset, body.ops, user.username)
    changed = sum(1 for r in outcome["results"] if r["status"] != "error")
    audit.record(db, request, "dataset_sync", user, f"dataset:{dataset.id}",
                 {"ops": len(body.ops), "ok": changed, "via": getattr(request.state, "auth_method", "")})
    db.commit()
    return outcome


def _live_rows(db: Session, dataset: Dataset) -> list[dict[str, Any]]:
    rows = db.scalars(select(Row).where(Row.dataset_id == dataset.id, Row.deleted.is_(False)).order_by(Row.idx, Row.id))
    return [r.data for r in rows]


@router.get("/datasets/{dataset_id}/export")
def export_dataset(
    dataset_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    dataset = get_dataset(db, user, dataset_id)
    content = tabular.to_xlsx_bytes(dataset.columns, _live_rows(db, dataset), dataset.name)
    audit.record(db, request, "dataset_exported", user, f"dataset:{dataset.id}")
    db.commit()
    filename = quote(f"{dataset.name}.xlsx")
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/datasets/{dataset_id}/analysis")
def dataset_analysis(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Kabelzug-Stand je Querschnitt, berechnet mit derselben Logik wie die Desktop-App (core/cable)."""
    dataset = get_dataset(db, user, dataset_id)
    mapping = dataset.settings.get("mapping") or {}
    required = [k for k in MAPPING_KEYS if k != "date"]
    if any(mapping.get(k) not in dataset.columns for k in required):
        raise HTTPException(status.HTTP_409_CONFLICT, "Spaltenzuordnung für den Kabelzug ist unvollständig.")
    frame = tabular.build_dataframe(dataset.columns, _live_rows(db, dataset))
    columns = CableColumns(**{k: mapping.get(k) or "" for k in MAPPING_KEYS})
    result = analyze(frame, columns, bool(dataset.settings.get("ignore_short")),
                     float(dataset.settings.get("min_length") or 0))

    def stats(g) -> dict:
        return {"label": g.label, "total": g.total, "done": g.done, "open": g.open,
                "percent": round(g.percent_count, 1), "meters_total": g.meters_total,
                "meters_done": g.meters_done, "meters_open": g.meters_open,
                "percent_meters": round(g.percent_meters, 1)}

    return {"groups": [stats(g) for g in result.groups], "total": stats(result.total), "ignored": result.ignored}


# ---- Share-Links (temporärer Zugriff für Externe) ----

@router.get("/datasets/{dataset_id}/shares")
def list_shares(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    dataset = get_dataset(db, user, dataset_id, "owner")
    links = db.scalars(select(ShareLink).where(ShareLink.dataset_id == dataset.id).order_by(ShareLink.id.desc()))
    return [{"id": s.id, "label": s.label, "mode": s.mode, "expires_at": s.expires_at,
             "revoked": s.revoked, "created_at": s.created_at} for s in links]


@router.post("/datasets/{dataset_id}/shares", status_code=201)
def create_share(
    dataset_id: int, body: ShareIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "owner")
    token, token_hash = new_share_token()
    hours = body.hours or settings.share_default_hours
    link = ShareLink(dataset_id=dataset.id, token_hash=token_hash, label=body.label, mode=body.mode,
                     created_by=user.id, expires_at=utcnow() + timedelta(hours=hours))
    db.add(link)
    db.flush()
    audit.record(db, request, "share_created", user, f"dataset:{dataset.id}", {"mode": body.mode, "hours": hours})
    db.commit()
    # Der Klartext-Token wird nur dieses eine Mal ausgegeben
    return {"id": link.id, "url": f"{settings.base_url.rstrip('/')}/s/{token}", "expires_at": link.expires_at,
            "mode": link.mode}


@router.delete("/datasets/{dataset_id}/shares/{share_id}", status_code=204)
def revoke_share(
    dataset_id: int, share_id: int, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> None:
    dataset = get_dataset(db, user, dataset_id, "owner")
    link = db.get(ShareLink, share_id)
    if link is None or link.dataset_id != dataset.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link nicht gefunden.")
    link.revoked = True
    audit.record(db, request, "share_revoked", user, f"dataset:{dataset.id}", {"share": share_id})
    db.commit()
