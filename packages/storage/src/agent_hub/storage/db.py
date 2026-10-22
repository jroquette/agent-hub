"""SQLAlchemy Core metadata: the single place where tables are declared.

The schema itself is only ever created by the Alembic migrations (ADR 0003), never from this
metadata directly; ``alembic check`` compares these tables with the migrations.
"""

from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    TypeDecorator,
    UniqueConstraint,
    text,
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
# the token counts. ``last_prompt``, ``last_reply`` and ``changed_files`` are the list's glimpse
# of the redacted log (0006). Indexed for the Session link, the live list and retention.
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
    Column("last_prompt", String, nullable=True),
    Column("last_reply", String, nullable=True),
    Column("changed_files", JSON, nullable=False, server_default=text("'[]'")),
    # What the session's review read in each repository, so it outlives the folders.
    Column("review_targets", JSON, nullable=False, server_default=text("'[]'")),
    # The tools the session may use (``all`` or ``read_only``), so a reopened one keeps them.
    Column("tool_access", String, nullable=False, server_default=text("'all'")),
    Index("ix_agent_sessions_project_claude_session_id", "project", "claude_session_id"),
    Index("ix_agent_sessions_status", "status"),
    Index("ix_agent_sessions_ended_at", "ended_at"),
)

# One row per log record of an agent session; ``seq`` is gap-free per session (S4). Its text is
# redacted before it is stored (ADR 0031). Deleting a session deletes its records.
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

# One row per item version (AGH-295, S3, ADR 0039): a stored snapshot of a Toolkit or workflow
# unit, append-only. ``seq`` is gap-free per ``(project, unit_path)``; the unique constraint
# makes a racing writer's second ``seq`` fail, and it serves the newest-first pages. ``content``
# is a file unit's bytes or a folder's frames; ``draft_id`` names the Studio draft a ``publish``
# came from (A5).
item_versions = Table(
    "item_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project", String, nullable=False),
    Column("unit_path", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("origin", String, nullable=False),
    Column("first", Boolean, nullable=False),
    Column("author_name", String, nullable=True),
    Column("author_email", String, nullable=True),
    Column("recorded_at", UtcDateTime, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("size", Integer, nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("restored_from", String(36), nullable=True),
    Column("draft_id", String, nullable=True),
    UniqueConstraint("project", "unit_path", "seq", name="uq_item_versions_project_unit_path_seq"),
)

# One row per file the knowledge index saw in a hub (AGH-391, ADR 0044). ``hub`` is the real
# path of the hub's main checkout; ``(hub, path)`` is the file's identity, so concurrent syncs
# converge. ``size`` and ``mtime_ns`` are its fingerprint and ``index_version`` the rules that
# indexed it. An indexed file has its ``sha256`` and its title and body in the FTS5 table
# ``knowledge_text`` (``rowid = id``); a skipped one has only ``skip_reason``, no text or hash.
knowledge_documents = Table(
    "knowledge_documents",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("hub", String, nullable=False),
    Column("path", String, nullable=False),
    Column("kind", String, nullable=True),
    Column("title", String, nullable=True),
    Column("status", String, nullable=True),
    Column("provenance", String, nullable=True),
    Column("size", Integer, nullable=False),
    Column("mtime_ns", Integer, nullable=False),
    Column("sha256", String, nullable=True),
    Column("skip_reason", String, nullable=True),
    Column("index_version", Integer, nullable=False),
    UniqueConstraint("hub", "path", name="uq_knowledge_documents_hub_path"),
)

# The FTS5 virtual table over the indexed documents' title and body. Migration 0008 creates it
# (metadata cannot declare a virtual table), so ``alembic check`` must not see it or the shadow
# tables FTS5 keeps beside it (``knowledge_text_data``, ``_idx``, ``_content``, ``_docsize``,
# ``_config``).
KNOWLEDGE_TEXT: Final = "knowledge_text"


# The shadow tables FTS5 keeps beside ``knowledge_text`` (``<table>_<suffix>``).
_FTS5_SHADOW_SUFFIXES: Final = ("data", "idx", "content", "docsize", "config")
_FTS5_TABLES: Final = frozenset(
    (KNOWLEDGE_TEXT, *(f"{KNOWLEDGE_TEXT}_{suffix}" for suffix in _FTS5_SHADOW_SUFFIXES))
)


def is_declared_table(name: str) -> bool:
    """Whether a reflected table belongs to this metadata's comparison: not ``knowledge_text``
    or one of its five FTS5 shadow tables."""
    return name not in _FTS5_TABLES
