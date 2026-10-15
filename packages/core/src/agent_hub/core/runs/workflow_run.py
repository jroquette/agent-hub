"""The WorkflowRun read model: one ``hub run`` or workflow engine run, its steps, failure and caps.

A step is keyed by its node id as recorded (``a__b`` inside an include). ``kind`` is the node's
type, which events do not carry: it is known only for issue-to-pr's steps; the workflow's
document (``GET /workflows``) gives the others.
"""

from typing import Annotated, Literal

from pydantic import Field

from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import ApiTimestamp, DerivedView, Money, ViewModel
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.workflows.failures import FailureKind
from agent_hub.core.workflows.ports import RunStatus, SkipCause

type StepKey = Annotated[str, Field(min_length=1)]
type StepStatus = Literal["running", "ok", "failed", "skipped"]
type StepKind = Literal[
    "agent", "shell", "script", "loop", "loop_group", "approval", "wait", "halt"
]
type WorkflowRunStatus = Literal["running"] | RunStatus
# What an ended run delivered (AGH-140), apart from whether it failed (``failure``).
type RunDelivery = Literal["delivered", "no_changes", "blocked", "failed"]


class RunStep(ViewModel):
    """One step attempt, keyed ``(key, attempt)``; a loop back into verify is attempt 2."""

    key: StepKey
    kind: StepKind | None = None
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    status: StepStatus
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None
    session_ids: tuple[str, ...] = ()
    reason: str | None = None
    failure_kind: FailureKind | None = None
    skip_cause: SkipCause | None = None


class RunFailure(ViewModel):
    """Where and why a run failed, and the event to open ("Open failing moment")."""

    stage: Stage
    reason: str | None
    failing_event_id: EventId | None
    diagnosis_comment_url: str | None = None
    failure_kind: FailureKind | None = None


class RunCaps(ViewModel):
    """The limits a run started with."""

    budget_usd: Money | None
    max_turns: int | None
    model: str | None
    tracker_transport: str | None


class RunGateResult(ViewModel):
    """A gate the executor ran (``gate_ok`` or a failed check)."""

    event_id: EventId
    result: Literal["passed", "failed"]
    command: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None


class IssueRef(ViewModel):
    """The tracker issue a run works on; title and url need Linear (``null`` in Phase 2)."""

    key: str
    title: str | None = None
    url: str | None = None


class WorkflowRun(DerivedView):
    """A run folded from executor events (D9, D16): the first ``run.end`` wins, the highest
    ``n`` for an engine run. ``stage`` is issue-to-pr's machine (another workflow's live run is
    ``PICKED``); ``status`` and ``outcome`` hold for every workflow."""

    id: str
    project: str
    repo: str | None
    issue: IssueRef | None
    workflow: str
    stage: Stage
    status: WorkflowRunStatus = "running"
    outcome: bool | str | None = None
    revision: int | None = None
    content_hash: str | None = None
    mode: Literal["live", "dry_run"] | None
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None
    last_activity_at: ApiTimestamp
    steps: tuple[RunStep, ...]
    failure: RunFailure | None
    caps: RunCaps | None
    cost_usd: Money | None
    cost_source: Literal["sessions", "executor"] | None = None
    session_ids: tuple[str, ...] = ()
    gate_results: tuple[RunGateResult, ...] = ()
    pr_url: str | None = None
    delivery: RunDelivery | None = None
    delivery_reason: str | None = None
