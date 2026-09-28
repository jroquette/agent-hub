from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.dialects import sqlite

from agent_hub.storage.db import UtcDateTime, events, metadata


def test_declares_events_table_when_metadata_loaded() -> None:
    assert set(metadata.tables) == {"events"}
    required = {"id", "project", "session", "type", "source", "source_id", "timestamp", "payload"}
    optional = {"repo", "agent", "workflow", "step"}
    assert {column.name for column in events.columns} == required | optional
    assert {column.name for column in events.columns if not column.nullable} == required
    assert [column.name for column in events.primary_key] == ["id"]
    assert isinstance(events.c.timestamp.type, UtcDateTime)
    assert isinstance(events.c.payload.type, JSON)
    unique = [item for item in events.constraints if isinstance(item, UniqueConstraint)]
    assert [(item.name, [column.name for column in item.columns]) for item in unique] == [
        ("uq_events_source_source_id", ["source", "source_id"])
    ]


def test_stores_utc_when_bound_value_has_offset() -> None:
    value = datetime(2026, 9, 27, 10, 0, 0, 123456, tzinfo=timezone(timedelta(hours=2)))

    stored = UtcDateTime().process_bind_param(value, sqlite.dialect())

    # SQLite has no timezone type: the column holds naive UTC.
    assert stored == datetime(2026, 9, 27, 8, 0, 0, 123456)


def test_rejects_naive_when_bound_value_has_no_offset() -> None:
    naive = datetime(2026, 9, 27, 10, 0)

    with pytest.raises(ValueError, match="timezone"):
        UtcDateTime().process_bind_param(naive, sqlite.dialect())


def test_attaches_utc_when_result_read() -> None:
    stored = datetime(2026, 9, 27, 8, 0)

    read = UtcDateTime().process_result_value(stored, sqlite.dialect())

    assert read == datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
    assert read is not None
    assert read.tzinfo is UTC
