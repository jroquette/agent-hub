"""item_versions: the stored versions of a project's Toolkit and workflow units.

One new table (AGH-295, S3, ADR 0039), append-only; ``seq`` is gap-free per
``(project, unit_path)``, which the unique constraint enforces against racing writers.
``draft_id`` names the Studio draft a publish came from (A5). No other table is touched;
downgrading drops it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 22:40:03.751254
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain DateTime column, as in 0002 and 0004: migrations never import app code.
    op.create_table(
        "item_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("unit_path", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("first", sa.Boolean(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("author_email", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("restored_from", sa.String(length=36), nullable=True),
        sa.Column("draft_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project", "unit_path", "seq", name="uq_item_versions_project_unit_path_seq"
        ),
    )


def downgrade() -> None:
    op.drop_table("item_versions")
