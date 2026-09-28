"""The EventStore port: where canonical events are kept (SQLite now, Postgres later)."""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agent_hub.core.events.event import Event


class AppendResult(BaseModel):
    """How many events an append wrote and how many it skipped as duplicates."""

    model_config = ConfigDict(frozen=True)

    appended: int
    duplicates: int


class EventStore(Protocol):
    """An append-only store of events, idempotent by ``(source, source_id)``.

    No update or delete exists: a stored event is never changed or removed.
    """

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append a batch all-or-nothing, in one transaction.

        An event equal to a stored one, or repeated in the batch, is counted as a duplicate
        and not written again. An event whose key matches a stored or earlier event with
        different content raises ``EventConflictError`` and nothing of the batch is written.
        """
        ...

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        ...
