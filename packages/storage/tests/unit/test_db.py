from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import JSON, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects import sqlite

from agent_hub.storage.db import (
    KNOWLEDGE_TEXT,
    UtcDateTime,
    agent_session_records,
    agent_sessions,
    events,
    is_declared_table,
    item_versions,
    knowledge_documents,
    knowledge_links,
    metadata,
)


def test_declares_events_table_when_metadata_loaded() -> None:
    assert set(metadata.tables) == {
        "events",
        "agent_sessions",
        "agent_session_records",
        "item_versions",
        "knowledge_documents",
        "knowledge_links",
    }
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


def test_declares_item_versions_when_metadata_read() -> None:
    columns = [column.name for column in item_versions.columns]
    assert columns == [
        "id",
        "project",
        "unit_path",
        "kind",
        "seq",
        "origin",
        "first",
        "author_name",
        "author_email",
        "recorded_at",
        "content_hash",
        "size",
        "content",
        "restored_from",
        "draft_id",
    ]
    nullable = {column.name for column in item_versions.columns if column.nullable}
    assert nullable == {"author_name", "author_email", "restored_from", "draft_id"}
    assert [column.name for column in item_versions.primary_key] == ["id"]
    assert isinstance(item_versions.c.id.type, String)
    assert item_versions.c.id.type.length == 36
    assert isinstance(item_versions.c.recorded_at.type, UtcDateTime)
    assert isinstance(item_versions.c.content.type, LargeBinary)
    unique = [item for item in item_versions.constraints if isinstance(item, UniqueConstraint)]
    assert [(item.name, [column.name for column in item.columns]) for item in unique] == [
        ("uq_item_versions_project_unit_path_seq", ["project", "unit_path", "seq"])
    ]


def test_declares_knowledge_documents_when_metadata_read() -> None:
    columns = [column.name for column in knowledge_documents.columns]
    assert columns == [
        "id",
        "hub",
        "path",
        "kind",
        "title",
        "status",
        "provenance",
        "size",
        "mtime_ns",
        "sha256",
        "skip_reason",
        "index_version",
    ]
    nullable = {column.name for column in knowledge_documents.columns if column.nullable}
    assert nullable == {"kind", "title", "status", "provenance", "sha256", "skip_reason"}
    assert [column.name for column in knowledge_documents.primary_key] == ["id"]
    integers = {"id", "size", "mtime_ns", "index_version"}
    assert {
        column.name for column in knowledge_documents.columns if isinstance(column.type, Integer)
    } == integers
    assert all(
        isinstance(column.type, String)
        for column in knowledge_documents.columns
        if column.name not in integers
    )
    unique = [
        item for item in knowledge_documents.constraints if isinstance(item, UniqueConstraint)
    ]
    assert [(item.name, [column.name for column in item.columns]) for item in unique] == [
        ("uq_knowledge_documents_hub_path", ["hub", "path"])
    ]


def test_declares_knowledge_links_when_metadata_read() -> None:
    columns = [column.name for column in knowledge_links.columns]
    assert columns == ["id", "hub", "source", "target"]
    assert not any(column.nullable for column in knowledge_links.columns)
    assert [column.name for column in knowledge_links.primary_key] == ["id"]
    assert isinstance(knowledge_links.c.id.type, Integer)
    assert all(
        isinstance(column.type, String) for column in knowledge_links.columns if column.name != "id"
    )
    assert not knowledge_links.foreign_keys
    unique = [item for item in knowledge_links.constraints if isinstance(item, UniqueConstraint)]
    assert [(item.name, [column.name for column in item.columns]) for item in unique] == [
        ("uq_knowledge_links_hub_source_target", ["hub", "source", "target"])
    ]
    assert {
        index.name: [column.name for column in index.columns] for index in knowledge_links.indexes
    } == {"ix_knowledge_links_hub_target": ["hub", "target"]}


def test_skips_fts_tables_when_names_reflected() -> None:
    assert KNOWLEDGE_TEXT == "knowledge_text"
    assert not is_declared_table("knowledge_text")
    assert not is_declared_table("knowledge_text_data")
    assert is_declared_table("knowledge_documents")
    assert is_declared_table("knowledge_textual")
    for shadow in ("data", "idx", "content", "docsize", "config"):
        assert not is_declared_table(f"knowledge_text_{shadow}")
    assert is_declared_table("knowledge_text_meta")
