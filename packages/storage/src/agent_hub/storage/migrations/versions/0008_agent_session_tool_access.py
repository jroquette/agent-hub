"""tool_access on agent_sessions: the tools a session may use.

``all`` for every row already there; ``read_only`` for a discovery session, which may only read
files (ADR 0043), kept so a reopened session keeps its tools. Downgrading drops the column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("tool_access", sa.String(), nullable=False, server_default=sa.text("'all'")),
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "tool_access")
