"""Session segments and status (D14), from the times a session was active and how it ended.

A session is ``live`` while it had an event in the last 5 minutes or a tool call is still
running, ``idle`` after that, and ``ended`` on ``session.end``; 30 minutes without an event and
without an end close it as ``ended`` with ``end_reason: no_end_event`` (inferred). A later event
opens a new segment. An open ``gate.request`` makes it ``waiting``, before any other live
state. Everything takes ``now`` as an argument: there is no clock here.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from agent_hub.core.sessions.session import Outcome, SessionSegment, SessionStatus

LIVE_WINDOW = timedelta(minutes=5)
END_AFTER = timedelta(minutes=30)
NO_END_EVENT = "no_end_event"


class Activity(BaseModel):
    """One moment a session was active; ``ends`` when it is the session's ``session.end``."""

    model_config = ConfigDict(frozen=True)

    at: datetime
    ends: bool = False
    end_reason: str | None = None
    outcome: Outcome | None = None


class _OpenSegment:
    def __init__(self, index: int, started_at: datetime) -> None:
        self.index = index
        self.started_at = started_at

    def close(
        self, ended_at: datetime, end_reason: str | None, *, inferred: bool
    ) -> SessionSegment:
        return SessionSegment(
            index=self.index,
            started_at=self.started_at,
            ended_at=ended_at,
            end_reason=end_reason,
            end_inferred=inferred,
        )

    def still_open(self) -> SessionSegment:
        return SessionSegment(
            index=self.index, started_at=self.started_at, ended_at=None, end_reason=None
        )


def session_segments(activity: Sequence[Activity], *, now: datetime) -> tuple[SessionSegment, ...]:
    """The segments of a session whose ``activity`` is sorted by time."""
    segments: list[SessionSegment] = []
    current: _OpenSegment | None = None
    last_at: datetime | None = None
    for moment in activity:
        if current is not None and last_at is not None and moment.at - last_at >= END_AFTER:
            segments.append(current.close(last_at, NO_END_EVENT, inferred=True))
            current = None
        if current is None:
            current = _OpenSegment(len(segments) + 1, moment.at)
        last_at = moment.at
        if moment.ends:
            segments.append(current.close(moment.at, moment.end_reason, inferred=False))
            current = None
    if current is not None and last_at is not None:
        if now - last_at >= END_AFTER:
            segments.append(current.close(last_at, NO_END_EVENT, inferred=True))
        else:
            segments.append(current.still_open())
    return tuple(segments)


def session_status(
    segments: Sequence[SessionSegment],
    *,
    last_activity_at: datetime,
    now: datetime,
    has_open_gate: bool,
    has_open_tool_call: bool,
) -> SessionStatus:
    """Where the session is now, by D14."""
    if not segments or segments[-1].ended_at is not None:
        return SessionStatus.ENDED
    if has_open_gate:
        return SessionStatus.WAITING
    if has_open_tool_call or now - last_activity_at < LIVE_WINDOW:
        return SessionStatus.LIVE
    return SessionStatus.IDLE
