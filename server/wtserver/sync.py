"""Zeilen-Synchronisation für Offline-Clients (PWA, Windows-App).

Protokoll
---------
* Pull:  Zeilen mit seq > since (seq ist ein pro Projekt hochgezählter Änderungs-Zähler).
* Push:  Liste von Operationen. Eine Änderung enthält nur die geänderten Felder (``patch``), die Werte
  vor der Änderung (``base``) und die Revision, auf der der Client aufgebaut hat (``base_rev``).
  Der Server übernimmt jedes Feld einzeln. Hat ein anderer Client dasselbe Feld inzwischen auf einen
  anderen Wert gesetzt, wird genau dieses Feld als Konflikt gemeldet und nicht überschrieben;
  alle anderen Felder derselben Zeile werden trotzdem übernommen.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wtserver.models import Conflict, Dataset, Project, Row, RowChange, utcnow


class SyncOp(BaseModel):
    id: int | None = None  # None = neue Zeile
    client_id: str | None = None  # wird bei Neuanlage im Ergebnis zurückgegeben
    base_rev: int = 0
    patch: dict[str, Any] = Field(default_factory=dict)
    base: dict[str, Any] = Field(default_factory=dict)
    delete: bool = False


class SyncRequest(BaseModel):
    ops: list[SyncOp] = Field(default_factory=list, max_length=5000)


def row_out(row: Row) -> dict[str, Any]:
    return {
        "id": row.id,
        "idx": row.idx,
        "data": row.data,
        "rev": row.rev,
        "seq": row.seq,
        "deleted": row.deleted,
        "updated_by": row.updated_by,
    }


def rows_since(db: Session, dataset: Dataset, since: int) -> list[Row]:
    query = select(Row).where(Row.dataset_id == dataset.id).order_by(Row.idx, Row.id)
    if since > 0:
        query = query.where(Row.seq > since)  # inkl. gelöschter Zeilen, damit Clients sie entfernen
    else:
        query = query.where(Row.deleted.is_(False))
    return list(db.scalars(query))


def _log(db: Session, dataset: Dataset, row: Row, field: str, old: Any, new: Any, actor: str, kind: str) -> None:
    db.add(RowChange(dataset_id=dataset.id, row_id=row.id, field=field, old=old, new=new, kind=kind, by=actor))


def _register_conflict(db: Session, dataset: Dataset, row: Row, field: str, base: Any, value: Any, actor: str) -> None:
    """Merkt den Konflikt vor; es gibt je (Zeile, Feld) höchstens einen offenen, der letzte Vorschlag gilt."""
    pending = db.scalar(select(Conflict).where(
        Conflict.dataset_id == dataset.id, Conflict.row_id == row.id, Conflict.field == field,
        Conflict.status == "pending"))
    if pending is None:
        pending = Conflict(dataset_id=dataset.id, row_id=row.id, field=field, base_value=base,
                           server_value=row.data.get(field), server_by=row.updated_by, server_at=row.updated_at)
        db.add(pending)
    pending.proposed_value, pending.proposed_by, pending.proposed_at = value, actor, utcnow()


def apply_values(
    db: Session, dataset: Dataset, changes: dict[int, dict[str, Any]], actor: str, kind: str = "edit"
) -> int:
    """Setzt Feldwerte direkt (ohne Konfliktprüfung), z. B. beim Abhaken oder Entscheiden. Liefert Anzahl geänderter Zeilen."""
    project = db.scalar(select(Project).where(Project.id == dataset.project_id).with_for_update())
    seq, touched = project.seq, 0
    for row_id, patch in changes.items():
        row = db.get(Row, row_id)
        if row is None or row.dataset_id != dataset.id or row.deleted:
            continue
        applied = {f: v for f, v in patch.items() if f in dataset.columns and row.data.get(f) != v}
        if not applied:
            continue
        for field, value in applied.items():
            _log(db, dataset, row, field, row.data.get(field), value, actor, kind)
        seq += 1
        row.data = {**row.data, **applied}
        row.rev, row.seq, row.updated_by, row.updated_at = row.rev + 1, seq, actor, utcnow()
        touched += 1
    project.seq = seq
    return touched


def apply_ops(
    db: Session, dataset: Dataset, ops: list[SyncOp], actor: str, allow_structure: bool = True
) -> dict[str, Any]:
    """Wendet die Operationen an (eine Transaktion) und liefert Ergebnis je Operation plus neuen seq-Stand."""
    project = db.scalar(select(Project).where(Project.id == dataset.project_id).with_for_update())
    seq = project.seq
    columns = set(dataset.columns)
    next_idx = (db.scalar(select(func.max(Row.idx)).where(Row.dataset_id == dataset.id)) or -1) + 1
    results: list[dict[str, Any]] = []

    for op in ops:
        result: dict[str, Any] = {"client_id": op.client_id, "id": op.id, "status": "ok", "conflicts": []}
        results.append(result)
        unknown = [f for f in op.patch if f not in columns]
        if unknown:
            result.update(status="error", error=f"Unbekannte Spalten: {', '.join(unknown)}")
            continue

        if op.id is None:
            if not allow_structure:
                result.update(status="error", error="Neue Zeilen sind hier nicht erlaubt.")
                continue
            seq += 1
            row = Row(dataset_id=dataset.id, idx=next_idx, data=dict(op.patch), rev=1, seq=seq,
                      updated_by=actor, updated_at=utcnow())
            next_idx += 1
            db.add(row)
            db.flush()
            _log(db, dataset, row, "*", None, None, actor, "create")
            result.update(id=row.id, row=row_out(row))
            continue

        row = db.get(Row, op.id)
        if row is None or row.dataset_id != dataset.id:
            result.update(status="error", error="Zeile nicht gefunden.")
            continue

        if op.delete:
            if not allow_structure:
                result.update(status="error", error="Löschen ist hier nicht erlaubt.")
                continue
            if not row.deleted:
                seq += 1
                row.deleted, row.rev, row.seq = True, row.rev + 1, seq
                row.updated_by, row.updated_at = actor, utcnow()
                _log(db, dataset, row, "*", None, None, actor, "delete")
            result["row"] = row_out(row)
            continue

        stale = op.base_rev != row.rev
        applied: dict[str, Any] = {}
        for field, value in op.patch.items():
            current = row.data.get(field)
            if stale and current != op.base.get(field) and current != value:
                result["conflicts"].append(field)
                _register_conflict(db, dataset, row, field, op.base.get(field), value, actor)
            elif current != value:
                applied[field] = value
        if applied:
            seq += 1
            for field, value in applied.items():
                _log(db, dataset, row, field, row.data.get(field), value, actor, "edit")
            row.data = {**row.data, **applied}
            row.rev, row.seq = row.rev + 1, seq
            row.updated_by, row.updated_at = actor, utcnow()
        if result["conflicts"]:
            result["status"] = "conflict"
        result["row"] = row_out(row)

    project.seq = seq
    db.commit()
    return {"results": results, "seq": seq}
