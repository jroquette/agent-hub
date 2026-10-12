"""A canonical event as the store keeps it: with its append sequence and storage-minted fields."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.events.event import Event, UtcTimestamp

# The canonical text form of a UUID (lowercase, hyphenated); the store mints UUIDv7s.
UUID_TEXT_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

type EventId = Annotated[str, Field(pattern=UUID_TEXT_PATTERN)]


class StoredEvent(BaseModel):
    """An event read back from the store.

    ``seq`` is the append sequence (1 for the first event ever appended): ordering, cursors and
    stream resumption use it. ``event_id`` is the storage id minted at append (UUIDv7) and the
    SSE ``id``. ``received_at`` is when the store appended it; rows appended before Phase 2
    have none. The event's identity stays ``event.key``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=1)
    event_id: EventId
    received_at: UtcTimestamp | None
    event: Event
