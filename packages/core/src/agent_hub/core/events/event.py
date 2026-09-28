"""The canonical event every source is turned into, and its identity ``(source, source_id)``."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, NamedTuple

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
)


class EventType(StrEnum):
    """The closed list of event types in the SPEC; widening it later is a compatible change."""

    SESSION_START = "session.start"
    SESSION_END = "session.end"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    MESSAGE = "message"
    REASONING = "reasoning"
    DECISION = "decision"
    GATE_REQUEST = "gate.request"
    GATE_RESULT = "gate.result"
    LEARNING_PROPOSED = "learning.proposed"
    LEARNING_ACCEPTED = "learning.accepted"


class EventSource(StrEnum):
    """Where an event comes from; with ``source_id`` it identifies the event."""

    CLAUDE_CODE = "claude_code"
    TRANSCRIPT = "transcript"
    OTEL = "otel"
    EXECUTOR = "executor"
    GITHUB = "github"
    LINEAR = "linear"


class EventKey(NamedTuple):
    """The identity of an event: two events with the same key are the same event."""

    source: EventSource
    source_id: str


def _reject_number(value: object) -> object:
    # A Unix number carries no offset, so it cannot say which instant the source meant.
    if isinstance(value, int | float):
        msg = "timestamp must be an ISO 8601 string with an offset, not a number"
        raise ValueError(msg)
    return value


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


type UtcTimestamp = Annotated[
    AwareDatetime, BeforeValidator(_reject_number), AfterValidator(_to_utc)
]


class Event(BaseModel):
    """A canonical event, validated strictly: unknown fields, types and sources are rejected.

    ``timestamp`` must carry an offset and is normalized to UTC, so the same instant written
    with another offset gives an equal event. ``Event`` is not hashable (``payload`` is a
    dict); use ``key`` to index events.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1)
    session: str = Field(min_length=1)
    type: EventType
    timestamp: UtcTimestamp
    source: EventSource
    source_id: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    repo: str | None = None
    agent: str | None = None
    workflow: str | None = None
    step: str | None = None

    @property
    def key(self) -> EventKey:
        """The event's identity ``(source, source_id)``."""
        return EventKey(source=self.source, source_id=self.source_id)
