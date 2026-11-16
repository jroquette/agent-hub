"""agent_sessions and agent_session_records: the sessions hub web drives and their logs.

Two new tables (AGH-165, P3); the events table is not touched, so the hook-fed store stays
metadata-only (ADR 0019). Downgrading drops both, records first.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13 10:12:40.318204
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = {
    "ix_agent_sessions_project_claude_session_id": ["project", "claude_session_id"],
    "ix_agent_sessions_status": ["status"],
    "ix_agent_sessions_ended_at": ["ended_at"],
}


def upgrade() -> None:
    # Plain DateTime columns, as in 0002: migrations never import app code.
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("project", sa.String(), nullable=False),
        sa.Column("workdir_id", sa.String(), nullable=False),
        sa.Column("workdir_label", sa.String(), nullable=False),
        sa.Column("claude_session_id", sa.String(), nullable=True),
        sa.Column("cloud_id", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(), nullable=True),
        sa.Column("cost_usd", sa.String(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("last_seq", sa.Integer(), nullable=False),
        sa.Column("stored_bytes", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in INDEXES.items():
        op.create_index(name, "agent_sessions", columns, unique=False)
    op.create_table(
        "agent_session_records",
        sa.Column("agent_session_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("by", sa.String(), nullable=True),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("text_bytes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["agent_sessions.id"],
            name="fk_agent_session_records_agent_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("agent_session_id", "seq", name="pk_agent_session_records"),
    )


def downgrade() -> None:
    op.drop_table("agent_session_records")
    for name in INDEXES:
        op.drop_index(name, table_name="agent_sessions")
    op.drop_table("agent_sessions")
