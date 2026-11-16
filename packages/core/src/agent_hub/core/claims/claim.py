"""A session's claim on a ticket and when it goes stale (ADR 0064, plan amendment AM-3).

``hub claim take`` writes a ``Claim`` to ``.agent-runs/claims/<ticket>.json``; a second session
reads it and asks ``claim_state`` whether the holder still works. A claim goes stale when its
session ended, not when it was merely quiet (AM-3): with a recorded Claude Code pid, only when no
such process runs or the pid now belongs to a process with another start time, however long the
session has been idle (a session that waits for the owner's merge is idle by design); with no
pid, once its last activity is more than ``STALE_AFTER`` old. No I/O here: the process table is
read through ``ProcessProbe``.

A session that stops for an owner answer records it in the claim (``hub claim wait``, AGH-811):
``question`` (one line, at most ``MAX_QUESTION`` characters) and ``asked_at``, always set together,
and the session's ``title``. All three default to ``None``, so a claim file written before them
still validates.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Final, Protocol, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# A tracker id (``AGH-827``): the claim file's name, so it can never leave the claims folder.
TICKET_PATTERN: Final = r"^[A-Z][A-Z0-9]{0,9}-[0-9]{1,9}$"
# A claim with no recorded pid goes stale after this long without activity (AM-3).
STALE_AFTER: Final = timedelta(hours=24)
# Bounds on the text another session wrote: the whole file stays under 4 KiB.
MAX_TEXT: Final = 512
# The owner question a waiting session records: one short line.
MAX_QUESTION: Final = 200


class Claim(BaseModel):
    """P4's claim record: the ticket, the session holding it, its Claude Code process (``pid``
    and ``started``, the start time ``ps -o lstart=`` prints, both ``None`` when none was found),
    the hub folder, and when it was claimed and last refreshed; then, when the session waits on
    the owner, the ``question`` it asked and when (``asked_at``), and the session's ``title``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket: Annotated[str, Field(pattern=TICKET_PATTERN)]
    session: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
    pid: Annotated[int, Field(gt=0)] | None
    started: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)] | None
    hub: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
    claimed_at: AwareDatetime
    last_activity: AwareDatetime
    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION)] | None = None
    asked_at: AwareDatetime | None = None
    title: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)] | None = None

    @model_validator(mode="after")
    def _pid_and_started_together(self) -> Self:
        if (self.pid is None) != (self.started is None):
            raise ValueError("pid and started are both set or both null")
        return self

    @model_validator(mode="after")
    def _question_and_asked_at_together(self) -> Self:
        if (self.question is None) != (self.asked_at is None):
            raise ValueError("question and asked_at are both set or both null")
        return self


class ProcessProbe(Protocol):
    def started(self, pid: int) -> str | None:
        """The start time ``ps -o lstart=`` prints for ``pid``; ``None`` when no such process."""
        ...


@dataclass(frozen=True)
class Live:
    """The holder still works on the ticket (or cannot be checked): the claim stands."""


@dataclass(frozen=True)
class Stale:
    """The holder's session ended; ``reason`` says why, in words a person can read."""

    reason: str


def claim_state(claim: Claim, now: datetime, probe: ProcessProbe) -> Live | Stale:
    """Whether ``claim`` still holds at ``now`` (AM-3)."""
    if claim.pid is not None:
        running = probe.started(claim.pid)
        if running is None:
            return Stale(f"process {claim.pid} is not running")
        if running != claim.started:
            return Stale(
                f"pid {claim.pid} now belongs to a process started {running}, not {claim.started}"
            )
        return Live()
    if now - claim.last_activity > STALE_AFTER:
        return Stale(
            f"no Claude Code process recorded, idle since {claim.last_activity.isoformat()}"
        )
    return Live()
