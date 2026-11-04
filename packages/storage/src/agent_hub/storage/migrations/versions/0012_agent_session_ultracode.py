"""ultracode on agent_sessions: whether Claude may run workflows of many agents on its own.

Off for every row already there. Kept so a reopened session keeps it. The upgrade skips the
column when ``agent_sessions`` already has it: a database migrated by an earlier copy of this
revision (the playground's) holds it before ``alembic_version`` says 0012. Downgrading drops the
column.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(name: str) -> bool:
    """Whether ``agent_sessions`` already has ``name``; offline (``--sql``) there is no database
    to look at, so the SQL adds it."""
    if context.is_offline_mode():
        return False
    columns = sa.inspect(op.get_bind()).get_columns("agent_sessions")
    return any(column["name"] == name for column in columns)


def upgrade() -> None:
    if not _has_column("ultracode"):
        op.add_column(
            "agent_sessions",
            sa.Column("ultracode", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column("agent_sessions", "ultracode")
