"""The SQLite engine of the event store: WAL journal, busy timeout, explicit write locks.

pysqlite opens transactions on its own and too late for SQLAlchemy to control them, so the
driver's transaction handling is switched off and a ``begin`` listener opens each transaction
instead. A connection with the execution option ``write_lock=True`` starts with
``BEGIN IMMEDIATE``: it takes the write lock before reading, so two writers cannot both read
"not stored" and then insert. Every other transaction starts deferred (``BEGIN``), so readers
never hold the write lock and, with WAL, never block writers.
"""

import sqlite3
from pathlib import Path

from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

BUSY_TIMEOUT_MS = 5000
WAL_SWITCH_ATTEMPTS = 10


def create_sqlite_engine(path: Path) -> Engine:
    """An engine on the SQLite file at ``path``; SQLite creates the file on first connect."""
    # No pool: each use opens and closes its own SQLite connection, so a store needs no close()
    # and no connection outlives the transaction that used it.
    # URL.create, not a "sqlite:///..." string: "?" and "%XX" in a path are file name characters,
    # which URL parsing would read as a query string and escapes.
    # hide_parameters: an error must never carry event payloads into messages or logs.
    engine = create_engine(
        URL.create("sqlite", database=str(path)), poolclass=NullPool, hide_parameters=True
    )
    event.listen(engine, "connect", _configure_connection)
    event.listen(engine, "begin", _begin_transaction)
    return engine


def _configure_connection(
    dbapi_connection: sqlite3.Connection, connection_record: ConnectionPoolEntry
) -> None:
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        # The timeout first: switching a fresh file to WAL needs a lock another process may hold.
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        _switch_to_wal(cursor)
    finally:
        cursor.close()


def _switch_to_wal(cursor: sqlite3.Cursor) -> None:
    # Connections switching a fresh file to WAL at the same moment can deadlock on its locks;
    # SQLite then fails one of them at once instead of waiting (the busy timeout does not apply).
    # Each such failure lets another connection go ahead, and once the file is in WAL the switch
    # is a no-op, so a few attempts cover a handful of processes opening a new database at once.
    for attempt in range(1, WAL_SWITCH_ATTEMPTS + 1):
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            if attempt == WAL_SWITCH_ATTEMPTS:
                raise
        else:
            return


def _begin_transaction(connection: Connection) -> None:
    if connection.get_execution_options().get("write_lock", False):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")
