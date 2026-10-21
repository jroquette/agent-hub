"""knowledge_documents and knowledge_text: the local knowledge index of a hub's Markdown.

Two new tables (AGH-391, ADR 0044). ``knowledge_documents`` holds one row per file the index
saw in a hub, unique by ``(hub, path)`` so concurrent syncs converge; a skipped file keeps its
reason and fingerprint, no text or hash. ``knowledge_text`` is an FTS5 virtual table over the
indexed files' title and body (``rowid`` = the document's ``id``), with English stemming over
``unicode61``; SQLite keeps five shadow tables beside it. A Python whose SQLite lacks FTS5
cannot run this revision. No other table is touched; downgrading drops both.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21 14:54:05.328994
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hub", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("provenance", sa.String(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime_ns", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("skip_reason", sa.String(), nullable=True),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hub", "path", name="uq_knowledge_documents_hub_path"),
    )
    # Metadata cannot declare a virtual table; env.py keeps it and its shadows out of
    # ``alembic check``.
    op.execute(
        "CREATE VIRTUAL TABLE knowledge_text USING fts5("
        "title, body, tokenize='porter unicode61 remove_diacritics 2')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE knowledge_text")
    op.drop_table("knowledge_documents")
