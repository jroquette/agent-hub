import multiprocessing
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text

from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event
from agent_hub.storage import event_store
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError, StorageError
from agent_hub.storage.event_store import open_event_store
from agent_hub.storage.migration import alembic_config


def _current_revision(db_path: Path) -> str | None:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _head(db_path: Path) -> str | None:
    return ScriptDirectory.from_config(alembic_config(f"sqlite:///{db_path}")).get_current_head()


def test_uses_wal_journal_when_store_opened(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"

    open_event_store(db_path)

    # WAL is a property of the file: any later connection sees it.
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
    finally:
        engine.dispose()
    assert journal_mode == "wal"


def test_creates_directories_and_migrates_when_path_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "a" / "b" / "agent-hub.db"

    open_event_store(db_path)

    assert db_path.is_file()
    assert _current_revision(db_path) == _head(db_path)


def test_stays_at_head_when_opened_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    open_event_store(db_path)

    open_event_store(db_path)

    assert _current_revision(db_path) == _head(db_path)


def test_raises_storage_error_when_file_is_not_a_database(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    db_path.write_bytes(b"this is not a SQLite database, just synthetic garbage bytes" * 20)

    with pytest.raises(StorageError) as raised:
        open_event_store(db_path)

    assert type(raised.value).__module__ == "agent_hub.storage.errors"
    message = str(raised.value)
    assert "file is not a database" in message
    for leaked in ("\n", "[SQL:", "[parameters:"):
        assert leaked not in message


def test_raises_storage_error_when_parent_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("synthetic", encoding="utf-8")

    with pytest.raises(StorageError, match="not-a-directory"):
        open_event_store(blocker / "agent-hub.db")


def _open_and_append(
    db_path: Path, batch: list[Event], *, barrier: Barrier, results: Queue[tuple[int, int]]
) -> None:
    barrier.wait()
    result = open_event_store(db_path).append(batch)
    results.put((result.appended, result.duplicates))


def test_migrates_once_when_processes_open_fresh_file_together(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-hub.db"
    batch = [an_event() for _ in range(3)]
    writers = 6
    # fork: the target is a function of this test module, which a spawned child cannot import.
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(writers)
    results: Queue[tuple[int, int]] = context.Queue()
    processes = [
        context.Process(
            target=_open_and_append,
            args=(db_path, batch),
            kwargs={"barrier": barrier, "results": results},
        )
        for _ in range(writers)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=60)

    assert [process.exitcode for process in processes] == [0] * writers
    counts = [results.get(timeout=5) for _ in range(writers)]
    assert sum(appended for appended, _ in counts) == len(batch)
    assert sum(duplicates for _, duplicates in counts) == len(batch) * (writers - 1)
    assert _current_revision(db_path) == _head(db_path)


def test_writes_named_file_when_path_holds_url_characters(tmp_path: Path) -> None:
    db_path = tmp_path / "q?mode=ro%41" / "events.db"
    batch = [an_event(), an_event()]

    open_event_store(db_path).append(batch)

    assert db_path.is_file()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["q?mode=ro%41"]
    assert open_event_store(db_path).read_all() == batch


def test_raises_storage_error_when_engine_cannot_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The migration succeeds on the real file; the store's own engine then points at a
    # directory, which SQLite cannot open.
    def engine_on_directory(path: Path) -> Engine:
        return create_sqlite_engine(tmp_path)

    monkeypatch.setattr(event_store, "create_sqlite_engine", engine_on_directory)

    with pytest.raises(DatabaseAccessError, match="cannot open"):
        open_event_store(tmp_path / "agent-hub.db")
