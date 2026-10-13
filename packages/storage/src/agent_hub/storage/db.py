"""SQLAlchemy Core metadata: the single place where tables are declared.

The schema itself is only ever created by the Alembic migrations (ADR 0003), never from this
metadata directly; ``alembic check`` compares these tables with the migrations.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    TypeDecorator,
    UniqueConstraint,
)


class UtcDateTime(TypeDecorator[datetime]):
    """An aware datetime stored as naive UTC and read back with ``UTC`` attached.

    SQLite has no timezone type: a plain ``DateTime(timezone=True)`` silently drops the offset,
    so this type converts to UTC on the way in and refuses naive values.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> Any:
        """Convert an aware datetime to naive UTC; a naive one raises ``ValueError``."""
        if value is None:
            return None
        if value.utcoffset() is None:
            msg = f"datetime {value.isoformat()} has no timezone; only aware values are stored"
            raise ValueError(msg)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any | None, dialect: Dialect) -> datetime | None:
        """Attach ``UTC`` to the stored naive UTC value."""
        if value is None:
            return None
        stored: datetime = value
        return stored.replace(tzinfo=UTC)


metadata = MetaData()

# One row per canonical event. Filtered fields get columns (ADR 0003); the rest is the JSON
# payload. ``id`` gives the insertion order; ``(source, source_id)`` is the event's identity,
# and the constraints are named so batch-mode migrations can address them. ``event_id`` (a
# UUIDv7) and ``received_at`` are minted by the store at append; rows appended before they
# existed got an ``event_id`` from the migration and keep ``received_at`` NULL. The indexes serve
# the read models' queries by project and session, type and time.
events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project", String, nullable=False),
    Column("session", String, nullable=False),
    Column("type", String, nullable=False),
    Column("source", String, nullable=False),
    Column("source_id", String, nullable=False),
    Column("timestamp", UtcDateTime, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("repo", String, nullable=True),
    Column("agent", String, nullable=True),
    Column("workflow", String, nullable=True),
    Column("step", String, nullable=True),
    Column("event_id", String(36), nullable=False),
    Column("received_at", UtcDateTime, nullable=True),
    UniqueConstraint("source", "source_id", name="uq_events_source_source_id"),
    UniqueConstraint("event_id", name="uq_events_event_id"),
    Index("ix_events_project_session_id", "project", "session", "id"),
    Index("ix_events_project_type_timestamp", "project", "type", "timestamp"),
    Index("ix_events_project_timestamp", "project", "timestamp"),
)

# One row per agent session (AGH-165, P3): a Claude Code session hub web started, or a cloud
# start (``kind = "cloud"``). ``last_seq`` is its log's last record; ``stored_bytes`` the text the
# log holds (the caps count it). ``cost_usd`` is the estimate as exact decimal text; ``usage``
# the token counts. Indexed for the Session link, the live list and retention.
agent_sessions = Table(
    "agent_sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String, nullable=False),
    Column("project", String, nullable=False),
    Column("workdir_id", String, nullable=False),
    Column("workdir_label", String, nullable=False),
    Column("claude_session_id", String, nullable=True),
    Column("cloud_id", String, nullable=True),
    Column("url", String, nullable=True),
    Column("status", String, nullable=False),
    Column("mode", String, nullable=False),
    Column("model", String, nullable=True),
    Column("title", String, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("ended_at", UtcDateTime, nullable=True),
    Column("end_reason", String, nullable=True),
    Column("cost_usd", String, nullable=True),
    Column("usage", JSON, nullable=True),
    Column("last_seq", Integer, nullable=False),
    Column("stored_bytes", Integer, nullable=False),
    Index("ix_agent_sessions_project_claude_session_id", "project", "claude_session_id"),
    Index("ix_agent_sessions_status", "status"),
    Index("ix_agent_sessions_ended_at", "ended_at"),
)

# One row per log record of an agent session; ``seq`` is gap-free per session (S4). Its text is
# redacted before it is stored (ADR 0027). Deleting a session deletes its records.
agent_session_records = Table(
    "agent_session_records",
    metadata,
    Column(
        "agent_session_id",
        String(36),
        ForeignKey(
            "agent_sessions.id",
            name="fk_agent_session_records_agent_session_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column("seq", Integer, nullable=False),
    Column("at", UtcDateTime, nullable=False),
    Column("kind", String, nullable=False),
    Column("by", String, nullable=True),
    Column("body", JSON, nullable=False),
    Column("text_bytes", Integer, nullable=False),
    PrimaryKeyConstraint("agent_session_id", "seq", name="pk_agent_session_records"),
)
