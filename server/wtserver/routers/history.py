"""Änderungsverlauf einer Liste (wer hat wann welchen Wert geändert) mit Rückgängig für einzelne Änderungen
und für ganze Läufe (z. B. Übersetzer)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.models import Dataset, Row, RowChange, User
from wtserver.security import current_user, get_dataset
from wtserver.sync import apply_values

router = APIRouter(prefix="/api/datasets/{dataset_id}/history", tags=["history"])

PAGE = 300
UNDO_SUFFIX = "-u"


def _labels(db: Session, dataset: Dataset, row_ids: set[int]) -> dict[int, str]:
    """Anzeigename je Zeile: Kabel-ID aus der Zuordnung, sonst erste Spalte; zusätzlich die Zeilennummer."""
    if not row_ids:
        return {}
    column = (dataset.settings.get("mapping") or {}).get("cable_id")
    if column not in dataset.columns:
        column = dataset.columns[0] if dataset.columns else None
    out: dict[int, str] = {}
    for row in db.scalars(select(Row).where(Row.dataset_id == dataset.id, Row.id.in_(row_ids))):
        value = row.data.get(column) if column else None
        out[row.id] = f"{value} (Zeile {row.idx + 1})" if value not in (None, "") else f"Zeile {row.idx + 1}"
    return out


def _change_out(change: RowChange, labels: dict[int, str]) -> dict[str, Any]:
    return {"id": change.id, "row_id": change.row_id, "label": labels.get(change.row_id, f"Zeile #{change.row_id}"),
            "field": change.field, "old": change.old, "new": change.new, "kind": change.kind, "by": change.by,
            "at": change.at, "batch": change.batch}


@router.get("")
def history(
    dataset_id: int, before: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    """Neueste Änderungen zuerst (seitenweise über ``before`` = kleinste bisher gesehene ID)."""
    dataset = get_dataset(db, user, dataset_id)
    query = select(RowChange).where(RowChange.dataset_id == dataset.id)
    if before:
        query = query.where(RowChange.id < before)
    changes = list(db.scalars(query.order_by(RowChange.id.desc()).limit(PAGE)))
    labels = _labels(db, dataset, {c.row_id for c in changes})
    undone = set(db.scalars(select(RowChange.batch).where(
        RowChange.dataset_id == dataset.id, RowChange.kind == "undo", RowChange.batch.is_not(None)).distinct()))
    return {
        "changes": [_change_out(c, labels) for c in changes],
        "undone": sorted(b[: -len(UNDO_SUFFIX)] for b in undone if b and b.endswith(UNDO_SUFFIX)),
        "next": changes[-1].id if len(changes) == PAGE else None,
        "total": db.scalar(select(func.count()).select_from(RowChange).where(RowChange.dataset_id == dataset.id)),
    }


def _revert(db: Session, dataset: Dataset, changes: list[RowChange], actor: str, batch: str | None) -> dict[str, int]:
    """Setzt den alten Wert zurück, aber nur, wenn das Feld seither nicht erneut geändert wurde."""
    patches: dict[int, dict[str, Any]] = {}
    skipped = 0
    rows = {r.id: r for r in db.scalars(select(Row).where(
        Row.dataset_id == dataset.id, Row.id.in_({c.row_id for c in changes})))}
    for change in changes:
        row = rows.get(change.row_id)
        if row is None or row.deleted or change.field == "*" or change.field not in dataset.columns:
            skipped += 1
            continue
        if row.data.get(change.field) != change.new:
            skipped += 1
            continue
        patches.setdefault(row.id, {})[change.field] = change.old
    touched = apply_values(db, dataset, patches, actor, kind="undo", batch=batch)
    return {"rows": touched, "cells": sum(len(p) for p in patches.values()), "skipped": skipped}


@router.post("/changes/{change_id}/revert")
def revert_change(
    dataset_id: int, change_id: int, request: Request, user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "editor")
    change = db.get(RowChange, change_id)
    if change is None or change.dataset_id != dataset.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Änderung nicht gefunden.")
    result = _revert(db, dataset, [change], user.username, None)
    if not result["cells"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Der Wert wurde inzwischen erneut geändert - nichts zurückgesetzt.")
    audit.record(db, request, "change_reverted", user, f"dataset:{dataset.id}", {"change": change.id})
    db.commit()
    return result


@router.post("/batches/{batch}/undo")
def undo_batch(
    dataset_id: int, batch: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, user, dataset_id, "editor")
    changes = list(db.scalars(select(RowChange).where(
        RowChange.dataset_id == dataset.id, RowChange.batch == batch, RowChange.kind != "undo")))
    if not changes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lauf nicht gefunden.")
    if db.scalar(select(RowChange.id).where(
            RowChange.dataset_id == dataset.id, RowChange.batch == batch + UNDO_SUFFIX).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Dieser Lauf wurde bereits rückgängig gemacht.")
    result = _revert(db, dataset, changes, user.username, batch + UNDO_SUFFIX)
    audit.record(db, request, "batch_undone", user, f"dataset:{dataset.id}", {"batch": batch, **result})
    db.commit()
    return result
