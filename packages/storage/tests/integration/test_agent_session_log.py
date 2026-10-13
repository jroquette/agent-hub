import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, EndReason
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError, StoreSequenceError
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.sessions.session import TokenUsage
from agent_hub.core.testing.read_model_builders import a_log_record, an_agent_session
from agent_hub.storage.agent_session_store import open_agent_session_store

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
FIRST = "01929a4e-7a11-7c00-8a00-00000000e001"
SECOND = "01929a4e-7a11-7c00-8a00-00000000e002"
THIRD = "01929a4e-7a11-7c00-8a00-00000000e003"
KINDS: tuple[RecordKind, ...] = ("user.message", "init", "text", "tool.call", "result")


def _records(count: int, first: int = 1) -> list[LogRecord]:
    return [
        a_log_record(KINDS[(seq - 1) % len(KINDS)], seq, at=T0 + timedelta(seconds=seq))
        for seq in range(first, first + count)
    ]


def _rows(path: Path, table: str, agent_session_id: str) -> int:
    column = "id" if table == "agent_sessions" else "agent_session_id"
    with sqlite3.connect(path) as connection:
        query = f"SELECT count(*) FROM {table} WHERE {column} = ?"  # noqa: S608 -- fixed names
        (count,) = connection.execute(query, (agent_session_id,)).fetchone()
    return int(count)


def _stored_bytes(path: Path, agent_session_id: str) -> int:
    with sqlite3.connect(path) as connection:
        query = "SELECT stored_bytes FROM agent_sessions WHERE id = ?"
        (stored,) = connection.execute(query, (agent_session_id,)).fetchone()
    return int(stored)


def test_returns_full_log_in_seq_order_when_store_reopened(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = open_agent_session_store(path)
    session = an_agent_session(id=FIRST, last_seq=0, created_at=T0, updated_at=T0)
    store.create(session)
    records = _records(12)
    store.append(FIRST, records[:5])
    store.append(FIRST, records[5:])
    store.update(
        FIRST,
        status=AgentSessionStatus.ENDED,
        end_reason=EndReason.CLOSED,
        ended_at=T0 + timedelta(minutes=1),
        cost_usd=Decimal("0.1234"),
        usage=TokenUsage(input=1, output=2, cache_read=3, cache_write=4),
    )

    reopened = open_agent_session_store(path)

    assert list(reopened.records(FIRST, limit=500)) == records
    assert [record.seq for record in reopened.records(FIRST, after=10)] == [11, 12]
    stored = reopened.get(FIRST)
    assert (stored.status, stored.last_seq, stored.cost_usd) == (
        AgentSessionStatus.ENDED,
        12,
        Decimal("0.1234"),
    )
    assert reopened.list(status=AgentSessionStatus.ENDED) == (stored,)
    assert _stored_bytes(path, FIRST) == sum(record.text_bytes for record in records)


def test_writes_nothing_when_batch_has_gap(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = open_agent_session_store(path)
    store.create(an_agent_session(id=FIRST, last_seq=0))
    batch = [*_records(2), *_records(1, first=4)]

    with pytest.raises(StoreSequenceError):
        store.append(FIRST, batch)

    assert _rows(path, "agent_session_records", FIRST) == 0
    assert _stored_bytes(path, FIRST) == 0


def test_deletes_records_when_session_deleted(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = open_agent_session_store(path)
    store.create(an_agent_session(id=FIRST, last_seq=0))
    store.create(an_agent_session(id=SECOND, last_seq=0))
    store.append(FIRST, _records(3))
    store.append(SECOND, _records(2))

    store.delete(FIRST)

    assert _rows(path, "agent_sessions", FIRST) == 0
    assert _rows(path, "agent_session_records", FIRST) == 0
    assert _rows(path, "agent_session_records", SECOND) == 2
    with pytest.raises(AgentSessionNotFoundError):
        store.get(FIRST)


def test_purges_only_ended_sessions_when_cutoff_passes(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    store = open_agent_session_store(path)
    retention = timedelta(days=30)
    now = T0 + timedelta(days=60)
    ended = {"status": AgentSessionStatus.ENDED, "end_reason": EndReason.CLOSED, "last_seq": 0}
    store.create(an_agent_session(id=FIRST, ended_at=now - retention - timedelta(days=1), **ended))
    store.create(an_agent_session(id=SECOND, ended_at=now - timedelta(days=1), **ended))
    store.create(an_agent_session(id=THIRD, last_seq=0, status=AgentSessionStatus.RUNNING))
    for agent_session_id in (FIRST, SECOND, THIRD):
        store.append(agent_session_id, _records(2))

    purged = store.purge_ended_before(now - retention)

    assert purged == 1
    assert _rows(path, "agent_sessions", FIRST) == 0
    assert _rows(path, "agent_session_records", FIRST) == 0
    for kept in (SECOND, THIRD):
        assert _rows(path, "agent_session_records", kept) == 2
