"""A session's problems: typed failures, how each was resolved, and the "what went wrong" lines.

Problems are derived on read from stored events (S4); nothing here is stored.
"""

from enum import StrEnum

from pydantic import Field

from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import ApiTimestamp, DerivedView, ViewModel
from agent_hub.core.sessions.session import Actor, SummaryLine

# At most this many "what went wrong" lines per session.
MAX_SUMMARY_LINES = 5


class ProblemKind(StrEnum):
    """What went wrong (S4 with E4)."""

    TOOL_FAILED = "tool_failed"
    COMMAND_EXIT = "command_exit"
    GUARD_DENIED = "guard_denied"
    GUARD_ASK_OPEN = "guard_ask_open"
    GUARD_ASK_DECLINED = "guard_ask_declined"
    INTERRUPTED = "interrupted"
    GATE_FAILED = "gate_failed"
    HOOK_FAILED = "hook_failed"


class Resolution(StrEnum):
    """How a problem ended (S4 with E5).

    ``recovered`` and ``agent_continued`` show as "Handled by the agent", ``open`` as "Agent is
    on it", ``needs_you`` as "Needs you" and ``by_you`` as "You interrupted" or "You declined".
    """

    RECOVERED = "recovered"
    AGENT_CONTINUED = "agent_continued"
    OPEN = "open"
    NEEDS_YOU = "needs_you"
    BY_YOU = "by_you"


class Problem(ViewModel):
    """One problem of a session and the event it comes from.

    ``where`` is the command head, path, pattern, URL, MCP tool or skill of the paired tool
    call (derived on read, at most 120 characters); ``message`` is the stored ``error_message``,
    else ``error_line``, else the rule or the gate's command and exit code.
    """

    event_id: EventId
    kind: ProblemKind
    tool: str | None
    where: str | None
    message: str | None
    at: ApiTimestamp
    actor: Actor
    resolution: Resolution
    resolved_by_event_id: EventId | None = None
    derived: bool = True


class SessionProblems(DerivedView):
    """The problems route: up to 5 deterministic summary lines, then every problem by time.

    ``summary`` is empty when the session has no problem.
    """

    session_id: str
    summary: tuple[SummaryLine, ...] = Field(max_length=MAX_SUMMARY_LINES)
    items: tuple[Problem, ...]
