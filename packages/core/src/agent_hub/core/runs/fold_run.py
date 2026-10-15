"""The WorkflowRun read model, folded from ``hub run``'s executor events (D9, D16, AC-200.25).

Steps are keyed ``(step, attempt)``: a loop back into verify is verify attempt 2. The first
``run.end`` in source order decides how the run ended; a later one is a conflicting copy and
is ignored. Without a ``run.end``, a failed step with nothing after it means the run failed
there; otherwise the run is at the stage of its latest step. Pure and order-independent.

A workflow engine run (ADR 0032) is told apart by what only the engine writes: the pinned
``content_hash``, or a step's ``failure_kind`` or ``skip_cause``. Its steps keep every node id,
its ``run.end`` is the one with the highest ``n`` in ``<run>:run:<n>:end`` (one per resume),
none while a step comes after it (a resume not ended yet), and a ``run.end`` without a
delivery outcome is a failed delivery only when the run failed.
Its ``stage`` follows issue-to-pr's nodes; any other workflow's live run is ``PICKED``.
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, get_args
from urllib.parse import urlsplit

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.fact_keys import (
    canonical_events,
    engine_end_index,
    resolve_facts,
)
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.workflow_run import (
    IssueRef,
    RunCaps,
    RunDelivery,
    RunFailure,
    RunGateResult,
    RunStep,
    StepKey,
    StepKind,
    WorkflowRun,
    WorkflowRunStatus,
)
from agent_hub.core.sessions.session import Session
from agent_hub.core.sessions.session_cost import run_cost
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.ports import SkipCause

RUN_SESSION_PREFIX = "run:"
DEFAULT_WORKFLOW = "issue-to-pr"
STEP_STAGES: Mapping[StepKey, Stage] = {
    "pick": Stage.PICKED,
    "worktree": Stage.WORKTREE,
    "implement": Stage.IMPLEMENTING,
    "verify": Stage.VERIFYING,
    "pr": Stage.PR_OPEN,
}
# The node type of each issue-to-pr step (``pick`` is the parent's, not a node).
ISSUE_TO_PR_KINDS: Mapping[StepKey, StepKind] = {
    "worktree": "shell",
    "implement": "loop",
    "verify": "shell",
    "pr": "shell",
    "report": "shell",
}
RUN_SOURCES_MISSING = (EventSource.LINEAR, EventSource.GITHUB)
_ENGINE_KEYS: Final = ("content_hash", "failure_kind", "skip_cause")
_FAILURE_KINDS: Final[tuple[FailureKind, ...]] = get_args(FailureKind.__value__)
_SKIP_CAUSES: Final[tuple[SkipCause, ...]] = get_args(SkipCause.__value__)
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


def _known[T](value: object, known: tuple[T, ...]) -> T | None:
    return next((item for item in known if item == value), None)


def _is_engine_run(winners: Sequence[StoredEvent]) -> bool:
    return any(key in stored.event.payload for stored in winners for key in _ENGINE_KEYS)


def _step_key(stored: StoredEvent, *, engine: bool = False) -> StepKey | None:
    """The step's node id: any for an engine run, else one of ``hub run``'s steps."""
    key = stored.event.step or _text(stored.event.payload.get("step"))
    if engine:
        return key
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


def _steps(
    winners: Sequence[StoredEvent],
    sessions: Sequence[Session],
    *,
    engine: bool,
    kinds: Mapping[StepKey, StepKind],
) -> tuple[RunStep, ...]:
    starts: dict[tuple[StepKey, int], StoredEvent] = {}
    ends: dict[tuple[StepKey, int], StoredEvent] = {}
    for stored in winners:
        key = _step_key(stored, engine=engine)
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
        ended = {} if end is None else end.event.payload
        steps.append(
            RunStep(
                key=step_id[0],
                kind=kinds.get(step_id[0]),
                attempt=step_id[1],
                max_attempts=max_attempts[step_id[0]],
                status="running" if end is None else _step_status(ended.get("status")),
                started_at=(start or end or winners[0]).event.timestamp,
                ended_at=None if end is None else end.event.timestamp,
                session_ids=_step_session_ids(step_id[0], step_id[1], sessions),
                reason=_text(ended.get("reason")),
                failure_kind=_known(ended.get("failure_kind"), _FAILURE_KINDS),
                skip_cause=_known(ended.get("skip_cause"), _SKIP_CAUSES),
            )
        )
    return tuple(sorted(steps, key=lambda step: (step.started_at, step.attempt, step.key)))


def _step_status(value: object) -> Literal["ok", "failed", "skipped"]:
    return "failed" if value == "failed" else "skipped" if value == "skipped" else "ok"


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


def _failure(
    winners: Sequence[StoredEvent],
    run_end: StoredEvent | None,
    *,
    engine: bool,
    stages: Mapping[StepKey, Stage],
) -> RunFailure | None:
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
    key = _step_key(failing, engine=engine)
    stage = (
        _stage(None if run_end is None else run_end.event.payload.get("stage"))
        or _stage(failing.event.payload.get("stage"))
        or (stages.get(key, Stage.FAILED) if key is not None else Stage.FAILED)
    )
    reason = _text(failing.event.payload.get("reason"))
    if run_end is not None:
        reason = _text(run_end.event.payload.get("reason")) or reason
    return RunFailure(
        stage=stage,
        reason=reason,
        failing_event_id=failing.event_id,
        failure_kind=_known(failing.event.payload.get("failure_kind"), _FAILURE_KINDS),
    )


def _delivery(payload: Mapping[str, JsonValue], *, failure: RunFailure | None) -> RunDelivery:
    """The ``run.end``'s ``outcome``; for one stored before it (AGH-140), ``delivered`` when it
    names a PR and did not fail, else ``failed``."""
    outcome = payload.get("outcome")
    for known in _DELIVERIES:
        if outcome == known:
            return known
    return "delivered" if failure is None and _https_url(payload.get("pr_url")) else "failed"


def _engine_delivery(
    payload: Mapping[str, JsonValue], *, failure: RunFailure | None
) -> RunDelivery | None:
    """An engine run's delivery outcome (issue-to-pr's ``report``), else ``failed`` for a failed
    run and none for another: its outcome is not a delivery."""
    return _known(payload.get("outcome"), _DELIVERIES) or ("failed" if failure else None)


def _end_index(run_id: str, source_id: str) -> int:
    index = engine_end_index(run_id, source_id)
    return -1 if index is None else index


def _run_end(run_id: str, winners: Sequence[StoredEvent], *, engine: bool) -> StoredEvent | None:
    run_ends = [stored for stored in winners if stored.event.type == EventType.RUN_END]
    if not run_ends:
        return None
    if not engine:
        return run_ends[0]
    latest = max(run_ends, key=lambda stored: _end_index(run_id, stored.event.source_id))
    # A step after the latest end is a resume whose own end is not written yet.
    resumed = any(
        stored.event.type in _STEP_TYPES and stored.event.timestamp > latest.event.timestamp
        for stored in winners
    )
    return None if resumed else latest


def _status(run_end: StoredEvent | None, failure: RunFailure | None) -> WorkflowRunStatus:
    if failure is not None:
        return "failed"
    if run_end is None:
        return "running"
    return "cancelled" if run_end.event.payload.get("status") == "cancelled" else "done"


def _engine_stage(winners: Sequence[StoredEvent], stages: Mapping[StepKey, Stage]) -> Stage:
    """The stage of the latest step started that has one (issue-to-pr's nodes), else PICKED."""
    started = [
        _step_key(stored, engine=True)
        for stored in winners
        if stored.event.type == EventType.STEP_START
    ]
    known = [stages[key] for key in started if key is not None and key in stages]
    return known[-1] if known else Stage.PICKED


def _pinned(winners: Sequence[StoredEvent]) -> tuple[int | None, str | None]:
    """The revision and content hash an engine run pinned at start."""
    revisions = (_int(item.event.payload.get("revision")) for item in winners)
    hashes = (_text(item.event.payload.get("content_hash")) for item in winners)
    revision = next((value for value in revisions if value is not None), None)
    return revision, next((value for value in hashes if value is not None), None)


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
    workflow = next((item.event.workflow for item in ordered if item.event.workflow), None)
    workflow = workflow or DEFAULT_WORKFLOW
    engine = _is_engine_run(winners)
    issue_to_pr = workflow == DEFAULT_WORKFLOW
    stages = STEP_STAGES if issue_to_pr or not engine else {}
    run_end = _run_end(run_id, winners, engine=engine)
    failure = _failure(winners, run_end, engine=engine, stages=stages)
    payload_of_end = {} if run_end is None else run_end.event.payload
    delivery = None
    if run_end is not None:
        deliver = _engine_delivery if engine else _delivery
        delivery = deliver(payload_of_end, failure=failure)
    stage = _current_stage(winners, run_end)
    if engine and run_end is None:
        stage = _engine_stage(winners, stages)
    outcome = payload_of_end.get("outcome")
    revision, content_hash = _pinned(winners)
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
        workflow=workflow,
        stage=Stage.FAILED if failure is not None else stage,
        status=_status(run_end, failure),
        outcome=outcome if isinstance(outcome, bool | str) else None,
        revision=revision,
        content_hash=content_hash,
        mode=_mode(winners),
        started_at=first.timestamp,
        ended_at=None if run_end is None else run_end.event.timestamp,
        last_activity_at=ordered[-1].event.timestamp,
        steps=_steps(
            winners, linked, engine=engine, kinds=ISSUE_TO_PR_KINDS if issue_to_pr else {}
        ),
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
