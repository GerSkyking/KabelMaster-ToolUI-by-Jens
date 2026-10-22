"""Öffentliche Endpunkte für temporäre Share-Links (ohne Login, nur mit gültigem Token)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from wtserver import audit
from wtserver.db import get_db
from wtserver.security import share_from_token
from wtserver.sync import SyncRequest, apply_ops, row_out, rows_since

router = APIRouter(prefix="/api/share", tags=["share"])


@router.get("/{token}")
def open_share(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    link = share_from_token(db, token)
    dataset = link.dataset
    return {
        "mode": link.mode,
        "label": link.label,
        "expires_at": link.expires_at,
        "dataset": {"id": dataset.id, "name": dataset.name, "columns": dataset.columns,
                    "settings": dataset.settings, "seq": dataset.project.seq},
        "rows": [row_out(r) for r in rows_since(db, dataset, 0)],
    }


@router.get("/{token}/rows")
def share_rows(token: str, since: int = 0, db: Session = Depends(get_db)) -> dict:
    link = share_from_token(db, token)
    return {"seq": link.dataset.project.seq, "columns": link.dataset.columns,
            "rows": [row_out(r) for r in rows_since(db, link.dataset, since)]}


@router.post("/{token}/sync")
def share_sync(token: str, body: SyncRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    link = share_from_token(db, token)
    if link.mode != "edit":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dieser Link erlaubt nur Lesen.")
    actor = f"gast:{link.label or link.id}"
    outcome = apply_ops(db, link.dataset, body.ops, actor, allow_structure=False)
    audit.record(db, request, "share_sync", None, f"dataset:{link.dataset_id}", {"ops": len(body.ops)}, username=actor)
    db.commit()
    return outcome
