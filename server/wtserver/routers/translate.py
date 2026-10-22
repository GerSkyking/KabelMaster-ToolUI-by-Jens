"""Übersetzer-Reiter: Quelle wählen (andere Liste oder Datei des Projekts), Vorschau, Anwenden, Excel-Download."""
from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.io.excel_reader import ExcelImportError
from wtserver import audit, tabular, translate
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import Dataset, Row, User
from wtserver.routers.projects import project_dir, project_file
from wtserver.security import current_user, get_dataset
from wtserver.sync import apply_values

router = APIRouter(prefix="/api/datasets/{dataset_id}/translate", tags=["translate"])

SOURCE_FILES = (".xlsx", ".xls", ".csv")
SOURCE_PREVIEW_ROWS = 12
_cache: dict[tuple, tuple[list[str], list[dict[str, Any]]]] = {}


class SourceRef(BaseModel):
    kind: Literal["dataset", "file"]
    dataset_id: int | None = None
    file: str = ""


class MappingIn(BaseModel):
    source: str
    target: str = Field(max_length=200)
    mode: Literal["empty", "overwrite"] = "overwrite"


class TranslateIn(BaseModel):
    source: SourceRef
    key_a: str
    key_b: str
    ignore_case: bool = True
    ignore_separators: bool = False
    duplicates: Literal["first", "last", "skip"] = "first"
    mappings: list[MappingIn] = Field(default_factory=list, max_length=100)


def _load_source(db: Session, user: User, dataset: Dataset, ref: SourceRef, settings: Settings):
    if ref.kind == "dataset":
        other = get_dataset(db, user, ref.dataset_id or 0)
        rows = db.scalars(select(Row).where(Row.dataset_id == other.id, Row.deleted.is_(False))
                          .order_by(Row.idx, Row.id))
        return list(other.columns), [{c: r.data.get(c) for c in other.columns} for r in rows]
    path = project_file(settings, dataset.project, ref.file)
    if path.suffix.lower() not in SOURCE_FILES or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quelldatei nicht gefunden (erlaubt: .xlsx, .xls, .csv).")
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _cache:
        try:
            _cache[key] = tabular.read_rows(path)
        except ExcelImportError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        while len(_cache) > 4:
            _cache.pop(next(iter(_cache)))
    return _cache[key]


def _options(body: TranslateIn) -> translate.Options:
    return translate.Options(
        key_a=body.key_a, key_b=body.key_b, ignore_case=body.ignore_case, ignore_separators=body.ignore_separators,
        duplicates=body.duplicates,
        mappings=[translate.Mapping(m.source, m.target.strip(), m.mode) for m in body.mappings])


def _plan(db: Session, user: User, dataset: Dataset, body: TranslateIn, settings: Settings):
    columns_b, rows_b = _load_source(db, user, dataset, body.source, settings)
    options = _options(body)
    try:
        translate.validate(options, list(dataset.columns), columns_b)
    except translate.TranslateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    rows_a = [(r.id, r.data) for r in db.scalars(
        select(Row).where(Row.dataset_id == dataset.id, Row.deleted.is_(False)).order_by(Row.idx, Row.id))]
    return rows_a, translate.make_plan(rows_a, list(dataset.columns), rows_b, options)


@router.get("/sources")
def sources(
    dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    dataset = get_dataset(db, user, dataset_id)
    files = [p.name for p in sorted(project_dir(settings, dataset.project).iterdir())
             if p.is_file() and p.suffix.lower() in SOURCE_FILES]
    return {
        "project_id": dataset.project_id,
        "datasets": [{"id": d.id, "name": d.name} for d in dataset.project.datasets if d.id != dataset.id],
        "files": files,
    }


@router.post("/source")
def source_info(
    dataset_id: int, ref: SourceRef, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Spalten und erste Zeilen der Quelle, damit man den Schlüssel (z. B. die W-Nummern) dort sehen kann."""
    dataset = get_dataset(db, user, dataset_id)
    columns, rows = _load_source(db, user, dataset, ref, settings)
    return {"columns": columns, "total": len(rows),
            "rows": [[row.get(c) for c in columns] for row in rows[:SOURCE_PREVIEW_ROWS]]}


@router.post("/preview")
def preview(
    dataset_id: int, body: TranslateIn, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    dataset = get_dataset(db, user, dataset_id)
    _, plan = _plan(db, user, dataset, body, settings)
    return {"stats": plan.stats, "new_columns": plan.new_columns, "sample": plan.sample,
            "unmatched_keys": plan.unmatched_keys}


@router.post("/apply")
def apply(
    dataset_id: int, body: TranslateIn, request: Request, user: User = Depends(current_user),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "editor")
    _, plan = _plan(db, user, dataset, body, settings)
    if plan.new_columns:
        dataset.columns = [*dataset.columns, *plan.new_columns]
        dataset.project.seq += 1  # Clients erkennen so die geänderte Spaltenliste
    touched = apply_values(db, dataset, plan.changes, user.username, kind="translate")
    audit.record(db, request, "translate_applied", user, f"dataset:{dataset.id}",
                 {"rows": touched, "cells": plan.stats["changed_cells"], "new_columns": plan.new_columns,
                  "source": body.source.model_dump()})
    db.commit()
    return {"changed_rows": touched, "changed_cells": plan.stats["changed_cells"], "new_columns": plan.new_columns,
            "stats": plan.stats}


@router.post("/export")
def export(
    dataset_id: int, body: TranslateIn, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Excel mit den eingetragenen Werten; die gespeicherte Liste bleibt unverändert."""
    dataset = get_dataset(db, user, dataset_id)
    rows_a, plan = _plan(db, user, dataset, body, settings)
    columns, rows = translate.apply_to_rows(rows_a, list(dataset.columns), plan)
    name = f"{dataset.name}_uebersetzt.xlsx"
    return Response(
        tabular.to_xlsx_bytes(columns, rows), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
