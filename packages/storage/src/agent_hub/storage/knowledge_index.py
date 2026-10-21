"""The SQLite ``KnowledgeIndex`` adapter (AGH-391, ADR 0044) and the entry point that opens it.

Documents live in the ``knowledge_documents`` table of the hub web database and their title and
body in the FTS5 table ``knowledge_text`` (migration 0008, ``rowid = knowledge_documents.id``).
``open_knowledge_index`` first checks that the interpreter's SQLite has FTS5, before any
directory, migration or engine is touched, so a missing module is reported as itself and no
database file is created (D-fts5).

An ``apply`` runs in one ``BEGIN IMMEDIATE`` transaction (P-5): a row is upserted by its unique
``(hub, path)``, so concurrent syncs converge, and its text is deleted and, for a document,
inserted again under its id. A search binds the hub, the kinds and an FTS5 ``MATCH`` string built
only by ``fts5_match`` (each word quoted), so no caller text is SQL or FTS5 syntax.

Database errors leave as ``DatabaseAccessError`` (``DatabaseBusyError`` past the busy
timeout); their messages carry no content (the engine hides bound parameters).
"""

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Protocol

from sqlalchemy import Connection, Engine, bindparam, delete, select, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from agent_hub.core.knowledge.knowledge_index import (
    KINDS,
    Fingerprint,
    IndexChange,
    IndexedDocument,
    Kind,
    SearchHit,
    SkippedFile,
    StoredFile,
    StoredIndex,
)
from agent_hub.core.knowledge.search_query import fts5_match, snippet_line
from agent_hub.storage.db import knowledge_documents
from agent_hub.storage.engine import BUSY_TIMEOUT_MS, create_sqlite_engine
from agent_hub.storage.errors import (
    DatabaseAccessError,
    Fts5UnavailableError,
    MigrationError,
    describe_database_error,
)
from agent_hub.storage.event_store import DatabaseBusyError
from agent_hub.storage.migration import upgrade_to_head

FTS5_MISSING: Final = "this Python's SQLite has no FTS5 module; the knowledge index needs it"

# The FTS5 table has no SQLAlchemy ``Table`` (Alembic must not compare it): its statements are
# fixed text with bound parameters.
_INSERT_TEXT: Final = text(
    "INSERT INTO knowledge_text (rowid, title, body) VALUES (:id, :title, :body)"
)
_DELETE_TEXT: Final = text("DELETE FROM knowledge_text WHERE rowid = :id")
# P-6: ranked by bm25 with the title weighted 10 and the body 1, then by path; the snippet is
# FTS5's cut of the body around the first match, without markers.
_SEARCH: Final = text(
    "SELECT d.path, d.kind, d.title, d.status, d.provenance, "
    "snippet(knowledge_text, 1, '', '', '…', 24) AS snippet "
    "FROM knowledge_text JOIN knowledge_documents AS d ON d.id = knowledge_text.rowid "
    "WHERE knowledge_text MATCH :match AND d.hub = :hub AND d.kind IN :kinds "
    "ORDER BY bm25(knowledge_text, 10.0, 1.0), d.path LIMIT :limit"
).bindparams(bindparam("kinds", expanding=True))
_DELETE_PATH_TEXT: Final = text(
    "DELETE FROM knowledge_text WHERE rowid IN "
    "(SELECT id FROM knowledge_documents WHERE hub = :hub AND path = :path)"
)
_DELETE_PATH: Final = delete(knowledge_documents).where(
    knowledge_documents.c.hub == bindparam("hub"),
    knowledge_documents.c.path == bindparam("path"),
)
_DELETE_HUB_TEXT: Final = text(
    "DELETE FROM knowledge_text WHERE rowid IN "
    "(SELECT id FROM knowledge_documents WHERE hub = :hub)"
)


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

    def stored(self, hub: str) -> StoredIndex:
        """What the hub's rows remember, by path; ``version`` only when every row shares it."""
        table = knowledge_documents
        statement = select(
            table.c.path,
            table.c.size,
            table.c.mtime_ns,
            table.c.sha256,
            table.c.skip_reason,
            table.c.index_version,
        ).where(table.c.hub == hub)
        with self._reading() as connection:
            rows = connection.execute(statement).mappings().all()
        versions = {row["index_version"] for row in rows}
        files = {
            row["path"]: StoredFile(
                path=row["path"],
                fingerprint=Fingerprint(size=row["size"], mtime_ns=row["mtime_ns"]),
                sha256=row["sha256"],
                skip_reason=row["skip_reason"],
            )
            for row in rows
        }
        return StoredIndex(version=versions.pop() if len(versions) == 1 else None, files=files)

    def apply(self, hub: str, change: IndexChange) -> None:
        """Write ``change`` to the hub's rows in one ``BEGIN IMMEDIATE`` transaction: rebuild,
        documents, skipped, touched, dropped."""
        table = knowledge_documents
        version = change.version
        with self._writing() as connection:
            if change.rebuild:
                connection.execute(_DELETE_HUB_TEXT, {"hub": hub})
                connection.execute(delete(table).where(table.c.hub == hub))
            for document in change.documents:
                row_id = _upsert(connection, hub, _document_row(document, version))
                connection.execute(
                    _INSERT_TEXT, {"id": row_id, "title": document.title, "body": document.body}
                )
            for skipped in change.skipped:
                if skipped.fingerprint is None:
                    _drop(connection, hub, (skipped.path,))
                else:
                    _upsert(connection, hub, _skipped_row(skipped, skipped.fingerprint, version))
            for path, fingerprint in change.touched.items():
                connection.execute(
                    update(table)
                    .where(table.c.hub == hub, table.c.path == path)
                    .values(
                        size=fingerprint.size,
                        mtime_ns=fingerprint.mtime_ns,
                        index_version=version,
                    )
                )
            _drop(connection, hub, change.dropped)

    def search(
        self, hub: str, words: tuple[str, ...], *, kinds: tuple[Kind, ...] = (), limit: int
    ) -> tuple[SearchHit, ...]:
        """The hub's documents holding every word, by bm25 (title 10, body 1) and then path, of
        ``kinds`` when not empty; ``()`` with no word."""
        if not words:
            return ()
        parameters = {
            "match": fts5_match(words),
            "hub": hub,
            "kinds": list(kinds or KINDS),
            "limit": limit,
        }
        with self._reading() as connection:
            rows = connection.execute(_SEARCH, parameters).mappings().all()
        return tuple(
            SearchHit(
                path=row["path"],
                kind=row["kind"],
                title=row["title"],
                status=row["status"],
                provenance=row["provenance"],
                snippet=snippet_line(row["snippet"]),
            )
            for row in rows
        )

    @contextmanager
    def _writing(self) -> Iterator[Connection]:
        try:
            with (
                self._engine.connect().execution_options(write_lock=True) as connection,
                connection.begin(),
            ):
                yield connection
        except SQLAlchemyError as error:
            raise _database_error(error, "write to") from error

    @contextmanager
    def _reading(self) -> Iterator[Connection]:
        try:
            with self._engine.connect() as connection, connection.begin():
                yield connection
        except SQLAlchemyError as error:
            raise _database_error(error, "read") from error


def open_knowledge_index(path: Path, *, connect: Connect = sqlite3.connect) -> SqliteKnowledgeIndex:
    """Open the knowledge index in the database at ``path``, creating its directories and
    upgrading it to head; ``Fts5UnavailableError`` first when SQLite has no FTS5, and
    ``DatabaseBusyError`` when another connection holds the write lock past the busy timeout."""
    if not fts5_available(connect):
        raise Fts5UnavailableError(FTS5_MISSING)
    # The path comes from the user: quoted and escaped, so a message stays on one line.
    quoted = json.dumps(str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        msg = f"cannot create the directory of the database {quoted}: {error}"
        raise DatabaseAccessError(msg) from error
    # Read here, not bound at import: the module's value is the tests' seam.
    busy_timeout_ms = BUSY_TIMEOUT_MS
    try:
        upgrade_to_head(path, busy_timeout_ms=busy_timeout_ms)
    except MigrationError as error:
        cause = error.__cause__
        # Another writer held the lock past the timeout: the line apply gives, not a schema one.
        if isinstance(cause, SQLAlchemyError) and _is_busy(cause):
            raise _database_error(cause, "open") from error
        raise
    engine = create_sqlite_engine(path, busy_timeout_ms=busy_timeout_ms)
    try:
        with engine.connect():
            pass
    except SQLAlchemyError as error:
        if _is_busy(error):
            raise _database_error(error, "open") from error
        msg = f"cannot open the database {quoted}: {describe_database_error(error)}"
        raise DatabaseAccessError(msg) from error
    return SqliteKnowledgeIndex(engine)


def _document_row(document: IndexedDocument, version: int) -> dict[str, Any]:
    return {
        "path": document.path,
        "kind": document.kind,
        "title": document.title,
        "status": document.status,
        "provenance": document.provenance,
        "size": document.fingerprint.size,
        "mtime_ns": document.fingerprint.mtime_ns,
        "sha256": document.sha256,
        "skip_reason": None,
        "index_version": version,
    }


def _skipped_row(skipped: SkippedFile, fingerprint: Fingerprint, version: int) -> dict[str, Any]:
    return {
        "path": skipped.path,
        "kind": None,
        "title": None,
        "status": None,
        "provenance": None,
        "size": fingerprint.size,
        "mtime_ns": fingerprint.mtime_ns,
        "sha256": None,
        "skip_reason": skipped.reason,
        "index_version": version,
    }


def _upsert(connection: Connection, hub: str, row: dict[str, Any]) -> int:
    """Write the row of ``(hub, row["path"])`` and drop its text; its id."""
    table = knowledge_documents
    statement = (
        insert(table)
        .values(hub=hub, **row)
        .on_conflict_do_update(index_elements=[table.c.hub, table.c.path], set_=row)
        .returning(table.c.id)
    )
    row_id = int(connection.execute(statement).scalar_one())
    connection.execute(_DELETE_TEXT, {"id": row_id})
    return row_id


def _drop(connection: Connection, hub: str, paths: tuple[str, ...]) -> None:
    """Delete the rows of ``paths`` in the hub, and their text."""
    if not paths:
        return
    # One statement per path (executemany), never ``path IN (…)``: a list of paths can be
    # longer than the variables SQLite binds in one statement.
    rows = [{"hub": hub, "path": path} for path in paths]
    connection.execute(_DELETE_PATH_TEXT, rows)
    connection.execute(_DELETE_PATH, rows)


def _database_error(error: SQLAlchemyError, action: str) -> DatabaseAccessError:
    description = describe_database_error(error)
    if _is_busy(error):
        return DatabaseBusyError(f"the knowledge index database is busy: {description}")
    return DatabaseAccessError(f"cannot {action} the knowledge index database: {description}")


def _is_busy(error: SQLAlchemyError) -> bool:
    code = getattr(getattr(error, "orig", None), "sqlite_errorcode", None)
    return (
        isinstance(error, OperationalError)
        and code is not None
        and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    )
