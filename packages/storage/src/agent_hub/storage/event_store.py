"""The SQLite ``EventStore`` adapter and the entry point that opens it."""

import json
import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, RowMapping, Select, func, insert, select, tuple_
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from agent_hub.core.events.append_plan import plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_query import EventPage, EventQuery
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.storage.db import events
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError, describe_database_error
from agent_hub.storage.migration import upgrade_to_head

# Keys per lookup query: two bound parameters each, far below SQLite's parameter limit.
KEYS_PER_QUERY = 500
# The canonical columns; the storage fields (event_id, received_at) are not part of an Event.
EVENT_FIELDS = tuple(Event.model_fields)


class DatabaseBusyError(DatabaseAccessError):
    """Another connection held the database lock for longer than the busy timeout.

    The API answers it with 503 "Collector database busy"; a retry usually succeeds.
    """


class SqliteEventStore:
    """An ``EventStore`` on a SQLite file migrated to head.

    An append reads the stored events with the batch's keys and writes the new ones in one
    ``BEGIN IMMEDIATE`` transaction, so no other writer runs between the read and the write.
    Database errors leave as ``DatabaseAccessError`` (``DatabaseBusyError`` when the lock was
    held past the busy timeout, on a read or an append); a conflict leaves as core's
    ``EventConflictError``, raised before anything is written.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append a batch all-or-nothing (see ``EventStore.append``)."""
        try:
            try:
                return self._append_once(events)
            except IntegrityError:
                # Only reachable when a writer bypassed the write lock and inserted one of our keys
                # after we read. Read again: the key is now stored, so the plan counts it as a
                # duplicate or raises a conflict. A second integrity error is not retried.
                return self._append_once(events)
        except SQLAlchemyError as error:
            raise _write_error(error) from error

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        rows = self._read(select(events).order_by(events.c.id))
        return [_to_event(row) for row in rows]

    def query(self, query: EventQuery) -> EventPage:
        """The stored events matching ``query`` (see ``EventReader.query``).

        Reads on a deferred transaction, so it never waits for the write lock; with WAL it
        sees the last committed append.
        """
        rows = self._read(query_statement(query))
        items = tuple(_to_stored(row) for row in rows[: query.limit])
        has_more = len(rows) > query.limit
        next_after_seq = items[-1].seq if has_more and query.order == "asc" else None
        return EventPage(items=items, next_after_seq=next_after_seq)

    def find(self, event_id: str) -> StoredEvent | None:
        """The stored event with this storage id, or None."""
        rows = self._read(select(events).where(events.c.event_id == event_id))
        return _to_stored(rows[0]) if rows else None

    def high_water_mark(self) -> int:
        """The largest append sequence, 0 when the store is empty."""
        try:
            with self._engine.connect() as connection:
                mark = connection.execute(select(func.max(events.c.id))).scalar()
        except SQLAlchemyError as error:
            raise _read_error(error) from error
        return int(mark or 0)

    def _read(self, statement: Select[Any]) -> list[RowMapping]:
        try:
            with self._engine.connect() as connection:
                return list(connection.execute(statement).mappings().all())
        except SQLAlchemyError as error:
            raise _read_error(error) from error

    def _append_once(self, batch: Sequence[Event]) -> AppendResult:
        with (
            self._engine.connect().execution_options(write_lock=True) as connection,
            connection.begin(),
        ):
            plan = plan_append(batch, self._read_stored(connection, batch))
            if plan.new_events:
                connection.execute(insert(events), [_to_row(event) for event in plan.new_events])
        return AppendResult(appended=len(plan.new_events), duplicates=plan.duplicates)

    def _read_stored(self, connection: Connection, batch: Sequence[Event]) -> dict[EventKey, Event]:
        """The stored events whose keys appear in ``batch``."""
        keys = list(dict.fromkeys((str(event.source), event.source_id) for event in batch))
        stored: dict[EventKey, Event] = {}
        for start in range(0, len(keys), KEYS_PER_QUERY):
            chunk = keys[start : start + KEYS_PER_QUERY]
            key_column = tuple_(events.c.source, events.c.source_id)
            rows = connection.execute(select(events).where(key_column.in_(chunk))).mappings()
            for row in rows:
                event = _to_event(row)
                stored[event.key] = event
        return stored


def open_event_store(path: Path) -> SqliteEventStore:
    """Open the event store at ``path``, creating its directories and upgrading it to head."""
    # The path comes from the user: quoted and escaped, so a message stays on one line.
    quoted = json.dumps(str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        msg = f"cannot create the directory of the event database {quoted}: {error}"
        raise DatabaseAccessError(msg) from error
    upgrade_to_head(path)
    engine = create_sqlite_engine(path)
    try:
        # Connect once now, so the journal mode is set and an unusable file fails here.
        with engine.connect():
            pass
    except SQLAlchemyError as error:
        msg = f"cannot open the event database {quoted}: {describe_database_error(error)}"
        raise DatabaseAccessError(msg) from error
    return SqliteEventStore(engine)


def query_statement(query: EventQuery) -> Select[Any]:
    """The ``SELECT`` that answers ``query``: one row more than its limit, to tell a next page.

    Its filters lead with ``project`` and order by ``id``, so SQLite can use the read indexes.
    """
    conditions = []
    if query.project is not None:
        conditions.append(events.c.project == query.project)
    if query.session is not None:
        conditions.append(events.c.session == query.session)
    if query.types:
        conditions.append(events.c.type.in_(sorted(str(type_) for type_ in query.types)))
    if query.since is not None:
        conditions.append(events.c.timestamp >= query.since)
    if query.until is not None:
        conditions.append(events.c.timestamp < query.until)
    if query.after_seq is not None:
        conditions.append(events.c.id > query.after_seq)
    if query.before_seq is not None:
        conditions.append(events.c.id < query.before_seq)
    order = events.c.id.asc() if query.order == "asc" else events.c.id.desc()
    return select(events).where(*conditions).order_by(order).limit(query.limit + 1)


def _write_error(error: SQLAlchemyError) -> DatabaseAccessError:
    description = describe_database_error(error)
    if _is_busy(error):
        return DatabaseBusyError(f"the event database is busy: {description}")
    return DatabaseAccessError(f"cannot write to the event database: {description}")


def _read_error(error: SQLAlchemyError) -> DatabaseAccessError:
    description = describe_database_error(error)
    if _is_busy(error):
        return DatabaseBusyError(f"the event database is busy: {description}")
    return DatabaseAccessError(f"cannot read the event database: {description}")


def _is_busy(error: SQLAlchemyError) -> bool:
    cause = getattr(error, "orig", None)
    code = getattr(cause, "sqlite_errorcode", None)
    return (
        isinstance(error, OperationalError)
        and code is not None
        and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    )


def _to_row(event: Event) -> dict[str, Any]:
    # JSON mode turns the enums into their values; the timestamp stays a datetime for UtcDateTime.
    # Only new events become rows, so the storage fields are minted once per event.
    return event.model_dump(mode="json") | {
        "timestamp": event.timestamp,
        "event_id": str(uuid.uuid7()),
        "received_at": datetime.now(UTC),
    }


def _to_event(row: RowMapping) -> Event:
    return Event.model_validate({field: row[field] for field in EVENT_FIELDS})


def _to_stored(row: RowMapping) -> StoredEvent:
    return StoredEvent(
        seq=row["id"],
        event_id=row["event_id"],
        received_at=row["received_at"],
        event=_to_event(row),
    )
