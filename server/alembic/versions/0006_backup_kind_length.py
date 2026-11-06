"""Sicherungen: Spalte kind auf 20 Zeichen verlaengern ("pre-restore" hat 11 Zeichen)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.alter_column("kind", existing_type=sa.String(10), type_=sa.String(20), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("backups") as batch:
        batch.alter_column("kind", existing_type=sa.String(20), type_=sa.String(10), existing_nullable=False)
