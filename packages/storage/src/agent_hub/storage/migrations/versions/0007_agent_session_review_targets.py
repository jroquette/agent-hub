"""review_targets on agent_sessions: what a session's review read in each repository.

One JSON array per session (``[]`` for every row already there): the repository, the folder
read, its branch, base, fork and head commits and its pull request, so the review reads the
branch's commits from the repository once a worktree is removed. Downgrading drops the column.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("review_targets", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "review_targets")
