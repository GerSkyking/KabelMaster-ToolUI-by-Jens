"""Änderungsverlauf: Lauf-Kennung (batch) für Rückgängig

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("row_changes")}
    if "batch" not in columns:  # bei Neuinstallationen legt 0001 die Tabelle bereits mit der Spalte an
        op.add_column("row_changes", sa.Column("batch", sa.String(32), nullable=True))
        op.create_index("ix_row_changes_batch", "row_changes", ["batch"])


def downgrade() -> None:
    op.drop_index("ix_row_changes_batch", table_name="row_changes")
    op.drop_column("row_changes", "batch")
