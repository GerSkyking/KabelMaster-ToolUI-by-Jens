"""Konflikte beim Abgleich: wenn zwei Personen dasselbe Feld unterschiedlich ändern, entscheidet jemand."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.models import Conflict, Dataset, Row, User, utcnow
from wtserver.security import current_user, get_dataset, get_project
from wtserver.sync import apply_values

router = APIRouter(prefix="/api", tags=["conflicts"])


class ResolveIn(BaseModel):
    choice: str = Field(pattern="^(server|proposed)$")  # server = aktueller Wert bleibt, proposed = Vorschlag übernehmen


def conflict_out(db: Session, dataset: Dataset, c: Conflict) -> dict[str, Any]:
    row = db.get(Row, c.row_id)
    label_col = (dataset.settings.get("mapping") or {}).get("cable_id")
    return {
        "id": c.id, "dataset_id": dataset.id, "dataset_name": dataset.name, "row_id": c.row_id,
        "row_number": (row.idx + 1) if row else None,
        "label": str(row.data.get(label_col, "")) if row and label_col else "",
        "field": c.field, "base_value": c.base_value,
        "server_value": row.data.get(c.field) if row and c.status == "pending" else c.server_value,
        "server_by": c.server_by, "server_at": c.server_at,
        "proposed_value": c.proposed_value, "proposed_by": c.proposed_by, "proposed_at": c.proposed_at,
        "status": c.status, "resolution": c.resolution, "resolved_by": c.resolved_by, "resolved_at": c.resolved_at,
    }


def pending_count(db: Session, dataset_ids: list[int]) -> int:
    if not dataset_ids:
        return 0
    return len(db.scalars(select(Conflict.id).where(Conflict.dataset_id.in_(dataset_ids), Conflict.status == "pending")).all())


@router.get("/datasets/{dataset_id}/conflicts")
def list_conflicts(
    dataset_id: int, status_filter: str = "pending", user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    dataset = get_dataset(db, user, dataset_id)
    query = select(Conflict).where(Conflict.dataset_id == dataset.id).order_by(Conflict.id.desc()).limit(500)
    if status_filter in ("pending", "resolved"):
        query = query.where(Conflict.status == status_filter)
    return [conflict_out(db, dataset, c) for c in db.scalars(query)]


@router.get("/projects/{project_id}/conflicts")
def project_conflicts(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    project = get_project(db, user, project_id)
    out: list[dict] = []
    for dataset in project.datasets:
        for c in db.scalars(select(Conflict).where(Conflict.dataset_id == dataset.id, Conflict.status == "pending")):
            out.append(conflict_out(db, dataset, c))
    return out


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: int, body: ResolveIn, request: Request,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    conflict = db.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Konflikt nicht gefunden.")
    dataset = get_dataset(db, user, conflict.dataset_id, "editor")
    if conflict.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Konflikt ist bereits entschieden.")
    if body.choice == "proposed":
        apply_values(db, dataset, {conflict.row_id: {conflict.field: conflict.proposed_value}}, user.username, "resolve")
    # Auch ältere offene Konflikte desselben Feldes sind damit entschieden
    for other in db.scalars(select(Conflict).where(
            Conflict.dataset_id == dataset.id, Conflict.row_id == conflict.row_id,
            Conflict.field == conflict.field, Conflict.status == "pending")):
        other.status, other.resolution = "resolved", body.choice
        other.resolved_by, other.resolved_at = user.username, utcnow()
    audit.record(db, request, "conflict_resolved", user, f"dataset:{dataset.id}",
                 {"row": conflict.row_id, "field": conflict.field, "choice": body.choice})
    db.commit()
    return conflict_out(db, dataset, conflict)
