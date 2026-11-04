"""effort on agent_sessions: how hard Claude works in a session.

Null for every row already there: those sessions keep the effort the CLI picks. Kept so a reopened
session keeps the effort it was set to. The upgrade skips the column when ``agent_sessions``
already has it: a database migrated by an earlier copy of this revision (the playground's) holds
it before ``alembic_version`` says 0011. Downgrading drops the column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
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
    if not _has_column("effort"):
        op.add_column("agent_sessions", sa.Column("effort", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_sessions", "effort")
