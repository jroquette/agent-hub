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
    Integer,
    MetaData,
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
# and the constraint is named so batch-mode migrations can address it.
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
    UniqueConstraint("source", "source_id", name="uq_events_source_source_id"),
)
