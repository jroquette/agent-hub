"""The stores' SQLite connections, reused across reads (AGH-609, AC-1 to AC-3, Q1, Q2).

An engine's pool keeps five idle connections and has no cap: sixteen held at once all open,
and once they are back five stay idle and eleven close. Reads one after another open at most
``POOL_SIZE`` connections, so the connect listener's PRAGMAs run that often; eight readers and
one writer share an engine with no lock error, and a read started after an append returns sees
it; a connection that wrote, then went back to the pool, starts its next read deferred and
holds no snapshot; and a closed store leaves its file alone, so leaving WAL succeeds and only
the database file is left. Each test closes the stores and engines it opens. No time is
asserted.
"""

import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import event
from sqlalchemy.pool import QueuePool

from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.testing.builders import an_event
from agent_hub.storage import engine
from agent_hub.storage.agent_session_store import open_agent_session_store
from agent_hub.storage.event_store import SqliteEventStore, open_event_store
from agent_hub.storage.item_version_store import open_item_version_store
from agent_hub.storage.knowledge_index import FTS5_MISSING, fts5_available, open_knowledge_index
from agent_hub.storage.migration import upgrade_to_head

READS: Final = 100
READERS: Final = 8
BATCHES: Final = 100
BATCH_SIZE: Final = 10
APPENDED: Final = BATCHES * BATCH_SIZE
WAIT_SECONDS: Final = 60.0
# Another connection's lock wait: short, so a lock still held fails fast instead of waiting 5 s.
OTHER_TIMEOUT_SECONDS: Final = 0.2


def _read_while_writing(store: SqliteEventStore, read: Callable[[int], None]) -> list[int]:
    """Run ``READERS`` threads calling ``read(appended)`` in a loop while one writer appends
    ``BATCHES`` batches of ``BATCH_SIZE`` new events through ``store``, then once more.

    ``appended`` counts the events whose ``append`` had returned when that read started. The
    threads start together; an exception any of them raised is raised here. Answers each
    reader's ``appended`` at its last read.
    """
    start = threading.Barrier(READERS + 1, timeout=WAIT_SECONDS)
    count_lock = threading.Lock()
    writer_done = threading.Event()
    appended = 0

    def write() -> None:
        nonlocal appended
        start.wait()
        try:
            for _ in range(BATCHES):
                store.append([an_event() for _ in range(BATCH_SIZE)])
                with count_lock:
                    appended += BATCH_SIZE
        finally:
            writer_done.set()

    def keep_reading() -> int:
        start.wait()
        while True:
            last = writer_done.is_set()
            with count_lock:
                before_read = appended
            read(before_read)
            if last:
                return before_read

    with ThreadPoolExecutor(max_workers=READERS + 1) as executor:
        writer = executor.submit(write)
        readers = [executor.submit(keep_reading) for _ in range(READERS)]
        # result() re-raises a thread's exception here, so any error fails the test.
        writer.result(timeout=WAIT_SECONDS)
        return [reader.result(timeout=WAIT_SECONDS) for reader in readers]


def test_keeps_five_idle_connections_per_engine_when_pool_size_read() -> None:
    """Spec Q1 and NFR: at most five idle SQLite connections per engine."""
    assert engine.POOL_SIZE == 5


def test_opens_every_connection_and_keeps_five_idle_when_sixteen_overlap(tmp_path: Path) -> None:
    """Q1: no cap on open connections, five kept idle. Sixteen is SQLAlchemy's default cap
    (5 idle + 10 overflow) plus one, the first a capped pool refuses (``TimeoutError``)."""
    path = tmp_path / "events.db"
    upgrade_to_head(path)
    store_engine = engine.create_sqlite_engine(path)
    pool = store_engine.pool
    connects: list[int] = []
    closes: list[int] = []

    def connected(dbapi_connection: object, *_: object) -> None:
        connects.append(id(dbapi_connection))

    def closed(dbapi_connection: object, *_: object) -> None:
        closes.append(id(dbapi_connection))

    event.listen(pool, "connect", connected)
    event.listen(pool, "close", closed)
    try:
        with ExitStack() as held:
            for _ in range(16):
                held.enter_context(store_engine.connect())
        assert (len(connects), len(closes)) == (16, 11)
        assert isinstance(pool, QueuePool)
        assert pool.checkedin() == 5
    finally:
        store_engine.dispose()


def test_opens_at_most_pool_size_connections_when_reads_run_in_sequence(tmp_path: Path) -> None:
    """AC-1: the connect listener runs once per new connection, not once per read."""
    path = tmp_path / "events.db"
    upgrade_to_head(path)
    store_engine = engine.create_sqlite_engine(path)
    connects: list[int] = []

    def count(dbapi_connection: object, *_: object) -> None:
        connects.append(id(dbapi_connection))

    event.listen(store_engine, "connect", count)
    with closing(SqliteEventStore(store_engine)) as store:
        for _ in range(READS):
            store.high_water_mark()
            store.query(EventQuery(limit=10))

    assert connects, "the counter saw no connection, so the bound below proves nothing"
    assert len(connects) <= engine.POOL_SIZE


def test_reads_without_lock_error_when_eight_readers_and_one_writer_share_engine(
    tmp_path: Path,
) -> None:
    """AC-2: no read or append raises ``DatabaseBusyError`` or "database is locked"."""
    store = open_event_store(tmp_path / "events.db")

    def read(_appended: int) -> None:
        store.high_water_mark()
        store.query(EventQuery(limit=10))

    try:
        last_reads = _read_while_writing(store, read)
    finally:
        store.close()

    assert last_reads == [APPENDED] * READERS


def test_sees_append_on_every_thread_when_read_starts_after_it(tmp_path: Path) -> None:
    """AC-3: a read started after an append returned sees its events, on any thread."""
    store = open_event_store(tmp_path / "events.db")
    try:
        # A fresh file: the ids count up from 1, so n appended events put the mark at n or more.
        assert store.high_water_mark() == 0

        def read(appended: int) -> None:
            assert store.high_water_mark() >= appended

        last_reads = _read_while_writing(store, read)
    finally:
        store.close()

    assert last_reads == [APPENDED] * READERS


def test_begins_deferred_when_pooled_connection_wrote_before(tmp_path: Path) -> None:
    """``write_lock`` belongs to one connection checkout, not to the pooled connection."""
    path = tmp_path / "events.db"
    upgrade_to_head(path)
    store_engine = engine.create_sqlite_engine(path)
    statements: list[str] = []

    def record(_connection: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(store_engine, "before_cursor_execute", record)
    with closing(SqliteEventStore(store_engine)) as store:
        store.append([an_event()])
        assert statements[:1] == ["BEGIN IMMEDIATE"], statements
        statements.clear()

        store.high_water_mark()

    assert statements[:1] == ["BEGIN"], statements


def test_holds_no_snapshot_when_read_connection_returns_to_pool(tmp_path: Path) -> None:
    """A connection back in the pool has ended its read: a checkpoint passes, new rows show."""
    path = tmp_path / "events.db"
    with closing(open_event_store(path)) as store:
        store.append([an_event()])
        first = store.high_water_mark()
        with closing(sqlite3.connect(path, timeout=OTHER_TIMEOUT_SECONDS)) as other:
            assert other.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            busy, _, _ = other.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        with closing(open_event_store(path)) as writer:
            writer.append([an_event()])

        assert busy == 0
        assert store.high_water_mark() > first


def _read_and_close_event_store(path: Path) -> None:
    with closing(open_event_store(path)) as store:
        store.high_water_mark()


def _read_and_close_agent_session_store(path: Path) -> None:
    with closing(open_agent_session_store(path)) as store:
        store.list()


def _read_and_close_item_version_store(path: Path) -> None:
    with closing(open_item_version_store(path)) as store:
        store.last("demo", "plugin/demo/agents/reviewer.md")


def _read_and_close_knowledge_index(path: Path) -> None:
    with closing(open_knowledge_index(path)) as index:
        index.stored("/hubs/demo")


@pytest.mark.parametrize(
    "read_and_close",
    [
        pytest.param(_read_and_close_event_store, id="event-store"),
        pytest.param(_read_and_close_agent_session_store, id="agent-session-store"),
        pytest.param(_read_and_close_item_version_store, id="item-version-store"),
        pytest.param(
            _read_and_close_knowledge_index,
            id="knowledge-index",
            marks=pytest.mark.skipif(not fts5_available(), reason=FTS5_MISSING),
        ),
    ],
)
def test_leaves_one_file_when_store_closed_and_journal_left(
    tmp_path: Path, read_and_close: Callable[[Path], None]
) -> None:
    """Q2, AC-7's mechanism: a closed store keeps no connection, so WAL can be left."""
    path = tmp_path / "events.db"
    read_and_close(path)

    with closing(sqlite3.connect(path, timeout=OTHER_TIMEOUT_SECONDS)) as other:
        assert other.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        left = other.execute("PRAGMA journal_mode=DELETE").fetchone()

    assert left == ("delete",)
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["events.db"]
