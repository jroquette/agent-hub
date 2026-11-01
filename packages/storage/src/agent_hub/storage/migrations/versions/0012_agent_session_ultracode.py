"""ultracode on agent_sessions: whether Claude may run workflows of many agents on its own.

Off for every row already there. Kept so a reopened session keeps it. Downgrading drops the column.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("ultracode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "ultracode")
