"""Zeitplan/Kalender je Projekt: eigene Einträge (Phasen, Termine, Urlaub, Meilensteine) plus externe Kalender
(iCal-Link, z. B. Urlaubskalender), die der Server abruft und zwischenspeichert."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from wtserver import audit, ics
from wtserver.config import Settings, get_settings
from wtserver.db import get_db
from wtserver.models import CalendarFeed, ScheduleEvent, User, utcnow
from wtserver.scope import check_scope, member_project_ids, project_names, valid_day
from wtserver.security import current_user

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

COLORS = "^(blue|green|red|orange|purple|gray)$"
KINDS = "^(phase|termin|urlaub|meilenstein)$"
STALE = timedelta(hours=6)


class EventIn(BaseModel):
    project_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    start: str
    end: str = ""
    kind: str = Field(default="phase", pattern=KINDS)
    color: str = Field(default="blue", pattern=COLORS)
    note: str = Field(default="", max_length=500)


class EventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start: str | None = None
    end: str | None = None
    kind: str | None = Field(default=None, pattern=KINDS)
    color: str | None = Field(default=None, pattern=COLORS)
    note: str | None = Field(default=None, max_length=500)
    done: bool | None = None


class FeedIn(BaseModel):
    project_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    color: str = Field(default="gray", pattern=COLORS)


def event_out(e: ScheduleEvent, names: dict[int, str]) -> dict:
    return {"id": e.id, "project_id": e.project_id, "project": names.get(e.project_id, "") if e.project_id else "",
            "title": e.title, "start": e.start, "end": e.end or e.start, "kind": e.kind, "color": e.color,
            "note": e.note, "done": e.done, "created_by": e.created_by}


def _order(start: str, end: str) -> str:
    valid_day(start, "Start")
    if end:
        valid_day(end, "Ende")
        if end < start:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Das Ende liegt vor dem Start.")
    return end


def _refresh(feed: CalendarFeed, settings: Settings) -> None:
    """Termine neu laden (Fenster: ein Jahr zurück bis zwei Jahre voraus). Fehler werden am Eintrag gespeichert."""
    today = date.today()
    try:
        text = ics.fetch(feed.url, settings.calendar_allow_private)
        feed.events = ics.parse(text, today - timedelta(days=366), today + timedelta(days=731))
        feed.error = ""
    except ics.FeedError as e:
        feed.error = str(e)[:300]
    feed.fetched_at = utcnow()


def _feed_out(feed: CalendarFeed, names: dict[int, str], start: str, end: str) -> dict:
    events = [e for e in (feed.events or []) if e["end"] >= start and e["start"] <= end]
    return {"id": feed.id, "project_id": feed.project_id, "project": names.get(feed.project_id, "") if feed.project_id else "",
            "name": feed.name, "color": feed.color, "error": feed.error, "fetched_at": feed.fetched_at,
            "events": events}


@router.get("")
def calendar(
    start: str, end: str, project_id: int | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict:
    """Alles im Zeitraum: eigene Einträge und externe Kalender des Projekts (oder aller eigenen Projekte)
    plus die gemeinsamen Einträge ohne Projekt."""
    valid_day(start, "Start")
    valid_day(end, "Ende")
    check_scope(db, user, project_id)
    ids = [project_id] if project_id is not None else member_project_ids(db, user)
    where = lambda col: or_(col.is_(None), col.in_(ids))  # noqa: E731
    events = list(db.scalars(select(ScheduleEvent).where(
        where(ScheduleEvent.project_id), ScheduleEvent.start <= end,
        or_(ScheduleEvent.end >= start, (ScheduleEvent.end == "") & (ScheduleEvent.start >= start))
    ).order_by(ScheduleEvent.start, ScheduleEvent.id)))
    feeds = list(db.scalars(select(CalendarFeed).where(where(CalendarFeed.project_id)).order_by(CalendarFeed.name)))
    stale = [f for f in feeds if f.fetched_at is None or utcnow() - (f.fetched_at if f.fetched_at.tzinfo else f.fetched_at.replace(tzinfo=timezone.utc)) > STALE]
    for feed in stale[:3]:  # veraltete Kalender beim Öffnen neu laden (höchstens drei, damit die Seite nicht hängt)
        _refresh(feed, settings)
    if stale:
        db.commit()
    names = project_names(db, [x.project_id for x in (*events, *feeds) if x.project_id])
    return {"events": [event_out(e, names) for e in events],
            "feeds": [_feed_out(f, names, start, end) for f in feeds]}


@router.post("/events", status_code=201)
def create_event(body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    check_scope(db, user, body.project_id, "editor")
    end = _order(body.start, body.end)
    event = ScheduleEvent(project_id=body.project_id, title=body.title.strip(), start=body.start, end=end, kind=body.kind,
                          color=body.color, note=body.note.strip(), created_by=user.username)
    db.add(event)
    db.commit()
    return event_out(event, project_names(db, [event.project_id] if event.project_id else []))


def _event(db: Session, user: User, event_id: int) -> ScheduleEvent:
    event = db.get(ScheduleEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eintrag nicht gefunden.")
    check_scope(db, user, event.project_id, "editor")
    return event


@router.patch("/events/{event_id}")
def patch_event(event_id: int, body: EventPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    event = _event(db, user, event_id)
    data = body.model_dump(exclude_none=True)
    start, end = data.get("start", event.start), data.get("end", event.end)
    _order(start, end)
    for key, value in data.items():
        setattr(event, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    return event_out(event, project_names(db, [event.project_id] if event.project_id else []))


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_event(db, user, event_id))
    db.commit()


@router.post("/feeds", status_code=201)
def add_feed(
    body: FeedIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    check_scope(db, user, body.project_id, "editor")
    try:
        url = ics.check_url(body.url.strip(), settings.calendar_allow_private)
    except ics.FeedError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    feed = CalendarFeed(project_id=body.project_id, name=body.name.strip(), url=url, color=body.color, created_by=user.username)
    _refresh(feed, settings)
    if feed.error:  # nicht speichern, wenn der Link nicht funktioniert: besser sofort melden
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, feed.error)
    db.add(feed)
    db.flush()
    audit.record(db, request, "calendar_feed_added", user, f"feed:{feed.id}", {"name": feed.name, "host": url.split('/')[2]})
    db.commit()
    today = date.today()
    return _feed_out(feed, project_names(db, [feed.project_id] if feed.project_id else []),
                     (today - timedelta(days=366)).isoformat(), (today + timedelta(days=731)).isoformat())


def _feed(db: Session, user: User, feed_id: int) -> CalendarFeed:
    feed = db.get(CalendarFeed, feed_id)
    if feed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kalender nicht gefunden.")
    check_scope(db, user, feed.project_id, "editor")
    return feed


@router.post("/feeds/{feed_id}/refresh")
def refresh_feed(feed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> dict:
    feed = _feed(db, user, feed_id)
    _refresh(feed, settings)
    db.commit()
    return {"error": feed.error, "events": len(feed.events or [])}


@router.delete("/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    db.delete(_feed(db, user, feed_id))
    db.commit()
