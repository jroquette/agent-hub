"""baseline: the empty starting schema; the events table lands with the collector.

Revision ID: 0001
Revises: none (first revision)
Create Date: 2026-09-27 22:29:25.008099
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
