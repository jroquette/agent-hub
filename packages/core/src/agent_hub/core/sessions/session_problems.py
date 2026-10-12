"""A session's problems (S4, E4, E5): typed failures, how each was resolved, what went wrong.

``fold_problems`` reads one session's events and its current status; it is pure, ignores the
order the events arrived in and their repeats, and works on events stored before AGH-201 (no
``error_message``, ``skill`` or ``git_branch``). Every problem is one counted fact (the winner of
its fact key), resolved in canonical order (timestamp, then ``(source, source_id)``):

* an interruption is ``by_you``, a declined guard ask ``by_you``, an open one ``needs_you``;
* a later ``ok`` result of the same actor for the same tool and ``where`` (or a later pass of the
  same gate) is ``recovered``; a later tool call of the same actor is ``agent_continued``;
* otherwise the problem is ``open`` while the session is live and ``needs_you`` once it waits,
  idles or ends.

``where`` is derived on read from the paired ``tool.call`` (L1), never stored.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.fact_keys import canonical_events, resolve_facts
from agent_hub.core.redaction.redact import clip
from agent_hub.core.sessions.problem import (
    MAX_SUMMARY_LINES,
    Problem,
    ProblemKind,
    Resolution,
    SessionProblems,
)
from agent_hub.core.sessions.session import Actor, ProblemCounts, SessionStatus, SummaryLine
from agent_hub.core.sessions.session_actors import MAIN_ACTOR, actor_key, fold_actors
from agent_hub.core.sessions.session_label import workflow_name

WHERE_LIMIT: Final = 120
BASH_TOOL: Final = "Bash"
GUARD_HOOK: Final = "guard"
_INTERRUPTED: Final = ("interrupted", "[request interrupted")
_GATE_PASSED: Final = frozenset({"passed", "approved"})
_HANDLED: Final = frozenset({Resolution.RECOVERED, Resolution.AGENT_CONTINUED})

type ActorKey = tuple[str, str | None]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _short(value: str) -> str:
    return clip(" ".join(value.split()), WHERE_LIMIT)


def _where_of_call(payload: Mapping[str, JsonValue]) -> str | None:
    command = _text(payload.get("command"))
    if command is not None:
        return _short(command)
    for key in ("pattern", "url"):
        value = _text(payload.get(key))
        if value is not None:
            return _short(value)
    server, tool = _text(payload.get("mcp_server")), _text(payload.get("mcp_tool"))
    if server is not None and tool is not None:
        return _short(f"{server}.{tool}")
    skill = _text(payload.get("skill"))
    if skill is not None:
        return _short(workflow_name(skill))
    path = _text(payload.get("path"))
    return None if path is None else _short(path)


def _where_of_gate(payload: Mapping[str, JsonValue]) -> str | None:
    for key in ("where", "name", "path", "command", "kind"):
        value = _text(payload.get(key))
        if value is not None:
            return _short(value)
    return None


def _message(payload: Mapping[str, JsonValue]) -> str | None:
    for key in ("error_message", "error_line"):
        value = _text(payload.get(key))
        if value is not None:
            return value
    rule = _text(payload.get("rule"))
    if rule is not None:
        return f"rule {rule}"
    command = _text(payload.get("command"))
    exit_code = payload.get("exit_code")
    code = (
        f"exit code {exit_code}"
        if isinstance(exit_code, int) and not isinstance(exit_code, bool)
        else None
    )
    parts = [part for part in (command, code) if part is not None]
    return ": ".join(parts) if parts else None


def _same_actor(one: ActorKey, other: ActorKey) -> bool:
    # A subagent's transcript events may lack its id; its type still names it.
    return one[0] == other[0] and (one[1] is None or other[1] is None or one[1] == other[1])


@dataclass(frozen=True, slots=True)
class _Found:
    """A problem found at ``position`` of the winners, before it is resolved."""

    position: int
    stored: StoredEvent
    kind: ProblemKind
    tool: str | None
    where: str | None
    message: str | None
    actor: ActorKey


class _Session:
    """One session's events, as the problems fold reads them."""

    def __init__(self, events: Iterable[StoredEvent], status: SessionStatus) -> None:
        self.ordered = canonical_events(events)
        self.winners: Sequence[StoredEvent] = resolve_facts(self.ordered).winners
        self.status = status
        self.calls = {
            use: stored
            for stored in self.winners
            if stored.event.type == EventType.TOOL_CALL
            and (use := _text(stored.event.payload.get("tool_use_id"))) is not None
        }
        self.asks = {
            approval.request_event_id: approval
            for approval in fold_approvals(self.ordered).values()
            if approval.kind == ApprovalKind.GUARD_ASK
        }
        self.actors = {
            (actor.type or "main", actor.agent_id): actor for actor in fold_actors(self.ordered)
        }

    def call_of(self, stored: StoredEvent) -> StoredEvent | None:
        use = _text(stored.event.payload.get("tool_use_id")) or _text(
            stored.event.payload.get("gate_id")
        )
        return None if use is None else self.calls.get(use)

    def actor(self, key: ActorKey) -> Actor:
        if key == ("main", None):
            return MAIN_ACTOR
        found = self.actors.get(key)
        return found or Actor(kind="subagent", type=key[0], agent_id=key[1])

    def where(self, stored: StoredEvent) -> str | None:
        call = self.call_of(stored)
        return None if call is None else _where_of_call(call.event.payload)

    def tool(self, stored: StoredEvent) -> str | None:
        call = self.call_of(stored)
        tool = _text(stored.event.payload.get("tool"))
        return tool if tool is not None or call is None else _text(call.event.payload.get("tool"))


def _result_kind(payload: Mapping[str, JsonValue], tool: str | None) -> ProblemKind | None:
    status = payload.get("status")
    if status == "denied":
        return ProblemKind.GUARD_DENIED
    if status != "error":
        return None
    text = (_text(payload.get("error_message")) or _text(payload.get("error_line")) or "").strip()
    if text.lower().startswith(_INTERRUPTED):
        return ProblemKind.INTERRUPTED
    hook = _text(payload.get("hook"))
    if hook is not None and hook != GUARD_HOOK:
        return ProblemKind.HOOK_FAILED
    return ProblemKind.COMMAND_EXIT if tool == BASH_TOOL else ProblemKind.TOOL_FAILED


def _find(session: _Session, position: int, stored: StoredEvent) -> _Found | None:
    event = stored.event
    payload = event.payload
    key = actor_key(stored)
    if event.type == EventType.TOOL_RESULT:
        tool = session.tool(stored)
        kind = _result_kind(payload, tool)
        if kind is None:
            return None
        where, message = session.where(stored), _message(payload)
        return _Found(position, stored, kind, tool, where, message, key)
    if event.type == EventType.GATE_REQUEST:
        approval = session.asks.get(stored.event_id)
        if approval is None or approval.status not in {"open", "declined"}:
            return None
        kind = (
            ProblemKind.GUARD_ASK_OPEN
            if approval.status == "open"
            else ProblemKind.GUARD_ASK_DECLINED
        )
        path = _text(payload.get("path"))
        where = _short(path) if path is not None else session.where(stored)
        return _Found(position, stored, kind, session.tool(stored), where, _message(payload), key)
    if event.type == EventType.GATE_RESULT and payload.get("result") == "failed":
        where = _where_of_gate(payload)
        return _Found(
            position, stored, ProblemKind.GATE_FAILED, None, where, _message(payload), key
        )
    return None


def _gate_key(payload: Mapping[str, JsonValue]) -> tuple[object, ...]:
    return tuple(payload.get(key) for key in ("kind", "name", "command", "path"))


def _recovery(session: _Session, found: _Found) -> StoredEvent | None:
    later = session.winners[found.position + 1 :]
    if found.kind == ProblemKind.GATE_FAILED:
        wanted = _gate_key(found.stored.event.payload)
        return next(
            (
                stored
                for stored in later
                if stored.event.type == EventType.GATE_RESULT
                and stored.event.payload.get("result") in _GATE_PASSED
                and _gate_key(stored.event.payload) == wanted
            ),
            None,
        )
    return next(
        (
            stored
            for stored in later
            if stored.event.type == EventType.TOOL_RESULT
            and stored.event.payload.get("status") == "ok"
            and _same_actor(actor_key(stored), found.actor)
            and session.tool(stored) == found.tool
            and session.where(stored) == found.where
        ),
        None,
    )


def _continuation(session: _Session, found: _Found) -> StoredEvent | None:
    return next(
        (
            stored
            for stored in session.winners[found.position + 1 :]
            if stored.event.type == EventType.TOOL_CALL
            and _same_actor(actor_key(stored), found.actor)
        ),
        None,
    )


def _resolve(session: _Session, found: _Found) -> tuple[Resolution, str | None]:
    if found.kind == ProblemKind.INTERRUPTED:
        return Resolution.BY_YOU, None
    if found.kind == ProblemKind.GUARD_ASK_DECLINED:
        approval: Approval | None = session.asks.get(found.stored.event_id)
        return Resolution.BY_YOU, None if approval is None else approval.decision_event_id
    if found.kind == ProblemKind.GUARD_ASK_OPEN:
        return Resolution.NEEDS_YOU, None
    recovery = _recovery(session, found)
    if recovery is not None:
        return Resolution.RECOVERED, recovery.event_id
    continuation = _continuation(session, found)
    if continuation is not None:
        return Resolution.AGENT_CONTINUED, continuation.event_id
    if session.status == SessionStatus.LIVE:
        return Resolution.OPEN, None
    return Resolution.NEEDS_YOU, None


def _problem(session: _Session, found: _Found) -> Problem:
    resolution, resolved_by = _resolve(session, found)
    return Problem(
        event_id=found.stored.event_id,
        kind=found.kind,
        tool=found.tool,
        where=found.where,
        message=found.message,
        at=found.stored.event.timestamp,
        actor=session.actor(found.actor),
        resolution=resolution,
        resolved_by_event_id=resolved_by,
    )


def problem_counts(problems: Iterable[Problem]) -> ProblemCounts:
    """How many of ``problems`` need the owner, are open, were handled, or were the owner's."""
    resolutions = [problem.resolution for problem in problems]
    return ProblemCounts(
        needs_you=resolutions.count(Resolution.NEEDS_YOU),
        open=resolutions.count(Resolution.OPEN),
        handled=sum(1 for resolution in resolutions if resolution in _HANDLED),
        by_you=resolutions.count(Resolution.BY_YOU),
    )


def status_text(problem: Problem) -> str:
    """The owner-facing status of ``problem``: "Needs you", "Handled by the agent"..."""
    match problem.resolution:
        case Resolution.NEEDS_YOU:
            return "Needs you"
        case Resolution.OPEN:
            return "Agent is on it"
        case Resolution.BY_YOU:
            interrupted = problem.kind == ProblemKind.INTERRUPTED
            return "You interrupted" if interrupted else "You declined"
        case _:
            return "Handled by the agent"


def _counts_text(counts: ProblemCounts, total: int) -> str:
    parts = [
        f"{counts.needs_you} {'needs' if counts.needs_you == 1 else 'need'} you"
        if counts.needs_you
        else None,
        f"{counts.open} in progress" if counts.open else None,
        f"{counts.handled} handled by the agent" if counts.handled else None,
        f"{counts.by_you} by you" if counts.by_you else None,
    ]
    noun = "problem" if total == 1 else "problems"
    return f"{total} {noun}: {', '.join(part for part in parts if part is not None)}"


def _line(problem: Problem) -> SummaryLine:
    place = problem.where or problem.tool
    text = f"{status_text(problem)}: {problem.kind.value}"
    return SummaryLine(
        text=text if place is None else f"{text} in {place}", event_id=problem.event_id
    )


def summary_lines(problems: Sequence[Problem]) -> tuple[SummaryLine, ...]:
    """The "what went wrong" lines: a counts line, then needs-you problems first, by time."""
    if not problems:
        return ()
    ranked = [
        *(problem for problem in problems if problem.resolution == Resolution.NEEDS_YOU),
        *(problem for problem in problems if problem.resolution != Resolution.NEEDS_YOU),
    ]
    counts = SummaryLine(
        text=_counts_text(problem_counts(problems), len(problems)), event_id=ranked[0].event_id
    )
    return (counts, *(_line(problem) for problem in ranked[: MAX_SUMMARY_LINES - 1]))


def fold_problems(events: Iterable[StoredEvent], *, status: SessionStatus) -> SessionProblems:
    """The problems of one session (its events, any order) whose status is ``status``."""
    session = _Session(events, status)
    found = [
        problem
        for position, stored in enumerate(session.winners)
        if (problem := _find(session, position, stored)) is not None
    ]
    items = tuple(_problem(session, problem) for problem in found)
    session_id = session.ordered[0].event.session if session.ordered else ""
    return SessionProblems(session_id=session_id, summary=summary_lines(items), items=items)
