"""Einkauf/Packliste, Whiteboard, Tagesbericht

Revision ID: 0005
Revises: 0004
"""
from alembic import op

from wtserver import models  # noqa: F401
from wtserver.db import Base

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in ("calendar_feeds", "schedule_events", "work_logs", "board_notes", "shop_requests", "catalog_items"):
        op.drop_table(table)
