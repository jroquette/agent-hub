"""The SQLite ``AgentSessionStore`` adapter (P3, P10) and the entry point that opens it.

Agent sessions and their logs live in the ``agent_sessions`` and ``agent_session_records``
tables of the hub web database (migration 0004; the list's glimpse columns, 0005). Every write
runs in one ``BEGIN IMMEDIATE`` transaction, so an append reads ``last_seq`` and writes its
records with no other writer in between: the log stays gap-free. SQLite's foreign key
enforcement is off on these connections, so the store deletes a session's records itself
(``delete``, ``purge_ended_before``) instead of relying on the ``ON DELETE CASCADE`` the schema
declares.

Database errors leave as ``DatabaseAccessError`` (``DatabaseBusyError`` past the busy
timeout); their messages carry no record text (the engine hides bound parameters).
"""

import json
import sqlite3
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Unpack

from sqlalchemy import Connection, Engine, RowMapping, delete, insert, select, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from agent_hub.core.agent_sessions.agent_session import (
    TERMINAL_STATUSES,
    AgentSession,
    AgentSessionKind,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError, StoreSequenceError
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.agent_sessions.store import AgentSessionFields
from agent_hub.storage.db import agent_session_records, agent_sessions
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError, describe_database_error
from agent_hub.storage.event_store import DatabaseBusyError
from agent_hub.storage.migration import upgrade_to_head

# Session ids per delete statement, far below SQLite's parameter limit.
IDS_PER_STATEMENT = 500
_TERMINAL = tuple(status.value for status in TERMINAL_STATUSES)


class SqliteAgentSessionStore:
    """An ``AgentSessionStore`` on a SQLite database migrated to head (see the module doc)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, session: AgentSession) -> None:
        """Store a new session; a non-zero ``last_seq`` is refused, ``open_permission`` dropped."""
        if session.last_seq != 0:
            msg = "a new agent session starts at last_seq 0"
            raise ValueError(msg)
        with self._writing() as connection:
            connection.execute(insert(agent_sessions), _to_row(session) | {"stored_bytes": 0})

    def append(self, agent_session_id: str, records: Sequence[LogRecord]) -> None:
        """Add records gap-free in one transaction (``StoreSequenceError`` writes nothing)."""
        with self._writing() as connection:
            row = _session_row(connection, agent_session_id)
            expected = int(row["last_seq"]) + 1
            for record in records:
                if record.seq != expected:
                    raise StoreSequenceError(agent_session_id, expected=expected, got=record.seq)
                expected += 1
            if not records:
                return
            connection.execute(
                insert(agent_session_records),
                [_record_row(agent_session_id, record) for record in records],
            )
            added = sum(record.text_bytes for record in records)
            connection.execute(
                update(agent_sessions)
                .where(agent_sessions.c.id == agent_session_id)
                .values(last_seq=expected - 1, stored_bytes=agent_sessions.c.stored_bytes + added)
            )

    def update(self, agent_session_id: str, **fields: Unpack[AgentSessionFields]) -> AgentSession:
        """Change some fields, validated as ``AgentSession`` says; answers the stored session."""
        with self._writing() as connection:
            current = _to_session(_session_row(connection, agent_session_id))
            updated = AgentSession.model_validate(current.model_dump() | dict(fields))
            changed = {name: _to_row(updated)[name] for name in fields}
            connection.execute(
                update(agent_sessions)
                .where(agent_sessions.c.id == agent_session_id)
                .values(**changed)
            )
        return updated

    def get(self, agent_session_id: str) -> AgentSession:
        """One session."""
        with self._reading() as connection:
            return _to_session(_session_row(connection, agent_session_id))

    def list(
        self,
        *,
        project: str | None = None,
        status: AgentSessionStatus | None = None,
        kind: AgentSessionKind | None = None,
        limit: int = 200,
    ) -> tuple[AgentSession, ...]:
        """Sessions matching every filter given, newest first, at most ``limit``."""
        statement = select(agent_sessions)
        if project is not None:
            statement = statement.where(agent_sessions.c.project == project)
        if status is not None:
            statement = statement.where(agent_sessions.c.status == status.value)
        if kind is not None:
            statement = statement.where(agent_sessions.c.kind == kind)
        statement = statement.order_by(
            agent_sessions.c.created_at.desc(), agent_sessions.c.id.desc()
        ).limit(limit)
        with self._reading() as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(_to_session(row) for row in rows)

    def records(
        self,
        agent_session_id: str,
        *,
        after: int = 0,
        limit: int = 200,
        kinds: Collection[RecordKind] | None = None,
    ) -> tuple[LogRecord, ...]:
        """The records with ``seq`` above ``after``, in order, at most ``limit`` (of ``kinds``
        only, when given)."""
        table = agent_session_records
        statement = select(table).where(
            table.c.agent_session_id == agent_session_id, table.c.seq > after
        )
        if kinds is not None:
            statement = statement.where(table.c.kind.in_(sorted(kinds)))
        statement = statement.order_by(table.c.seq).limit(limit)
        with self._reading() as connection:
            _session_row(connection, agent_session_id)
            rows = connection.execute(statement).mappings().all()
        return tuple(_to_record(row) for row in rows)

    def link_of(self, project: str, claude_session_id: str) -> str | None:
        """The id of the newest agent session of ``project`` driving that Claude session."""
        statement = (
            select(agent_sessions.c.id)
            .where(
                agent_sessions.c.project == project,
                agent_sessions.c.claude_session_id == claude_session_id,
            )
            .order_by(agent_sessions.c.created_at.desc(), agent_sessions.c.id.desc())
            .limit(1)
        )
        with self._reading() as connection:
            found = connection.execute(statement).scalar()
        return None if found is None else str(found)

    def end_unfinished(self, at: datetime, reason: EndReason) -> int:
        """End every session not yet ``ended`` or ``failed``; answers how many."""
        statement = (
            update(agent_sessions)
            .where(agent_sessions.c.status.not_in(_TERMINAL))
            .values(
                status=AgentSessionStatus.ENDED.value,
                end_reason=reason.value,
                ended_at=at,
                updated_at=at,
            )
        )
        with self._writing() as connection:
            return int(connection.execute(statement).rowcount)

    def purge_ended_before(self, cutoff: datetime) -> int:
        """Remove terminal sessions that ended before ``cutoff``, records first."""
        statement = select(agent_sessions.c.id).where(
            agent_sessions.c.status.in_(_TERMINAL), agent_sessions.c.ended_at < cutoff
        )
        with self._writing() as connection:
            found: Sequence[object] = connection.execute(statement).scalars().all()
            ids = [str(agent_session_id) for agent_session_id in found]
            for start in range(0, len(ids), IDS_PER_STATEMENT):
                _delete_sessions(connection, ids[start : start + IDS_PER_STATEMENT])
        return len(ids)

    def delete(self, agent_session_id: str) -> None:
        """Remove one session and its records."""
        with self._writing() as connection:
            _session_row(connection, agent_session_id)
            _delete_sessions(connection, [agent_session_id])

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


def open_agent_session_store(path: Path) -> SqliteAgentSessionStore:
    """Open the agent session store in the database at ``path``, creating its directories and
    upgrading it to head."""
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
    return SqliteAgentSessionStore(engine)


def _session_row(connection: Connection, agent_session_id: str) -> RowMapping:
    statement = select(agent_sessions).where(agent_sessions.c.id == agent_session_id)
    row = connection.execute(statement).mappings().first()
    if row is None:
        raise AgentSessionNotFoundError(agent_session_id)
    return row


def _delete_sessions(connection: Connection, ids: Sequence[str]) -> None:
    connection.execute(
        delete(agent_session_records).where(agent_session_records.c.agent_session_id.in_(ids))
    )
    connection.execute(delete(agent_sessions).where(agent_sessions.c.id.in_(ids)))


def _to_row(session: AgentSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "kind": session.kind,
        "project": session.project,
        "workdir_id": session.workdir_id,
        "workdir_label": session.workdir_label,
        "claude_session_id": session.claude_session_id,
        "cloud_id": session.cloud_id,
        "url": session.url,
        "status": session.status.value,
        "mode": session.mode,
        "model": session.model,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
        "end_reason": None if session.end_reason is None else session.end_reason.value,
        "cost_usd": None if session.cost_usd is None else str(session.cost_usd),
        "usage": None if session.usage is None else session.usage.model_dump(mode="json"),
        "last_seq": session.last_seq,
        "last_prompt": session.last_prompt,
        "last_reply": session.last_reply,
        "changed_files": [item.model_dump(mode="json") for item in session.changed_files],
    }


def _to_session(row: RowMapping) -> AgentSession:
    fields = {name: row[name] for name in AgentSession.model_fields if name in row}
    if row["cost_usd"] is not None:
        fields["cost_usd"] = Decimal(row["cost_usd"])
    return AgentSession.model_validate(fields)


def _record_row(agent_session_id: str, record: LogRecord) -> dict[str, Any]:
    return {"agent_session_id": agent_session_id, **record.model_dump(mode="python")}


def _to_record(row: RowMapping) -> LogRecord:
    return LogRecord.model_validate({name: row[name] for name in LogRecord.model_fields})


def _database_error(error: SQLAlchemyError, action: str) -> DatabaseAccessError:
    description = describe_database_error(error)
    if _is_busy(error):
        return DatabaseBusyError(f"the agent session database is busy: {description}")
    return DatabaseAccessError(f"cannot {action} the agent session database: {description}")


def _is_busy(error: SQLAlchemyError) -> bool:
    code = getattr(getattr(error, "orig", None), "sqlite_errorcode", None)
    return (
        isinstance(error, OperationalError)
        and code is not None
        and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    )
