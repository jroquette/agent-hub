"""The SQLite ``EventStore`` adapter and the entry point that opens it."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, RowMapping, insert, select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from agent_hub.core.events.append_plan import plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_store import AppendResult
from agent_hub.storage.db import events
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError
from agent_hub.storage.migration import upgrade_to_head

# Keys per lookup query: two bound parameters each, far below SQLite's parameter limit.
KEYS_PER_QUERY = 500
EVENT_FIELDS = tuple(Event.model_fields)


class SqliteEventStore:
    """An ``EventStore`` on a SQLite file migrated to head.

    An append reads the stored events with the batch's keys and writes the new ones in one
    ``BEGIN IMMEDIATE`` transaction, so no other writer runs between the read and the write.
    A conflict leaves as core's ``EventConflictError``, raised before anything is written.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append a batch all-or-nothing (see ``EventStore.append``)."""
        return self._append_once(events)

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        with self._engine.connect() as connection:
            rows = connection.execute(select(events).order_by(events.c.id)).mappings().all()
        return [_to_event(row) for row in rows]

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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        msg = f"cannot create the directory of the event database {path}: {error}"
        raise DatabaseAccessError(msg) from error
    upgrade_to_head(f"sqlite:///{path}")
    engine = create_sqlite_engine(path)
    try:
        # Connect once now, so the journal mode is set and an unusable file fails here.
        with engine.connect():
            pass
    except SQLAlchemyError as error:
        msg = f"cannot open the event database {path}: {error}"
        raise DatabaseAccessError(msg) from error
    return SqliteEventStore(engine)


def _to_row(event: Event) -> dict[str, Any]:
    # JSON mode turns the enums into their values; the timestamp stays a datetime for UtcDateTime.
    return event.model_dump(mode="json") | {"timestamp": event.timestamp}


def _to_event(row: RowMapping) -> Event:
    return Event.model_validate({field: row[field] for field in EVENT_FIELDS})
