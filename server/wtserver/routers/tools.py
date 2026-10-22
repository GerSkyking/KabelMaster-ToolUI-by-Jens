"""Werkzeuge pro Liste: Einzelsuche, Stapelsuche, Farbmarkierung, KMK, Schrank-Erkennung (Vorschau + Export).
Dazu: KMK-Exportläufe und das Abhaken ("beschriftet Ziel 1/2")."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit, tools
from wtserver.db import get_db
from wtserver.models import Dataset, ExportRun, Row, User
from wtserver.security import current_user, get_dataset
from wtserver.sync import apply_values

router = APIRouter(prefix="/api", tags=["tools"])

LABEL_NAMES = {"1": "beschriftet Ziel 1", "2": "beschriftet Ziel 2"}
LABEL_KEYS = {"1": "labeled1", "2": "labeled2"}
DATE_FORMAT = "%d.%m.%y"


class ToolIn(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    globals: dict[str, Any] | None = None
    term: str = ""
    min_chars: int = 3
    hide_labeled: str = ""  # "" | "1" | "2" | "both" (nur KMK)


class ExportIn(ToolIn):
    formats: list[str] = Field(default_factory=lambda: ["xlsx"])
    cabinet: str = ""  # leer = alle ausgewählten
    cabinets: list[str] | None = None  # Auswahl; None = alle erkannten
    combined: bool = False  # Sammeldatei
    mark: str = ""  # KMK: "" | "1" | "2" | "both" -> sofort abhaken
    note: str = ""


class MarkIn(BaseModel):
    targets: list[str] = Field(default_factory=list)  # "1" und/oder "2"
    unmark: bool = False
    row_ids: list[int] | None = None  # Teilmenge des Laufs; None = alle


def load_frame(db: Session, dataset: Dataset):
    rows = db.scalars(select(Row).where(Row.dataset_id == dataset.id, Row.deleted.is_(False)).order_by(Row.idx, Row.id))
    return tools.make_frame(dataset.columns, [(r.id, r.data) for r in rows])


def label_columns(dataset: Dataset) -> dict[str, str]:
    mapping = dataset.settings.get("mapping") or {}
    return {t: mapping.get(k) for t, k in LABEL_KEYS.items() if mapping.get(k) in dataset.columns}


def ensure_label_columns(dataset: Dataset) -> dict[str, str]:
    """Legt die Spalten 'beschriftet Ziel 1/2' bei Bedarf an und hinterlegt sie in der Zuordnung."""
    mapping = dict(dataset.settings.get("mapping") or {})
    columns = list(dataset.columns)
    changed = False
    for target, key in LABEL_KEYS.items():
        if mapping.get(key) not in columns:
            name = LABEL_NAMES[target]
            if name not in columns:
                columns.append(name)
            mapping[key] = name
            changed = True
    if changed:
        dataset.columns = columns
        dataset.settings = {**dataset.settings, "mapping": mapping}
        dataset.project.seq += 1
    return {t: mapping[k] for t, k in LABEL_KEYS.items()}


def _hide_labeled(frame, dataset: Dataset, mode: str):
    cols = label_columns(dataset)
    wanted = [cols[t] for t in (["1", "2"] if mode == "both" else [mode]) if t in cols]
    if not wanted:
        return frame
    done = frame[wanted].apply(lambda col: col.map(lambda v: v is not None and str(v).strip() != "")).all(axis=1)
    return frame[~done]


def _frame(db: Session, dataset: Dataset, body: ToolIn):
    frame = load_frame(db, dataset)
    if body.hide_labeled in ("1", "2", "both"):
        frame = _hide_labeled(frame, dataset, body.hide_labeled)
    return frame


def _tool_name(tool: str) -> str:
    if tool not in tools.TOOLS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Werkzeug.")
    return tool


def _download(files: list[tools.OutputFile], base: str, extra: dict[str, str] | None = None) -> Response:
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte Excel und/oder PDF wählen.")
    if len(files) == 1:
        f = files[0]
        content, media, name = f.content, f.media_type, f.name
    else:
        content, media, name = tools.zip_files(files), "application/zip", f"{base}.zip"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}", **(extra or {})}
    return Response(content, media_type=media, headers=headers)


@router.post("/datasets/{dataset_id}/tools/{tool}/preview")
def preview(
    dataset_id: int, tool: str, body: ToolIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    dataset = get_dataset(db, user, dataset_id)
    _tool_name(tool)
    frame = _frame(db, dataset, body)
    cfg, glob, original = body.config, body.globals, dataset.name
    try:
        if tool == "search":
            return {"table": tools.payload_json(tools.search_payload(frame, cfg, glob, original, body.term, body.min_chars))}
        if tool == "batch":
            active = [t for t in tools._terms(cfg) if t.enabled and t.term.strip()]
            columns = tools.column_configs(cfg, list(frame.columns))
            engine = tools.SearchEngine()
            search_cols = [c.name for c in columns if c.search_enabled]
            counts = [{"term": t.term, "count": len(engine.search(frame, tools.SearchOptions(
                search_columns=search_cols, term=t.term, min_chars=1)).matched_indices)} for t in active]
            out: dict[str, Any] = {"terms": counts}
            if body.term:
                out["table"] = tools.payload_json(tools.batch_payload(frame, cfg, glob, original, body.term))
            return out
        if tool == "highlight":
            return {"table": tools.payload_json(tools.highlight_payload(frame, cfg, glob, original))}
        if tool == "kmk":
            return tools.kmk_preview(frame, cfg)
        _, _, _, detected = tools.cabinet_setup(frame, cfg)
        out = {"cabinets": [{"name": n, "count": len(ix)} for n, ix in detected.items()]}
        if body.term and body.term in detected:
            out["table"] = tools.payload_json(tools.cabinet_payload(frame, cfg, glob, original, body.term, detected[body.term]))
        return out
    except tools.ToolError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/datasets/{dataset_id}/tools/{tool}/export")
def export(
    dataset_id: int, tool: str, body: ExportIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> Response:
    dataset = get_dataset(db, user, dataset_id)
    _tool_name(tool)
    formats = [f for f in body.formats if f in ("xlsx", "pdf")]
    frame = _frame(db, dataset, body)
    cfg, glob, original = body.config, body.globals, dataset.name
    extra: dict[str, str] = {}
    try:
        if tool == "kmk":
            if body.mark:
                get_dataset(db, user, dataset_id, "editor")
            files, row_ids, warnings = tools.kmk_files(frame, cfg, glob, original, formats)
            run = ExportRun(dataset_id=dataset.id, created_by=user.username, formats=formats, row_ids=row_ids,
                            status={}, note=body.note[:255])
            db.add(run)
            db.flush()
            if body.mark in ("1", "2", "both"):
                _mark(db, dataset, run, ["1", "2"] if body.mark == "both" else [body.mark], False, None, user.username)
            extra = {"X-Run-Id": str(run.id), "X-Warnings": str(len(warnings)), "X-Label-Count": str(len(row_ids))}
            audit.record(db, request, "kmk_exported", user, f"dataset:{dataset.id}", {"run": run.id, "rows": len(row_ids)})
            db.commit()
            return _download(files, f"{original}_KMK", extra)

        if tool == "search":
            payload = tools.search_payload(frame, cfg, glob, original, body.term, body.min_chars)
            files = tools.render(payload, formats)
        elif tool == "highlight":
            files = tools.render(tools.highlight_payload(frame, cfg, glob, original), formats)
        elif tool == "batch":
            terms = [t.term for t in tools._terms(cfg) if t.enabled and t.term.strip()]
            if body.term:
                terms = [body.term]
            if not terms:
                raise tools.ToolError("Keine aktiven Suchbegriffe vorhanden.")
            files = []
            for term in terms:
                files += tools.render(tools.batch_payload(frame, cfg, glob, original, term), formats)
        else:
            _, _, _, detected = tools.cabinet_setup(frame, cfg)
            chosen = body.cabinets if body.cabinets is not None else list(detected)
            if body.cabinet:
                chosen = [body.cabinet]
            chosen = [c for c in chosen if c in detected]
            if not chosen:
                raise tools.ToolError("Keine Schränke zum Exportieren ausgewählt.")
            sheets = [(c, tools.cabinet_payload(frame, cfg, glob, original, c, detected[c])) for c in chosen]
            if body.combined:
                files = tools.combined(sheets, formats, sheets[0][1].filename_stem.rsplit("_", 1)[0] or original)
            else:
                files = [f for _, p in sheets for f in tools.render(p, formats)]
    except tools.ToolError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    audit.record(db, request, "tool_exported", user, f"dataset:{dataset.id}", {"tool": tool, "formats": formats})
    db.commit()
    return _download(files, f"{original}_{tool}")


# ---- KMK: Läufe und Abhaken ----

def run_out(run: ExportRun) -> dict[str, Any]:
    return {"id": run.id, "dataset_id": run.dataset_id, "created_by": run.created_by, "created_at": run.created_at,
            "formats": run.formats, "count": len(run.row_ids), "status": run.status, "note": run.note}


def _mark(db: Session, dataset: Dataset, run: ExportRun, targets: list[str], unmark: bool,
          row_ids: list[int] | None, actor: str) -> int:
    cols = ensure_label_columns(dataset)
    subset = [r for r in run.row_ids if row_ids is None or r in set(row_ids)]
    today = datetime.now().strftime(DATE_FORMAT)
    patch = {r: {cols[t]: ("" if unmark else today) for t in targets if t in cols} for r in subset}
    touched = apply_values(db, dataset, patch, actor, "label")
    state = dict(run.status or {})
    for t in targets:
        if row_ids is None or set(row_ids) >= set(run.row_ids):
            state[t] = "" if unmark else today
        else:
            state[f"{t}_partial"] = today
    run.status = state
    return touched


@router.get("/datasets/{dataset_id}/kmk/runs")
def list_runs(dataset_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    dataset = get_dataset(db, user, dataset_id)
    runs = db.scalars(select(ExportRun).where(ExportRun.dataset_id == dataset.id).order_by(ExportRun.id.desc()).limit(100))
    return [run_out(r) for r in runs]


@router.post("/kmk/runs/{run_id}/mark")
def mark_run(
    run_id: int, body: MarkIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    run = db.get(ExportRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exportlauf nicht gefunden.")
    dataset = get_dataset(db, user, run.dataset_id, "editor")
    targets = [t for t in body.targets if t in LABEL_NAMES]
    if not targets:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte Ziel 1 und/oder Ziel 2 wählen.")
    touched = _mark(db, dataset, run, targets, body.unmark, body.row_ids, user.username)
    audit.record(db, request, "kmk_unmarked" if body.unmark else "kmk_marked", user, f"dataset:{dataset.id}",
                 {"run": run.id, "targets": targets, "rows": touched})
    db.commit()
    return {**run_out(run), "changed": touched, "seq": dataset.project.seq}
