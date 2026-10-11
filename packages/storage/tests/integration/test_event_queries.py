import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_hub.core.events.event import EventType
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.testing.builders import an_event
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError
from agent_hub.storage.event_store import (
    DatabaseBusyError,
    SqliteEventStore,
    open_event_store,
    query_statement,
)


def _plan_of(db_path: Path, query: EventQuery) -> str:
    statement = query_statement(query)
    engine = create_sqlite_engine(db_path)
    try:
        with engine.connect() as connection:
            compiled = statement.compile(
                dialect=connection.dialect, compile_kwargs={"literal_binds": True}
            )
            rows = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {compiled}").all()
    finally:
        engine.dispose()
    return " | ".join(str(row[-1]) for row in rows)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "events.db"
    store = open_event_store(path)
    store.append([an_event(session=f"s{n % 3}") for n in range(9)])
    return path


@pytest.mark.parametrize(
    ("query", "index"),
    [
        (EventQuery(project="demo", session="s1"), "ix_events_project_session_id"),
        (
            EventQuery(project="demo", types=frozenset({EventType.MESSAGE})),
            "ix_events_project_type_timestamp",
        ),
        (
            EventQuery(project="demo", since=datetime(2026, 9, 1, tzinfo=UTC)),
            "ix_events_project_timestamp",
        ),
    ],
)
def test_uses_read_index_when_query_filters_by_project(
    db_path: Path, query: EventQuery, index: str
) -> None:
    assert index in _plan_of(db_path, query)


@pytest.fixture
def locked_db(db_path: Path) -> Iterator[Path]:
    # A connection in exclusive locking mode keeps every other connection out, readers too.
    holder = sqlite3.connect(db_path, isolation_level=None)
    holder.execute("PRAGMA locking_mode=EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("UPDATE events SET repo = repo")
    try:
        yield db_path
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_raises_busy_error_when_query_meets_locked_database(locked_db: Path) -> None:
    store = SqliteEventStore(create_sqlite_engine(locked_db, busy_timeout_ms=50))

    with pytest.raises(DatabaseBusyError) as raised:
        store.query(EventQuery())

    assert isinstance(raised.value, DatabaseAccessError)
    assert "busy" in str(raised.value)


def test_raises_busy_error_when_find_or_mark_meets_locked_database(locked_db: Path) -> None:
    store = SqliteEventStore(create_sqlite_engine(locked_db, busy_timeout_ms=50))

    with pytest.raises(DatabaseBusyError):
        store.find("01929a4e-6c1d-7f3a-9b2e-5d1c0a8e4f17")
    with pytest.raises(DatabaseBusyError):
        store.high_water_mark()


def test_raises_access_error_when_events_table_missing(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    store = SqliteEventStore(create_sqlite_engine(path))

    with pytest.raises(DatabaseAccessError) as raised:
        store.query(EventQuery())

    assert not isinstance(raised.value, DatabaseBusyError)
