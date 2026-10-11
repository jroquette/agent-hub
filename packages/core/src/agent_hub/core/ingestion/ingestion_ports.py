"""Ports of hook ingestion: map a hook envelope to events, and tail a transcript it points to."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.events.event import Event
from agent_hub.core.ingestion.hook_envelope import HookEnvelope


class TranscriptRef(BaseModel):
    """A transcript a hook names: the main one (Stop, SessionEnd) or a subagent's (SubagentStop)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session: str = Field(min_length=1)
    path: str = Field(min_length=1)
    kind: Literal["main", "subagent"]


class HookMapping(BaseModel):
    """The canonical events one envelope yields, and the transcript to read next, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[Event, ...]
    transcript: TranscriptRef | None = None


class TailResult(BaseModel):
    """What one transcript read produced: events, whether the path was refused, lines skipped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[Event, ...]
    refused: bool = False
    skipped_lines: int = Field(default=0, ge=0)


class HookMapper(Protocol):
    """Turns a hook envelope into canonical events (the collector implements it)."""

    def map(self, envelope: HookEnvelope) -> HookMapping:
        """The events of ``envelope``; never raises on missing or unknown hook keys."""
        ...


class TranscriptTailer(Protocol):
    """Reads what a transcript gained since the last read (the collector implements it)."""

    def read_new(self, ref: TranscriptRef) -> TailResult:
        """The events of the lines appended since the last read of ``ref.path``."""
        ...
