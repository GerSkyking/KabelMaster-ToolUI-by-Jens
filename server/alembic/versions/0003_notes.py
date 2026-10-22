"""Notizen (Markdown) je Projekt

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from wtserver import models  # noqa: F401
from wtserver.db import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("notes")
