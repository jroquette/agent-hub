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

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

BUSY_TIMEOUT_MS = 5000


def create_sqlite_engine(path: Path) -> Engine:
    """An engine on the SQLite file at ``path``; SQLite creates the file on first connect."""
    # No pool: each use opens and closes its own SQLite connection, so a store needs no close()
    # and no connection outlives the transaction that used it.
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
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
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _begin_transaction(connection: Connection) -> None:
    if connection.get_execution_options().get("write_lock", False):
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.exec_driver_sql("BEGIN")
