"""knowledge_links: the brain notes each indexed document links to.

One new table (AGH-393). ``knowledge_links`` holds one row per ``(hub, source, target)``: the
path of an indexed document and the path of a brain note (``brain/<rest>``) it links to, unique
so concurrent syncs converge, with an index on ``(hub, target, source)`` for the backlinks of a
note (one seek, in source order). It has no foreign key: the knowledge index adapter clears a
document's rows itself. The rows are derived from the checkout like the rest of the index. No
other table is touched; downgrading drops it.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22 13:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hub", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hub", "source", "target", name="uq_knowledge_links_hub_source_target"),
    )
    op.create_index("ix_knowledge_links_hub_target", "knowledge_links", ["hub", "target", "source"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_links_hub_target", table_name="knowledge_links")
    op.drop_table("knowledge_links")
