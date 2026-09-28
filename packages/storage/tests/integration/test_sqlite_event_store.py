import sqlite3
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.testing.builders import an_event
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError
from agent_hub.storage.event_store import KEYS_PER_QUERY, SqliteEventStore, open_event_store


class StaleReadEventStore(SqliteEventStore):
    """Sees an empty store on its first ``stale_reads`` lookups, as if another writer had
    inserted between its read and its write without taking the write lock."""

    def __init__(self, path: Path, *, stale_reads: int) -> None:
        super().__init__(create_sqlite_engine(path))
        self.stale_reads = stale_reads

    def _read_stored(self, connection: Connection, batch: Sequence[Event]) -> dict[EventKey, Event]:
        if self.stale_reads > 0:
            self.stale_reads -= 1
            return {}
        return super()._read_stored(connection, batch)


def _drop_events_table(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE events")
    finally:
        engine.dispose()


def test_counts_each_key_once_when_two_writers_append_same_batch(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    writers = [open_event_store(db_path), open_event_store(db_path)]
    batch = [an_event() for _ in range(3)]
    barrier = threading.Barrier(len(writers))

    def write(store: SqliteEventStore) -> AppendResult:
        barrier.wait()
        return store.append(batch)

    with ThreadPoolExecutor(max_workers=len(writers)) as executor:
        futures = [executor.submit(write, store) for store in writers]
        # result() re-raises a writer's exception here, so any error fails the test.
        results = [future.result(timeout=30) for future in futures]

    assert sum(result.appended for result in results) == len(batch)
    assert sum(result.duplicates for result in results) == len(batch)
    assert writers[0].read_all() == batch


def test_reports_duplicate_when_stale_read_hits_unique_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    event = an_event()
    open_event_store(db_path).append([event])
    stale = StaleReadEventStore(db_path, stale_reads=1)

    result = stale.append([an_event(), event])

    assert result == AppendResult(appended=1, duplicates=1)
    assert len(stale.read_all()) == 2


def test_raises_conflict_when_stale_read_hides_different_event(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    stored = an_event(payload={"version": 1})
    open_event_store(db_path).append([stored])
    stale = StaleReadEventStore(db_path, stale_reads=1)
    changed = an_event(source_id=stored.source_id, payload={"version": 2})

    with pytest.raises(EventConflictError) as raised:
        stale.append([an_event(), changed])

    assert raised.value.position == 1
    assert stale.read_all() == [stored]


def test_raises_storage_error_when_unique_constraint_hit_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    stored = an_event()
    open_event_store(db_path).append([stored])
    stale = StaleReadEventStore(db_path, stale_reads=2)

    with pytest.raises(DatabaseAccessError):
        stale.append([an_event(), stored])

    assert stale.read_all() == [stored]


def test_raises_storage_error_when_append_finds_no_events_table(tmp_path: Path) -> None:
    """Stands in for a read-only database: tests may run as root (the dev container does), where
    a read-only file mode does not stop writes, so a missing table makes the write fail."""
    db_path = tmp_path / "agent-hub.db"
    store = open_event_store(db_path)
    _drop_events_table(db_path)

    with pytest.raises(DatabaseAccessError, match="cannot write"):
        store.append([an_event()])


def test_raises_storage_error_when_read_finds_no_events_table(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    store = open_event_store(db_path)
    _drop_events_table(db_path)

    with pytest.raises(DatabaseAccessError, match="cannot read") as raised:
        store.read_all()

    assert str(raised.value) == "cannot read the event database: no such table: events"


def test_keeps_sql_and_payload_out_of_message_when_insert_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    store = open_event_store(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER reject_insert BEFORE INSERT ON events "
                "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
            )
    finally:
        engine.dispose()

    with pytest.raises(DatabaseAccessError) as raised:
        store.append([an_event(payload={"note": "synthetic-payload-marker"})])

    message = str(raised.value)
    assert message == "cannot write to the event database: synthetic failure"
    for leaked in ("\n", "[SQL:", "[parameters:", "synthetic-payload-marker"):
        assert leaked not in message


def test_finds_every_stored_key_when_batch_needs_several_lookups(tmp_path: Path) -> None:
    store = open_event_store(tmp_path / "agent-hub.db")
    batch = [an_event() for _ in range(KEYS_PER_QUERY + 1)]
    store.append(batch)

    result = store.append(batch)

    assert result == AppendResult(appended=0, duplicates=KEYS_PER_QUERY + 1)


def test_reads_but_cannot_write_when_other_connection_holds_write_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    stored = an_event()
    open_event_store(db_path).append([stored])
    # A short busy timeout, so the blocked append below fails fast instead of waiting 5 s.
    store = SqliteEventStore(create_sqlite_engine(db_path, busy_timeout_ms=50))
    writer = sqlite3.connect(db_path, isolation_level=None)
    try:
        writer.execute("BEGIN IMMEDIATE")

        assert store.read_all() == [stored]
        with pytest.raises(DatabaseAccessError, match="database is locked"):
            store.append([an_event()])
    finally:
        writer.execute("ROLLBACK")
        writer.close()
