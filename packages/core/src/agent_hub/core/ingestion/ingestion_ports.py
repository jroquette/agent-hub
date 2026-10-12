"""Ports of hook ingestion: map a hook envelope to events, and tail a transcript it points to.

A tail read is two-phase: ``read_new`` returns the events and the position it reached, and the
caller commits that position only after the events are stored.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.events.event import Event
from agent_hub.core.ingestion.hook_envelope import HookEnvelope


class TranscriptRef(BaseModel):
    """A transcript a hook names: the main one (Stop, SessionEnd) or a subagent's (SubagentStop).

    ``project``, ``repo`` and ``agent`` are who the transcript's events belong to, as the hook
    that named it was attributed; ``session`` is used for lines that name none.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = Field(min_length=1)
    repo: str | None = None
    agent: str | None = None
    session: str = Field(min_length=1)
    path: str = Field(min_length=1)
    kind: Literal["main", "subagent"]


class HookMapping(BaseModel):
    """The canonical events one envelope yields, and the transcript to read next, if any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[Event, ...]
    transcript: TranscriptRef | None = None


class TailPosition(BaseModel):
    """Where one transcript read ended, as the tailer that made it knows it.

    The tailer moves its offset there only when the position is committed, so a read whose
    events were never stored is read again next time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    version: int = Field(ge=0)


class TailResult(BaseModel):
    """What one transcript read produced: events, whether the path was refused, lines skipped.

    ``position`` is where the read ended; None when nothing was read (a refused path).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    events: tuple[Event, ...]
    refused: bool = False
    skipped_lines: int = Field(default=0, ge=0)
    position: TailPosition | None = None


class HookMapper(Protocol):
    """Turns a hook envelope into canonical events (the collector implements it)."""

    def map(self, envelope: HookEnvelope) -> HookMapping:
        """The events of ``envelope``; never raises on missing or unknown hook keys."""
        ...


class TranscriptTailer(Protocol):
    """Reads what a transcript gained since the last read (the collector implements it)."""

    def read_new(self, ref: TranscriptRef) -> TailResult:
        """The events of the lines appended since the last committed read of ``ref.path``."""
        ...

    def commit(self, position: TailPosition) -> None:
        """Move the read offset to ``position`` once its events are stored; stale: a no-op."""
        ...
