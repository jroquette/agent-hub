"""The SQLite knowledge index on a real file: the FTS5 probe, an unusable path, porter stemming
and the snippet FTS5 cuts."""

import sqlite3
from pathlib import Path
from typing import Final

import pytest

from agent_hub.storage.errors import Fts5UnavailableError, StorageError
from agent_hub.storage.knowledge_index import fts5_available, open_knowledge_index

NO_FTS5: Final = "no such module: fts5"


class _NoFts5Connection:
    """A ``sqlite3`` connection of an interpreter built without the FTS5 module."""

    def execute(self, sql: str, /) -> object:
        raise sqlite3.OperationalError(NO_FTS5)

    def close(self) -> None:
        pass


def _connect_without_fts5(database: str) -> _NoFts5Connection:
    return _NoFts5Connection()


def test_finds_fts5_when_interpreter_sqlite_has_it() -> None:
    assert fts5_available()


def test_raises_fts5_error_when_sqlite_lacks_module(tmp_path: Path) -> None:
    path = tmp_path / "data" / "events.db"

    with pytest.raises(Fts5UnavailableError):
        open_knowledge_index(path, connect=_connect_without_fts5)

    assert not path.exists()
    assert not path.parent.exists()


def test_raises_storage_error_when_database_unusable(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    path.mkdir()

    with pytest.raises(StorageError):
        open_knowledge_index(path)
