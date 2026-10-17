from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.dialects import sqlite

from agent_hub.storage.db import (
    UtcDateTime,
    agent_session_records,
    agent_sessions,
    events,
    metadata,
)


def test_declares_events_table_when_metadata_loaded() -> None:
    assert set(metadata.tables) == {"events", "agent_sessions", "agent_session_records"}
    required = {
        "id",
        "project",
        "session",
        "type",
        "source",
        "source_id",
        "timestamp",
        "payload",
        "event_id",
    }
    optional = {"repo", "agent", "workflow", "step", "received_at"}
    assert {column.name for column in events.columns} == required | optional
    assert {column.name for column in events.columns if not column.nullable} == required
    assert [column.name for column in events.primary_key] == ["id"]
    assert isinstance(events.c.timestamp.type, UtcDateTime)
    assert isinstance(events.c.received_at.type, UtcDateTime)
    assert isinstance(events.c.payload.type, JSON)
    unique = [item for item in events.constraints if isinstance(item, UniqueConstraint)]
    assert sorted((item.name, [column.name for column in item.columns]) for item in unique) == [
        ("uq_events_event_id", ["event_id"]),
        ("uq_events_source_source_id", ["source", "source_id"]),
    ]
    assert {index.name: [column.name for column in index.columns] for index in events.indexes} == {
        "ix_events_project_session_id": ["project", "session", "id"],
        "ix_events_project_type_timestamp": ["project", "type", "timestamp"],
        "ix_events_project_timestamp": ["project", "timestamp"],
    }


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


def test_declares_agent_session_tables_when_metadata_loaded() -> None:
    optional = {
        "claude_session_id",
        "cloud_id",
        "url",
        "model",
        "title",
        "ended_at",
        "end_reason",
        "cost_usd",
        "usage",
        "last_prompt",
        "last_reply",
    }
    assert {column.name for column in agent_sessions.columns if column.nullable} == optional
    assert [column.name for column in agent_sessions.primary_key] == ["id"]
    assert isinstance(agent_sessions.c.usage.type, JSON)
    assert isinstance(agent_sessions.c.changed_files.type, JSON)
    assert isinstance(agent_sessions.c.created_at.type, UtcDateTime)
    assert {
        index.name: [column.name for column in index.columns] for index in agent_sessions.indexes
    } == {
        "ix_agent_sessions_project_claude_session_id": ["project", "claude_session_id"],
        "ix_agent_sessions_status": ["status"],
        "ix_agent_sessions_ended_at": ["ended_at"],
    }
    assert [column.name for column in agent_session_records.primary_key] == [
        "agent_session_id",
        "seq",
    ]
    [key] = agent_session_records.foreign_keys
    assert (key.target_fullname, key.ondelete) == ("agent_sessions.id", "CASCADE")
    assert isinstance(agent_session_records.c.body.type, JSON)
    assert {column.name for column in agent_session_records.columns if column.nullable} == {"by"}
