"""Persönlicher Tagesbericht je Projekt: was habe ich heute gemacht? Nur die eigenen Einträge sind sichtbar.
Die Auswertung fasst nach Tag, Woche, Monat oder Jahr zusammen und zählt zusätzlich die eigenen Listen-Änderungen."""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import Dataset, RowChange, User, WorkLog
from wtserver.scope import day_end, day_start, member_project_ids, project_names, to_local, tzinfo, valid_day
from wtserver.security import current_user, get_project

router = APIRouter(prefix="/api/worklog", tags=["worklog"])


class LogIn(BaseModel):
    project_id: int
    day: str
    text: str = Field(min_length=1, max_length=5000)
    hours: float | None = Field(default=None, ge=0, le=24)


class LogPatch(BaseModel):
    day: str | None = None
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    hours: float | None = Field(default=None, ge=0, le=24)


def log_out(entry: WorkLog, names: dict[int, str]) -> dict:
    return {"id": entry.id, "project_id": entry.project_id, "project": names.get(entry.project_id, ""),
            "day": entry.day, "text": entry.text, "hours": entry.hours}


def period_key(day: str, group: str) -> str:
    d = date.fromisoformat(day)
    if group == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return {"day": day, "month": day[:7], "year": day[:4]}[group]


def _own(db: Session, user: User, project_id: int | None, date_from: str, date_to: str) -> list[WorkLog]:
    if project_id is not None:
        get_project(db, user, project_id)
        ids = [project_id]
    else:
        ids = member_project_ids(db, user)
    stmt = select(WorkLog).where(WorkLog.user_id == user.id, WorkLog.project_id.in_(ids))
    if date_from:
        stmt = stmt.where(WorkLog.day >= valid_day(date_from, "Von"))
    if date_to:
        stmt = stmt.where(WorkLog.day <= valid_day(date_to, "Bis"))
    return list(db.scalars(stmt.order_by(WorkLog.day.desc(), WorkLog.id.desc()).limit(5000)))


@router.get("")
def list_logs(project_id: int | None = None, date_from: str = "", date_to: str = "",
              user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = _own(db, user, project_id, date_from, date_to)
    names = project_names(db, list({r.project_id for r in rows}))
    return [log_out(r, names) for r in rows]


@router.post("", status_code=201)
def create_log(body: LogIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_project(db, user, body.project_id)  # jedes Mitglied darf für sich dokumentieren
    entry = WorkLog(project_id=body.project_id, user_id=user.id, day=valid_day(body.day, "Tag"),
                    text=body.text.strip(), hours=body.hours)
    db.add(entry)
    db.commit()
    return log_out(entry, project_names(db, [entry.project_id]))


def _mine(db: Session, user: User, log_id: int) -> WorkLog:
    entry = db.get(WorkLog, log_id)
    if entry is None or entry.user_id != user.id:  # fremde Einträge verraten wir nicht
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden.")
    return entry


@router.patch("/{log_id}")
def patch_log(log_id: int, body: LogPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    entry = _mine(db, user, log_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("day"):
        entry.day = valid_day(data["day"], "Tag")
    if data.get("text"):
        entry.text = data["text"].strip()
    if "hours" in data:
        entry.hours = data["hours"]
    db.commit()
    return log_out(entry, project_names(db, [entry.project_id]))


@router.delete("/{log_id}", status_code=204)
def delete_log(log_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_mine(db, user, log_id))
    db.commit()


def _edits_per_day(db: Session, user: User, project_id: int | None, date_from: str, date_to: str, tz) -> dict[str, int]:
    """Eigene Zelländerungen in den Listen (nur echte Eingaben, keine Rückgängig-Läufe) je Tag."""
    ids = [project_id] if project_id is not None else member_project_ids(db, user)
    dataset_ids = list(db.scalars(select(Dataset.id).where(Dataset.project_id.in_(ids))))
    if not dataset_ids:
        return {}
    stmt = select(RowChange.at).where(RowChange.dataset_id.in_(dataset_ids), RowChange.by == user.username,
                                      RowChange.kind.in_(("edit", "resolve", "label", "translate")))
    if date_from:
        stmt = stmt.where(RowChange.at >= day_start(date_from))
    if date_to:
        stmt = stmt.where(RowChange.at <= day_end(date_to))
    counts: dict[str, int] = defaultdict(int)
    for at in db.scalars(stmt):
        counts[to_local(at, tz).strftime("%Y-%m-%d")] += 1
    return counts


@router.get("/summary")
def summary(
    group: str = Query("week", pattern="^(day|week|month|year)$"), project_id: int | None = None,
    date_from: str = "", date_to: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> list[dict]:
    rows = _own(db, user, project_id, date_from, date_to)
    periods: dict[str, dict] = {}

    def slot(key: str) -> dict:
        return periods.setdefault(key, {"period": key, "entries": 0, "hours": 0.0, "days": set(), "edits": 0})

    for r in rows:
        s = slot(period_key(r.day, group))
        s["entries"] += 1
        s["hours"] += r.hours or 0
        s["days"].add(r.day)
    for day, count in _edits_per_day(db, user, project_id, date_from, date_to, tzinfo(settings)).items():
        slot(period_key(day, group))["edits"] += count
        slot(period_key(day, group))["days"].add(day)
    out = [{**p, "days": len(p["days"]), "hours": round(p["hours"], 2)} for p in periods.values()]
    return sorted(out, key=lambda p: p["period"], reverse=True)


@router.get("/export")
def export(project_id: int | None = None, date_from: str = "", date_to: str = "",
           user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    rows = _own(db, user, project_id, date_from, date_to)
    names = project_names(db, list({r.project_id for r in rows}))
    wb = Workbook()
    ws = wb.active
    ws.title = "Tagesbericht"
    ws.append(["Tag", "Projekt", "Tätigkeit", "Stunden"])
    for r in sorted(rows, key=lambda r: (r.day, r.id)):
        ws.append([r.day, names.get(r.project_id, ""), r.text, r.hours])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="tagesbericht.xlsx"'})
