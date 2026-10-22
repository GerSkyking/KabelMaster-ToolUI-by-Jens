"""Übersicht je Projekt/Liste: gezogene und fehlende Kabel je Querschnitt, Prognose, Tagesbericht (TXT)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.cable.cable_analysis import CableColumns, analyze
from core.cable.forecast import SectionForecast, forecast
from core.cable.report import daily_report_text
from wtserver import audit
from wtserver.db import get_db
from wtserver.models import Conflict, Dataset, User
from wtserver.routers.datasets import MAPPING_KEYS
from wtserver.routers.tools import label_columns, load_frame
from wtserver.security import current_user, get_dataset, get_project
from wtserver.sync import apply_values

router = APIRouter(prefix="/api", tags=["overview"])

FORECAST_COLUMN = "prognostizierte Länge"


class ForecastWriteIn(BaseModel):
    only_empty: bool = True


def _mapping(dataset: Dataset) -> dict[str, str | None]:
    return dict(dataset.settings.get("mapping") or {})


def cable_ready(dataset: Dataset) -> bool:
    mapping = _mapping(dataset)
    return all(mapping.get(k) in dataset.columns for k in MAPPING_KEYS if k != "date")


def _section(s: SectionForecast) -> dict[str, Any]:
    return {"label": s.label, "total": s.total, "done": s.done, "open": s.open,
            "percent": round(100.0 * s.done / s.total, 1) if s.total else 0.0,
            "planned_m": round(s.planned_m, 2), "done_m": round(s.done_m, 2),
            "predicted_open_m": round(s.predicted_open_m, 2), "forecast_m": round(s.forecast_m, 2),
            "delta_m": round(s.delta_m, 2), "delta_percent": round(s.delta_percent, 1),
            "basis": s.basis_counts}


def dataset_overview(db: Session, dataset: Dataset) -> dict[str, Any]:
    out: dict[str, Any] = {"id": dataset.id, "name": dataset.name, "ready": cable_ready(dataset)}
    pending = db.scalars(select(Conflict.id).where(Conflict.dataset_id == dataset.id, Conflict.status == "pending")).all()
    out["conflicts"] = len(pending)
    if not out["ready"]:
        return out
    mapping = _mapping(dataset)
    frame = load_frame(db, dataset)
    ignore = bool(dataset.settings.get("ignore_short"))
    min_length = float(dataset.settings.get("min_length") or 0)
    cols = CableColumns(**{k: mapping.get(k) or "" for k in MAPPING_KEYS})
    result = forecast(frame, mapping, ignore, min_length)
    out["sections"] = [_section(s) for s in result.sections]
    out["total"] = _section(result.total)
    out["has_routes"] = bool(mapping.get("target1") in dataset.columns or mapping.get("target2") in dataset.columns)
    analysis = analyze(frame, cols, ignore, min_length)
    out["ignored"] = analysis.ignored
    labeled = label_columns(dataset)
    if labeled:
        out["labeled"] = {t: int(frame[c].map(lambda v: v is not None and str(v).strip() != "").sum())
                          for t, c in labeled.items()}
        out["labeled"]["rows"] = len(frame)
    return out


@router.get("/projects/{project_id}/overview")
def project_overview(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = get_project(db, user, project_id)
    datasets = [dataset_overview(db, d) for d in project.datasets]
    return {"project": {"id": project.id, "name": project.name}, "datasets": datasets,
            "conflicts": sum(d["conflicts"] for d in datasets)}


@router.get("/datasets/{dataset_id}/overview")
def overview(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return dataset_overview(db, get_dataset(db, user, dataset_id))


@router.get("/datasets/{dataset_id}/forecast")
def forecast_rows(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Prognose je offenem Kabel (Zeilen-ID -> Länge + Grundlage)."""
    dataset = get_dataset(db, user, dataset_id)
    if not cable_ready(dataset):
        raise HTTPException(status.HTTP_409_CONFLICT, "Spaltenzuordnung für den Kabelzug ist unvollständig.")
    result = forecast(load_frame(db, dataset), _mapping(dataset), bool(dataset.settings.get("ignore_short")),
                      float(dataset.settings.get("min_length") or 0))
    return {"rows": {str(i): {"length": r.length, "basis": r.basis} for i, r in result.rows.items()}}


@router.post("/datasets/{dataset_id}/forecast/write")
def write_forecast(
    dataset_id: int, body: ForecastWriteIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    """Schreibt die Prognose in die Spalte 'prognostizierte Länge' (wird bei Bedarf angelegt)."""
    dataset = get_dataset(db, user, dataset_id, "editor")
    if not cable_ready(dataset):
        raise HTTPException(status.HTTP_409_CONFLICT, "Spaltenzuordnung für den Kabelzug ist unvollständig.")
    mapping = _mapping(dataset)
    if mapping.get("forecast") not in dataset.columns:
        if FORECAST_COLUMN not in dataset.columns:
            dataset.columns = [*dataset.columns, FORECAST_COLUMN]
            dataset.project.seq += 1
        mapping["forecast"] = FORECAST_COLUMN
        dataset.settings = {**dataset.settings, "mapping": mapping}
    column = mapping["forecast"]
    frame = load_frame(db, dataset)
    result = forecast(frame, mapping, bool(dataset.settings.get("ignore_short")),
                      float(dataset.settings.get("min_length") or 0))
    patch: dict[int, dict[str, Any]] = {}
    for row_id, item in result.rows.items():
        if item.basis == "done" or item.length is None:
            continue
        if body.only_empty and frame.at[row_id, column] not in (None, ""):
            continue
        patch[int(row_id)] = {column: item.length}
    touched = apply_values(db, dataset, patch, user.username, "forecast")
    audit.record(db, request, "forecast_written", user, f"dataset:{dataset.id}", {"rows": touched})
    db.commit()
    return {"changed": touched, "column": column, "seq": dataset.project.seq}


def _parse(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Datum bitte als JJJJ-MM-TT angeben.") from exc


def _txt(text: str, name: str) -> Response:
    return Response(text.encode("utf-8-sig"), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/datasets/{dataset_id}/report.txt")
def dataset_report(
    dataset_id: int, request: Request, start: str = "", end: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> Response:
    dataset = get_dataset(db, user, dataset_id)
    if not cable_ready(dataset):
        raise HTTPException(status.HTTP_409_CONFLICT, "Spaltenzuordnung für den Kabelzug ist unvollständig.")
    text = daily_report_text(load_frame(db, dataset), _mapping(dataset), dataset.name, _parse(start), _parse(end))
    audit.record(db, request, "report_created", user, f"dataset:{dataset.id}")
    db.commit()
    return _txt(text, f"Tagesbericht_{dataset.name}_{datetime.now():%Y-%m-%d}.txt")


@router.get("/projects/{project_id}/report.txt")
def project_report(
    project_id: int, request: Request, start: str = "", end: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> Response:
    project = get_project(db, user, project_id)
    parts = [daily_report_text(load_frame(db, d), _mapping(d), f"{project.name} / {d.name}", _parse(start), _parse(end))
             for d in project.datasets if cable_ready(d)]
    if not parts:
        raise HTTPException(status.HTTP_409_CONFLICT, "Keine Liste mit vollständiger Kabelzug-Zuordnung im Projekt.")
    audit.record(db, request, "report_created", user, f"project:{project.id}")
    db.commit()
    return _txt("\n".join(parts), f"Tagesbericht_{project.name}_{datetime.now():%Y-%m-%d}.txt")
