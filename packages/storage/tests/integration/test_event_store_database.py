from pathlib import Path

import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from agent_hub.storage.errors import StorageError
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


def test_raises_storage_error_when_parent_is_a_file(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("synthetic", encoding="utf-8")

    with pytest.raises(StorageError, match="not-a-directory"):
        open_event_store(blocker / "agent-hub.db")
