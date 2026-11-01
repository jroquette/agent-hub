"""effort on agent_sessions: how hard Claude works in a session.

Null for every row already there: those sessions keep the effort the CLI picks. Kept so a reopened
session keeps the effort it was set to. Downgrading drops the column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_sessions", sa.Column("effort", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_sessions", "effort")
