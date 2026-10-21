"""The SQLite ``KnowledgeIndex`` adapter (AGH-391, ADR 0044) and the entry point that opens it.

Documents live in the ``knowledge_documents`` table of the hub web database and their title and
body in the FTS5 table ``knowledge_text`` (migration 0008, ``rowid = knowledge_documents.id``).
``open_knowledge_index`` first checks that the interpreter's SQLite has FTS5, before any
directory, migration or engine is touched, so a missing module is reported as itself and no
database file is created (D-fts5).
"""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import (
    DatabaseAccessError,
    Fts5UnavailableError,
    describe_database_error,
)
from agent_hub.storage.migration import upgrade_to_head

FTS5_MISSING = "this Python's SQLite has no FTS5 module; the knowledge index needs it"


class _ProbeConnection(Protocol):
    def execute(self, sql: str, /) -> object: ...

    def close(self) -> None: ...


type Connect = Callable[[str], _ProbeConnection]


def fts5_available(connect: Connect = sqlite3.connect) -> bool:
    """Whether the interpreter's SQLite can create an FTS5 table, tried in a memory database."""
    connection = connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.p USING fts5(x)")
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()
    return True


class SqliteKnowledgeIndex:
    """A ``KnowledgeIndex`` on a SQLite database migrated to head (see the module doc)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine


def open_knowledge_index(path: Path, *, connect: Connect = sqlite3.connect) -> SqliteKnowledgeIndex:
    """Open the knowledge index in the database at ``path``, creating its directories and
    upgrading it to head; ``Fts5UnavailableError`` first when SQLite has no FTS5."""
    if not fts5_available(connect):
        raise Fts5UnavailableError(FTS5_MISSING)
    # The path comes from the user: quoted and escaped, so a message stays on one line.
    quoted = json.dumps(str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        msg = f"cannot create the directory of the database {quoted}: {error}"
        raise DatabaseAccessError(msg) from error
    upgrade_to_head(path)
    engine = create_sqlite_engine(path)
    try:
        with engine.connect():
            pass
    except SQLAlchemyError as error:
        msg = f"cannot open the database {quoted}: {describe_database_error(error)}"
        raise DatabaseAccessError(msg) from error
    return SqliteKnowledgeIndex(engine)
