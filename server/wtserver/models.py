"""Datenmodell. Zeilen eines Datensatzes (Excel-Liste) sind JSON-Dokumente mit Revision und Änderungs-Zähler,
damit Offline-Clients inkrementell synchronisieren können."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wtserver.db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_user_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    display_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), default="local")  # local | ldap | oidc | oauth2
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)  # Name des Arbeitsverzeichnisses
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)  # Änderungs-Zähler für die Synchronisation
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["ProjectMember"]] = relationship(cascade="all, delete-orphan", back_populates="project")
    datasets: Mapped[list["Dataset"]] = relationship(cascade="all, delete-orphan", back_populates="project")
    notes: Mapped[list["Note"]] = relationship(cascade="all, delete-orphan", order_by="Note.updated_at.desc()")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # owner | editor | viewer

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Note(Base):
    """Notiz im Markdown-Format; gehört zu einem Projekt. ``version`` verhindert stilles Überschreiben."""
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(150), default="")
    updated_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_file: Mapped[str] = mapped_column(String(255), default="")
    columns: Mapped[list[str]] = mapped_column(JsonType, default=list)
    # Reiter-spezifische Einstellungen: Spaltenzuordnung (Kabelzug), Auto-Datum, kurze Enden ...
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="datasets")
    rows: Mapped[list["Row"]] = relationship(cascade="all, delete-orphan", back_populates="dataset")


class Row(Base):
    __tablename__ = "rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)  # Reihenfolge wie in der Excel-Datei
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    rev: Mapped[int] = mapped_column(Integer, default=1)
    seq: Mapped[int] = mapped_column(Integer, default=0, index=True)  # Projekt-seq bei letzter Änderung
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(150), default="")

    dataset: Mapped[Dataset] = relationship(back_populates="rows")


class RowChange(Base):
    """Änderungsprotokoll je Feld (für Versionsvergleiche und Nachvollziehbarkeit)."""
    __tablename__ = "row_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    row_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(255))
    old: Mapped[Any] = mapped_column(JsonType, nullable=True)
    new: Mapped[Any] = mapped_column(JsonType, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="edit")  # edit | resolve | label | create | delete | translate | undo
    batch: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # gemeinsamer Lauf (Übersetzer, Rückgängig)
    by: Mapped[str] = mapped_column(String(150), default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Conflict(Base):
    """Zwei Personen haben dasselbe Feld unterschiedlich geändert - jemand muss entscheiden."""
    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    row_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(255))
    base_value: Mapped[Any] = mapped_column(JsonType, nullable=True)
    server_value: Mapped[Any] = mapped_column(JsonType, nullable=True)
    server_by: Mapped[str] = mapped_column(String(150), default="")
    server_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposed_value: Mapped[Any] = mapped_column(JsonType, nullable=True)
    proposed_by: Mapped[str] = mapped_column(String(150), default="")
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending | resolved
    resolution: Mapped[str] = mapped_column(String(10), default="")  # server | proposed
    resolved_by: Mapped[str] = mapped_column(String(150), default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Template(Base):
    """Vorlage, global gespeichert unter Vorlagen/<Benutzer>/<Name>. Alle sehen sie, nur der Besitzer ändert."""
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("owner_id", "tab_id", "name", name="uq_template"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    owner_name: Mapped[str] = mapped_column(String(150), default="")
    tab_id: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExportRun(Base):
    """Ein KMK-Export (PDF/Excel). Die enthaltenen Kabel können danach als beschriftet abgehakt werden."""
    __tablename__ = "export_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(20), default="kmk")
    created_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    formats: Mapped[list[str]] = mapped_column(JsonType, default=list)
    row_ids: Mapped[list[int]] = mapped_column(JsonType, default=list)
    # je Ziel: "" offen, sonst Datum TT.MM.JJ der Markierung
    status: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    note: Mapped[str] = mapped_column(String(255), default="")


def purge_datasets(db, dataset_ids: list[int]) -> None:
    """Löscht alles, was an Datensätzen hängt, mit je einem DELETE (statt jede Zeile einzeln zu laden)."""
    from sqlalchemy import delete

    if not dataset_ids:
        return
    for model in (Row, RowChange, Conflict, ExportRun, ShareLink):
        db.execute(delete(model).where(model.dataset_id.in_(dataset_ids)))


class Backup(Base):
    __tablename__ = "backups"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True)
    kind: Mapped[str] = mapped_column(String(10), default="manual")  # manual | auto | pre-restore | upload
    created_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship()


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    mode: Mapped[str] = mapped_column(String(10), default="view")  # view | edit
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    dataset: Mapped[Dataset] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(150), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class CatalogItem(Base):
    """Artikel der allgemeinen Liste (für alle Projekte). Gehört zu keinem Warenkorb, bis jemand ihn anfordert."""
    __tablename__ = "catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    article_no: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    unit: Mapped[str] = mapped_column(String(30), default="Stk")
    note: Mapped[str] = mapped_column(String(500), default="")
    image: Mapped[str] = mapped_column(String(120), default="")  # Dateiname unter DATA_DIR/catalog
    created_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShopRequest(Base):
    """Bedarf: etwas mitbringen oder prüfen. Status ergibt sich aus packed_at / done_at.
    Name und Artikelnummer sind kopiert, damit das Archiv auch nach dem Löschen eines Katalogartikels stimmt."""
    __tablename__ = "shop_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # None = ohne Projekt
    catalog_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    article_no: Mapped[str] = mapped_column(String(100), default="")
    unit: Mapped[str] = mapped_column(String(30), default="Stk")
    qty: Mapped[float] = mapped_column(Float, default=1)
    kind: Mapped[str] = mapped_column(String(10), default="bringen")  # bringen | pruefen
    due: Mapped[str] = mapped_column(String(10), default="")  # JJJJ-MM-TT, optional
    note: Mapped[str] = mapped_column(String(500), default="")
    requested_by: Mapped[str] = mapped_column(String(150), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    packed_by: Mapped[str] = mapped_column(String(150), default="")
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by: Mapped[str] = mapped_column(String(150), default="")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class BoardNote(Base):
    """Haftnotiz auf dem Whiteboard. project_id None = gemeinsames Whiteboard für alle Projekte."""
    __tablename__ = "board_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(10), default="yellow")
    x: Mapped[float] = mapped_column(Float, default=20)
    y: Mapped[float] = mapped_column(Float, default=20)
    w: Mapped[float] = mapped_column(Float, default=200)
    h: Mapped[float] = mapped_column(Float, default=140)
    created_by: Mapped[str] = mapped_column(String(150), default="")
    updated_by: Mapped[str] = mapped_column(String(150), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkLog(Base):
    """Persönlicher Tagesbericht: was ich an einem Tag im Projekt gemacht habe. Nur der Autor sieht ihn."""
    __tablename__ = "work_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # JJJJ-MM-TT
    text: Mapped[str] = mapped_column(Text, default="")
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScheduleEvent(Base):
    """Eintrag im Zeitplan/Kalender eines Projekts (project_id None = für alle sichtbar). Datumsangaben JJJJ-MM-TT."""
    __tablename__ = "schedule_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    start: Mapped[str] = mapped_column(String(10), index=True)
    end: Mapped[str] = mapped_column(String(10), default="")  # leer = eintägig; einschließlich
    kind: Mapped[str] = mapped_column(String(12), default="phase")  # phase | termin | urlaub | meilenstein
    color: Mapped[str] = mapped_column(String(10), default="blue")
    note: Mapped[str] = mapped_column(String(500), default="")
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(150), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CalendarFeed(Base):
    """Externer Kalender (iCal/ICS-Link, z. B. Urlaub oder Termine). Der Server holt ihn ab und merkt sich die Termine."""
    __tablename__ = "calendar_feeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    color: Mapped[str] = mapped_column(String(10), default="gray")
    events: Mapped[list[Any]] = mapped_column(JsonType, default=list)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[str] = mapped_column(String(150), default="")
