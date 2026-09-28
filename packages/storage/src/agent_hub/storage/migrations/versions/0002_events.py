"""events table: one row per canonical event, unique by (source, source_id).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28 07:08:18.171564
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain DateTime here: migrations never import app code; UtcDateTime in the metadata
    # stores naive UTC in this column, so the two compare equal in `alembic check`.
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("session", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("repo", sa.String(), nullable=True),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("workflow", sa.String(), nullable=True),
        sa.Column("step", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_events_source_source_id"),
    )


def downgrade() -> None:
    op.drop_table("events")
