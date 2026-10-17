"""last_prompt, last_reply and changed_files on agent_sessions: the Sessions list's glimpse.

Three new columns, filled by ``hub web`` from the redacted log: the prompt and reply snippets
are nullable text, ``changed_files`` a JSON array (``[]`` for every row already there). The
rows that predate them get their values from their logs once ``hub web`` runs (its first
sweep). Downgrading drops the three columns.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("last_prompt", "last_reply", "changed_files")


def upgrade() -> None:
    op.add_column("agent_sessions", sa.Column("last_prompt", sa.String(), nullable=True))
    op.add_column("agent_sessions", sa.Column("last_reply", sa.String(), nullable=True))
    op.add_column(
        "agent_sessions",
        sa.Column("changed_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("agent_sessions", name)
