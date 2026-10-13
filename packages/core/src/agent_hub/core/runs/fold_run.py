"""The WorkflowRun read model, folded from ``hub run``'s executor events (D9, D16, AC-200.25).

Steps are keyed ``(step, attempt)``: a loop back into verify is verify attempt 2. The first
``run.end`` in source order decides how the run ended; a later one is a conflicting copy and
is ignored. Without a ``run.end``, a failed step with nothing after it means the run failed
there; otherwise the run is at the stage of its latest step. Pure and order-independent.
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, get_args
from urllib.parse import urlsplit

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.fact_keys import canonical_events, resolve_facts
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.workflow_run import (
    IssueRef,
    RunCaps,
    RunDelivery,
    RunFailure,
    RunGateResult,
    RunStep,
    StepKey,
    WorkflowRun,
)
from agent_hub.core.sessions.session import Session
from agent_hub.core.sessions.session_cost import run_cost

RUN_SESSION_PREFIX = "run:"
DEFAULT_WORKFLOW = "issue-to-pr"
STEP_STAGES: Mapping[StepKey, Stage] = {
    "pick": Stage.PICKED,
    "worktree": Stage.WORKTREE,
    "implement": Stage.IMPLEMENTING,
    "verify": Stage.VERIFYING,
    "pr": Stage.PR_OPEN,
}
RUN_SOURCES_MISSING = (EventSource.LINEAR, EventSource.GITHUB)
_STEP_TYPES = frozenset({EventType.STEP_START, EventType.STEP_END})
_DELIVERIES: Final[tuple[RunDelivery, ...]] = get_args(RunDelivery.__value__)
_NOT_DELIVERED: Final = frozenset({"no_changes", "blocked"})
_STAGES = frozenset(stage.value for stage in Stage)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _https_url(value: object) -> str | None:
    """``value`` when it is an absolute https URL with a host, else None (never javascript:)."""
    text = _text(value)
    if text is None or any(ch.isspace() or not ch.isprintable() or ch == "\\" for ch in text):
        return None
    try:
        parts = urlsplit(text)
    except ValueError:  # e.g. an unclosed IPv6 bracket
        return None
    return text if parts.scheme == "https" and parts.hostname else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _stage(value: object) -> Stage | None:
    return Stage(value) if isinstance(value, str) and value in _STAGES else None


def run_id_of(stored: StoredEvent) -> str | None:
    """The run an executor event belongs to, or None for any other event."""
    event = stored.event
    if event.source != EventSource.EXECUTOR:
        return None
    run = _text(event.payload.get("run"))
    if run is None and event.session.startswith(RUN_SESSION_PREFIX):
        run = event.session.removeprefix(RUN_SESSION_PREFIX) or None
    return run


def _step_key(stored: StoredEvent) -> StepKey | None:
    key = stored.event.step or _text(stored.event.payload.get("step"))
    for known in STEP_STAGES:
        if key == known:
            return known
    return None


def _attempt(stored: StoredEvent) -> int:
    attempt = _int(stored.event.payload.get("attempt"))
    return attempt if attempt is not None and attempt >= 1 else 1


def _step_session_ids(key: StepKey, attempt: int, sessions: Sequence[Session]) -> tuple[str, ...]:
    return tuple(
        session.id
        for session in sessions
        if session.step == key and session.attempt in {attempt, None}
    )


def _steps(winners: Sequence[StoredEvent], sessions: Sequence[Session]) -> tuple[RunStep, ...]:
    starts: dict[tuple[StepKey, int], StoredEvent] = {}
    ends: dict[tuple[StepKey, int], StoredEvent] = {}
    for stored in winners:
        key = _step_key(stored)
        if key is None or stored.event.type not in _STEP_TYPES:
            continue
        target = starts if stored.event.type == EventType.STEP_START else ends
        target.setdefault((key, _attempt(stored)), stored)
    max_attempts: dict[str, int] = {}
    for key, attempt in {*starts, *ends}:
        max_attempts[key] = max(max_attempts.get(key, 1), attempt)
    steps = []
    for step_id in {*starts, *ends}:
        start, end = starts.get(step_id), ends.get(step_id)
        failed = end is not None and end.event.payload.get("status") == "failed"
        steps.append(
            RunStep(
                key=step_id[0],
                attempt=step_id[1],
                max_attempts=max_attempts[step_id[0]],
                status="running" if end is None else "failed" if failed else "ok",
                started_at=(start or end or winners[0]).event.timestamp,
                ended_at=None if end is None else end.event.timestamp,
                session_ids=_step_session_ids(step_id[0], step_id[1], sessions),
                reason=None if end is None else _text(end.event.payload.get("reason")),
            )
        )
    return tuple(sorted(steps, key=lambda step: (step.started_at, step.attempt, step.key)))


def _caps(winners: Sequence[StoredEvent]) -> RunCaps | None:
    for stored in winners:
        caps = stored.event.payload.get("caps")
        if isinstance(caps, dict):
            return RunCaps(
                budget_usd=_decimal(caps.get("budget")),
                max_turns=_int(caps.get("max_turns")),
                model=_text(caps.get("model")),
                tracker_transport=_text(caps.get("transport")),
            )
    return None


def _mode(winners: Sequence[StoredEvent]) -> Literal["live", "dry_run"] | None:
    for stored in winners:
        mode = stored.event.payload.get("mode")
        if mode == "live":
            return "live"
        if mode == "dry_run":
            return "dry_run"
    return None


def _latest_step_event(winners: Sequence[StoredEvent]) -> StoredEvent | None:
    steps = [stored for stored in winners if stored.event.type in _STEP_TYPES]
    return steps[-1] if steps else None


def _failure(winners: Sequence[StoredEvent], run_end: StoredEvent | None) -> RunFailure | None:
    latest = _latest_step_event(winners)
    failed_steps = [
        stored
        for stored in winners
        if stored.event.type == EventType.STEP_END
        and stored.event.payload.get("status") == "failed"
    ]
    if run_end is not None:
        if run_end.event.payload.get("status") != "failed":
            return None
    elif latest is None or latest not in failed_steps:
        return None
    failing = failed_steps[-1] if failed_steps else run_end
    if failing is None:
        return None
    key = _step_key(failing)
    stage = (
        _stage(None if run_end is None else run_end.event.payload.get("stage"))
        or _stage(failing.event.payload.get("stage"))
        or (STEP_STAGES[key] if key is not None else Stage.FAILED)
    )
    reason = _text(failing.event.payload.get("reason"))
    if run_end is not None:
        reason = _text(run_end.event.payload.get("reason")) or reason
    return RunFailure(stage=stage, reason=reason, failing_event_id=failing.event_id)


def _delivery(payload: Mapping[str, JsonValue], *, failure: RunFailure | None) -> RunDelivery:
    """The ``run.end``'s ``outcome``; for one stored before it (AGH-140), ``delivered`` when it
    names a PR and did not fail, else ``failed``."""
    outcome = payload.get("outcome")
    for known in _DELIVERIES:
        if outcome == known:
            return known
    return "delivered" if failure is None and _https_url(payload.get("pr_url")) else "failed"


def _current_stage(winners: Sequence[StoredEvent], run_end: StoredEvent | None) -> Stage:
    if run_end is not None:
        return Stage.REPORTED
    starts = [stored for stored in winners if stored.event.type == EventType.STEP_START]
    if not starts:
        return Stage.PICKED
    key = _step_key(starts[-1])
    return _stage(starts[-1].event.payload.get("stage")) or (
        STEP_STAGES[key] if key is not None else Stage.PICKED
    )


def _gate_results(winners: Sequence[StoredEvent]) -> tuple[RunGateResult, ...]:
    results = []
    for stored in winners:
        result = stored.event.payload.get("result")
        if stored.event.type != EventType.GATE_RESULT or result not in {"passed", "failed"}:
            continue
        results.append(
            RunGateResult(
                event_id=stored.event_id,
                result="passed" if result == "passed" else "failed",
                command=_text(stored.event.payload.get("command")),
                exit_code=_int(stored.event.payload.get("exit_code")),
                duration_ms=_int(stored.event.payload.get("duration_ms")),
            )
        )
    return tuple(results)


def fold_run(
    run_id: str, events: Iterable[StoredEvent], *, sessions: Sequence[Session] = ()
) -> WorkflowRun:
    """One run from its executor events (at least one) and the sessions it started."""
    ordered = canonical_events(events)
    winners = resolve_facts(ordered).winners
    run_ends = [stored for stored in winners if stored.event.type == EventType.RUN_END]
    run_end = run_ends[0] if run_ends else None
    failure = _failure(winners, run_end)
    payload_of_end = {} if run_end is None else run_end.event.payload
    delivery = None if run_end is None else _delivery(payload_of_end, failure=failure)
    issue = next((_text(item.event.payload.get("issue")) for item in ordered), None)
    linked = sorted((s for s in sessions if s.run_id == run_id), key=lambda s: s.started_at)
    cost, cost_source = run_cost(
        [session.cost_usd for session in linked if session.tokens is not None],
        executor_cost=_decimal(payload_of_end.get("cost_usd")),
    )
    first = ordered[0].event
    return WorkflowRun(
        id=run_id,
        project=first.project,
        repo=next((item.event.repo for item in ordered if item.event.repo), None),
        issue=None if issue is None else IssueRef(key=issue),
        workflow=next((item.event.workflow for item in ordered if item.event.workflow), None)
        or DEFAULT_WORKFLOW,
        stage=Stage.FAILED if failure is not None else _current_stage(winners, run_end),
        mode=_mode(winners),
        started_at=first.timestamp,
        ended_at=None if run_end is None else run_end.event.timestamp,
        last_activity_at=ordered[-1].event.timestamp,
        steps=_steps(winners, linked),
        failure=failure,
        caps=_caps(winners),
        cost_usd=cost,
        cost_source=cost_source,
        session_ids=tuple(session.id for session in linked),
        gate_results=_gate_results(winners),
        pr_url=_https_url(payload_of_end.get("pr_url")),
        delivery=delivery,
        delivery_reason=_text(payload_of_end.get("reason")) if delivery in _NOT_DELIVERED else None,
        sources_missing=RUN_SOURCES_MISSING,
    )


def fold_runs(
    events: Iterable[StoredEvent], *, sessions: Mapping[str, Session] | None = None
) -> dict[str, WorkflowRun]:
    """Every run in ``events``, by id; ``sessions`` lends costs and step sessions."""
    groups: dict[str, list[StoredEvent]] = {}
    for stored in canonical_events(events):
        run_id = run_id_of(stored)
        if run_id is not None:
            groups.setdefault(run_id, []).append(stored)
    known_sessions = list((sessions or {}).values())
    return {
        run_id: fold_run(run_id, group, sessions=known_sessions) for run_id, group in groups.items()
    }
