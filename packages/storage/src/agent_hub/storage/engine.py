"""The SQLite engine of the event store: WAL journal, busy timeout, explicit write locks.

pysqlite opens transactions on its own and too late for SQLAlchemy to control them, so the
driver's transaction handling is switched off and a ``begin`` listener opens each transaction
instead. A connection with the execution option ``write_lock=True`` starts with
``BEGIN IMMEDIATE``: it takes the write lock before reading, so two writers cannot both read
"not stored" and then insert. Every other transaction starts deferred (``BEGIN``), so readers
never hold the write lock and, with WAL, never block writers.
"""

import random
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

BUSY_TIMEOUT_MS = 5000
BACKOFF_MIN_SECONDS = 0.001
BACKOFF_MAX_SECONDS = 0.02


def create_sqlite_engine(path: Path, *, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> Engine:
    """An engine on the SQLite file at ``path``; SQLite creates the file on first connect.

    A connection waits up to ``busy_timeout_ms`` for a lock another connection holds.
    """
    # No pool: each use opens and closes its own SQLite connection, so a store needs no close()
    # and no connection outlives the transaction that used it.
    # URL.create, not a "sqlite:///..." string: "?" and "%XX" in a path are file name characters,
    # which URL parsing would read as a query string and escapes.
    # hide_parameters: an error must never carry event payloads into messages or logs.
    engine = create_engine(
        URL.create("sqlite", database=str(path)), poolclass=NullPool, hide_parameters=True
    )

    def configure_connection(
        dbapi_connection: sqlite3.Connection, connection_record: ConnectionPoolEntry
    ) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            # The timeout first: switching a fresh file to WAL needs a lock another process may
            # hold.
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            switch_to_wal(cursor, busy_timeout_ms)
        finally:
            cursor.close()

    event.listen(engine, "connect", configure_connection)
    event.listen(engine, "begin", _begin_transaction)
    return engine


class _StatementCursor(Protocol):
    def execute(self, sql: str, /) -> object: ...


def switch_to_wal(
    cursor: _StatementCursor,
    busy_timeout_ms: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Put the database in WAL mode, backing off while another connection holds its locks.

    Connections switching a fresh file to WAL at the same moment deadlock on its locks, and
    SQLite fails the loser at once with SQLITE_BUSY instead of calling the busy handler. The
    loser sleeps a short random while (so contenders spread out) and tries again until the
    busy timeout has passed; once the file is in WAL the switch is a no-op. Any other error is
    raised at once.
    """
    deadline = clock() + busy_timeout_ms / 1000
    while True:
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as error:
            if not _is_busy(error) or clock() >= deadline:
                raise
            sleep(_backoff_seconds())
        else:
            return


def _is_busy(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and code & 0xFF == sqlite3.SQLITE_BUSY


def _backoff_seconds() -> float:
    # Jitter to spread contending processes, not a secret: a non-cryptographic PRNG is right.
    return random.uniform(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS)  # noqa: S311


def _begin_transaction(connection: Connection) -> None:
    if connection.get_execution_options().get("write_lock", False):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")
