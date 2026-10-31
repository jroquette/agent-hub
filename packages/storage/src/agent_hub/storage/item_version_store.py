"""The SQLite ``ItemVersionStore`` adapter (AGH-295, S3) and the entry point that opens it.

Versions live in the ``item_versions`` table of the hub web database (migration 0005). An
append runs in one ``BEGIN IMMEDIATE`` transaction that reads the unit's last ``seq`` before
inserting, so writers queue on the write lock and a loser finds the winner's row: its ``seq`` is
refused with ``ItemVersionSequenceError``, as is a duplicate the unique constraint catches. The
store only inserts and selects: nothing is updated or deleted. ``has_publish`` reads the
``draft_id`` column a ``publish`` fills (A5, A20).

Database errors leave as ``DatabaseAccessError`` (``DatabaseBusyError`` past the busy
timeout); their messages carry no content (the engine hides bound parameters).
"""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, RowMapping, func, insert, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    ItemVersionMeta,
    NewItemVersion,
    VersionOrigin,
)
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError
from agent_hub.storage.db import item_versions
from agent_hub.storage.engine import create_sqlite_engine
from agent_hub.storage.errors import DatabaseAccessError, describe_database_error
from agent_hub.storage.event_store import DatabaseBusyError
from agent_hub.storage.migration import upgrade_to_head

_META_COLUMNS = tuple(column for column in item_versions.columns if column.name != "content")


class SqliteItemVersionStore:
    """An ``ItemVersionStore`` on a SQLite database migrated to head (see the module doc)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, version: NewItemVersion) -> ItemVersion:
        """Store ``version`` when its ``seq`` is the unit's next one, minting a UUIDv7 id."""
        stored = ItemVersion.model_validate(version.model_dump() | {"id": str(uuid.uuid7())})
        table = item_versions
        last_seq = select(func.max(table.c.seq)).where(
            table.c.project == version.project, table.c.unit_path == version.unit_path
        )
        with self._writing() as connection:
            expected = int(connection.execute(last_seq).scalar() or 0) + 1
            if version.seq != expected:
                raise ItemVersionSequenceError(
                    version.project, version.unit_path, expected=expected, got=version.seq
                )
            try:
                connection.execute(insert(table), _to_row(stored))
            except IntegrityError as error:
                # Another writer stored this seq first.
                raise ItemVersionSequenceError(
                    version.project, version.unit_path, expected=version.seq + 1, got=version.seq
                ) from error
        return stored

    def last(self, project: str, unit_path: str) -> ItemVersionMeta | None:
        """The unit's newest version, or None."""
        found = self.page(project, unit_path, limit=1)
        return found[0] if found else None

    def page(
        self, project: str, unit_path: str, *, limit: int = 50, before_seq: int | None = None
    ) -> tuple[ItemVersionMeta, ...]:
        """The unit's versions newest first, below ``before_seq`` when given, without content."""
        table = item_versions
        statement = select(*_META_COLUMNS).where(
            table.c.project == project, table.c.unit_path == unit_path
        )
        if before_seq is not None:
            statement = statement.where(table.c.seq < before_seq)
        statement = statement.order_by(table.c.seq.desc()).limit(limit)
        with self._reading() as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(ItemVersionMeta.model_validate(_to_fields(row)) for row in rows)

    def get(self, project: str, unit_path: str, version_id: str) -> ItemVersion | None:
        """The version ``version_id`` of that unit, with its content, or None."""
        table = item_versions
        statement = select(table).where(
            table.c.project == project, table.c.unit_path == unit_path, table.c.id == version_id
        )
        with self._reading() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else ItemVersion.model_validate(_to_fields(row))

    def has_publish(self, project: str, draft_id: str) -> bool:
        """Whether a version of the project is a ``publish`` of ``draft_id``."""
        table = item_versions
        statement = (
            select(table.c.id)
            .where(
                table.c.project == project,
                table.c.origin == VersionOrigin.PUBLISH.value,
                table.c.draft_id == draft_id,
            )
            .limit(1)
        )
        with self._reading() as connection:
            return connection.execute(statement).first() is not None

    def close(self) -> None:
        """Close the idle connections the store's engine keeps; a later use opens new ones.

        One checked out at that moment is not closed here: it goes back to the old pool when it
        returns, and closes when that pool is garbage collected.
        """
        self._engine.dispose()

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


def open_item_version_store(path: Path) -> SqliteItemVersionStore:
    """Open the item version store in the database at ``path``, creating its directories and
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
    return SqliteItemVersionStore(engine)


def _to_row(version: ItemVersion) -> dict[str, Any]:
    row = version.model_dump(mode="python", exclude={"author"})
    row["kind"] = version.kind.value
    row["origin"] = version.origin.value
    row["author_name"] = None if version.author is None else version.author.name
    row["author_email"] = None if version.author is None else version.author.email
    return row


def _to_fields(row: RowMapping) -> dict[str, Any]:
    fields = dict(row)
    name, email = fields.pop("author_name"), fields.pop("author_email")
    fields["author"] = None if name is None else {"name": name, "email": email}
    return fields


def _database_error(error: SQLAlchemyError, action: str) -> DatabaseAccessError:
    description = describe_database_error(error)
    if _is_busy(error):
        return DatabaseBusyError(f"the item version database is busy: {description}")
    return DatabaseAccessError(f"cannot {action} the item version database: {description}")


def _is_busy(error: SQLAlchemyError) -> bool:
    code = getattr(getattr(error, "orig", None), "sqlite_errorcode", None)
    return (
        isinstance(error, OperationalError)
        and code is not None
        and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    )
