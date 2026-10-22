"""Konflikte, Änderungsprotokoll, Vorlagen, KMK-Läufe, Sicherungen

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from wtserver import models  # noqa: F401
from wtserver.db import Base

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Neue Tabellen anlegen (bei Neuinstallationen existieren sie bereits durch 0001)
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in ("backups", "export_runs", "templates", "conflicts", "row_changes"):
        op.drop_table(name)
