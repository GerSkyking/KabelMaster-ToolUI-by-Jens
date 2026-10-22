"""Ausgangsschema

Revision ID: 0001
Revises:
"""
from alembic import op

from wtserver import models  # noqa: F401
from wtserver.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Das Ausgangsschema wird direkt aus den Modellen erzeugt. Spätere Änderungen kommen als eigene
    # Revisionen:  alembic revision --autogenerate -m "beschreibung"
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
