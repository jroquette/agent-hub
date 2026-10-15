"""Approvals folded from ``gate.request`` events and what answered them (D24, D14, E3).

A request is decided, in this order of evidence:

1. a hook ``tool.result`` with the guard ask's tool use id: the tool ran, so it was approved
   (``ok`` or ``error``; E3), or the guard denied it (``denied``, declined);
2. a ``gate.result`` with the same ``gate_id``: its ``result`` says how;
3. a transcript ``tool.result`` with the tool use id: ``ok`` approved; an error is the refusal
   Claude Code writes when the person says no (declined, inferred);
4. the session's turn ending after the request (its next user prompt or ``session.end``)
   without the tool running: declined, inferred. For a permission prompt, a tool that ran
   before that is taken as approved (inferred);
5. for a workflow run's gate (session ``run:<id>``), the run ending or the gate's step ending
   other than ``ok`` after the request (abandoned, skipped or failed on resume): declined,
   inferred. Its "How to decide" is ``hub workflow approve|reject|respond <run>``.

Stop hooks yield no event (E4); a Stop after a refused ask shows up through the transcript
tail it triggers (rule 3). The fold only reads events: it is pure and order-independent.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

from agent_hub.core.approvals.approval import Approval, ApprovalKind, ApprovalStatus
from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events

_APPROVAL_KINDS = frozenset(kind.value for kind in ApprovalKind)
_RESULT_STATUS: Mapping[str, ApprovalStatus] = {
    "passed": "approved",
    "approved": "approved",
    "failed": "rejected",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
    "declined": "declined",
}
_TOOL_RAN = frozenset({"ok", "error"})
_RUN_SESSION = "run:"


class Decision(NamedTuple):
    """How a request was answered, by which event, and whether that is deduced."""

    status: ApprovalStatus
    event: StoredEvent
    inferred: bool


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _gate_id(stored: StoredEvent) -> str:
    return _text(stored.event.payload.get("gate_id")) or stored.event_id


def _kind(stored: StoredEvent) -> ApprovalKind | None:
    kind = stored.event.payload.get("kind")
    return ApprovalKind(kind) if isinstance(kind, str) and kind in _APPROVAL_KINDS else None


def _is_turn_end(stored: StoredEvent) -> bool:
    event = stored.event
    if event.type == EventType.SESSION_END:
        return True
    return event.type == EventType.MESSAGE and event.payload.get("role") == "user"


def _tool_results(events: Sequence[StoredEvent], tool_use_id: str) -> list[StoredEvent]:
    return [
        stored
        for stored in events
        if stored.event.type == EventType.TOOL_RESULT
        and stored.event.payload.get("tool_use_id") == tool_use_id
    ]


def _by_hook_result(results: Sequence[StoredEvent]) -> Decision | None:
    for stored in results:
        if stored.event.source != EventSource.CLAUDE_CODE:
            continue
        status = stored.event.payload.get("status")
        if status in _TOOL_RAN:
            return Decision("approved", stored, inferred=False)
        if status == "denied":
            return Decision("declined", stored, inferred=False)
    return None


def _by_gate_result(events: Sequence[StoredEvent], gate_id: str) -> Decision | None:
    for stored in events:
        event = stored.event
        if event.type != EventType.GATE_RESULT or event.payload.get("gate_id") != gate_id:
            continue
        status = _RESULT_STATUS.get(str(event.payload.get("result")))
        if status is not None:
            return Decision(status, stored, inferred=False)
    return None


def _by_transcript_result(results: Sequence[StoredEvent]) -> Decision | None:
    for stored in results:
        if stored.event.source != EventSource.TRANSCRIPT:
            continue
        if stored.event.payload.get("status") == "ok":
            return Decision("approved", stored, inferred=False)
        return Decision("declined", stored, inferred=True)
    return None


def _by_turn_end(
    request: StoredEvent, session_events: Sequence[StoredEvent], kind: ApprovalKind
) -> Decision | None:
    for stored in session_events:
        if stored.event.timestamp <= request.event.timestamp:
            continue
        if (
            kind == ApprovalKind.PERMISSION
            and stored.event.type == EventType.TOOL_RESULT
            and stored.event.source == EventSource.CLAUDE_CODE
        ):
            return Decision("approved", stored, inferred=True)
        if _is_turn_end(stored):
            return Decision("declined", stored, inferred=True)
    return None


def _by_run_close(request: StoredEvent, session_events: Sequence[StoredEvent]) -> Decision | None:
    for stored in session_events:
        event = stored.event
        if event.timestamp <= request.event.timestamp:
            continue
        step_closed = (
            event.type == EventType.STEP_END
            and event.step == request.event.step
            and event.payload.get("status") != "ok"
        )
        if event.type == EventType.RUN_END or step_closed:
            return Decision("declined", stored, inferred=True)
    return None


def _decide(
    request: StoredEvent, kind: ApprovalKind, session_events: Sequence[StoredEvent]
) -> Decision | None:
    gate_id = _gate_id(request)
    results = _tool_results(session_events, gate_id) if kind == ApprovalKind.GUARD_ASK else []
    decision = _by_hook_result(results) or _by_gate_result(session_events, gate_id)
    if decision is None:
        decision = _by_transcript_result(results)
    if decision is None and kind in {ApprovalKind.GUARD_ASK, ApprovalKind.PERMISSION}:
        decision = _by_turn_end(request, session_events, kind)
    if decision is None and request.event.session.startswith(_RUN_SESSION):
        decision = _by_run_close(request, session_events)
    return decision


def _title(request: StoredEvent, kind: ApprovalKind) -> str:
    payload = request.event.payload
    name = _text(payload.get("name"))
    feature = _text(payload.get("feature"))
    path = _text(payload.get("path"))
    if name is not None:
        return name
    if kind in {ApprovalKind.PLAN, ApprovalKind.SPEC} and feature is not None:
        return f"Approve {kind.value} for {feature}"
    if kind == ApprovalKind.GUARD_ASK:
        return f"Edit {path} needs approval" if path else "Tool call needs approval"
    if kind == ApprovalKind.PERMISSION:
        return "Permission prompt"
    return f"{kind.value.replace('_', ' ').capitalize()} needs approval"


def _approval(
    request: StoredEvent,
    kind: ApprovalKind,
    *,
    decision: Decision | None,
    hub_path: str | None,
) -> Approval:
    event = request.event
    payload = event.payload
    resume = f"claude --resume {event.session}"
    if event.session.startswith(_RUN_SESSION):
        resume = f"hub workflow approve|reject|respond {event.session.removeprefix(_RUN_SESSION)}"
    return Approval(
        id=_gate_id(request),
        project=event.project,
        repo=event.repo,
        kind=kind,
        title=_title(request, kind),
        status="open" if decision is None else decision.status,
        decided=decision is not None,
        inferred=decision is not None and decision.inferred,
        gate_id=_gate_id(request),
        session_id=event.session,
        requested_by=event.agent,
        requested_at=event.timestamp,
        decided_at=None if decision is None else decision.event.event.timestamp,
        path=_text(payload.get("path")),
        rule=_text(payload.get("rule")),
        feature=_text(payload.get("feature")),
        hub_path=hub_path,
        how_to_decide=resume if hub_path is None else f"cd {hub_path} && {resume}",
        request_event_id=request.event_id,
        decision_event_id=None if decision is None else decision.event.event_id,
    )


def fold_approvals(
    events: Iterable[StoredEvent], *, hub_paths: Mapping[str, str] | None = None
) -> dict[str, Approval]:
    """Every approval requested in ``events``, by id (its ``gate_id``).

    ``hub_paths`` maps a project to its hub's path, for "How to decide". When one gate id is
    requested twice, the first request counts.
    """
    ordered = canonical_events(events)
    by_session: dict[str, list[StoredEvent]] = {}
    for stored in ordered:
        by_session.setdefault(stored.event.session, []).append(stored)
    approvals: dict[str, Approval] = {}
    for stored in ordered:
        kind = _kind(stored) if stored.event.type == EventType.GATE_REQUEST else None
        if kind is None or _gate_id(stored) in approvals:
            continue
        decision = _decide(stored, kind, by_session[stored.event.session])
        hub_path = (hub_paths or {}).get(stored.event.project)
        approvals[_gate_id(stored)] = _approval(stored, kind, decision=decision, hub_path=hub_path)
    return approvals


def open_gate_ids(events: Iterable[StoredEvent]) -> frozenset[str]:
    """The gate ids of the approvals in ``events`` still waiting for a person."""
    return frozenset(
        approval_id
        for approval_id, approval in fold_approvals(events).items()
        if not approval.decided
    )
