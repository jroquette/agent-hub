"""Start, cancel, resume and abandon workflow runs from hub web (ADR 0032, decision 4).

``StartWorkflowRun`` mints the run id first, checks the inputs against the workflow's declared
``inputs`` (each one's type, then ``start_inputs``), refuses a second live run of one issue and
hands the run to a ``RunLauncher``, which starts ``hub workflow run --live`` as a child (a dry
run belongs to the CLI). A run's issue is its ``issue`` input when the workflow declares one and
it is a tracker key (``DEM-7``); a run is live while the read model folds it ``running`` or the
launcher still holds its child (a run just started has no event yet). A start and a resume share
one ``RunGuard``: its lock is held from the live check through the launch, so two launches of
one issue never race. ``issue-to-pr`` is refused: its tracker writes are its parent's and need
``LINEAR_API_KEY``, which no launched child gets. ``ControlWorkflowRun`` cancels, resumes and
abandons an engine run of a registered hub. Status is never tracked here: it comes from events.
"""

import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StringConstraints

from agent_hub.core.agent_sessions.agent_session import MAX_PROJECT_CHARS
from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.filters import MAX_PAGE_LIMIT, RunFilter
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.workflows.engine import WorkflowEngineError, start_inputs
from agent_hub.core.workflows.events import issue_key
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.substitution import echo
from agent_hub.core.workflows.workflow_reads import ProjectHubs

# The CLI's run ids: they name the run's folder and are its events' session.
RUN_ID_TEXT: Final = r"^[a-z0-9][a-z0-9-]{0,31}$"
RUN_ID_PATTERN: Final = re.compile(RUN_ID_TEXT)
ISSUE_INPUT: Final = "issue"
TRACKER_WORKFLOWS: Final = frozenset({"issue-to-pr"})
MAX_INPUTS: Final = 64
# One argv element each (Linux caps one at 128 KiB); no NUL, which argv cannot carry.
MAX_INPUT_CHARS: Final = 16_384
# All inputs together, as ``--input name=value`` argv text (UTF-8): far below any ARG_MAX.
MAX_INPUT_ARGV_BYTES: Final = 256 * 1024
MAX_WORKFLOW_CHARS: Final = 128
# The read model's pages read for an issue's live runs, newest first.
MAX_LIVE_PAGES: Final = 10

type InputText = Annotated[
    str, StringConstraints(max_length=MAX_INPUT_CHARS, pattern=r"^[^\x00]*$")
]
type InputNumber = Annotated[float, Field(allow_inf_nan=False)]
type InputValue = StrictBool | StrictInt | InputNumber | InputText
type InputName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
type RunAction = Literal["start", "cancel", "resume", "abandon"]


class StartRunRequest(BaseModel):
    """The body of ``POST /workflow-runs``: a project's workflow and its inputs (always live)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PROJECT_CHARS)]
    workflow: Annotated[str, StringConstraints(min_length=1, max_length=MAX_WORKFLOW_CHARS)]
    inputs: Annotated[dict[InputName, InputValue], Field(max_length=MAX_INPUTS)] = Field(
        default_factory=dict
    )


class RunAccepted(BaseModel):
    """What a run command did: the run, its project and the action taken."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    project: str
    action: RunAction


class RunInputError(AgentHubError):
    """Inputs that do not fit the workflow's ``inputs`` (answers 422); names an input only."""


class RunConflictError(AgentHubError):
    """A run command refused in the run's current state (answers 409); ``reason`` is shown."""

    def __init__(self, *, code: str, reason: str, run_id: str | None = None) -> None:
        self.code, self.reason, self.run_id = code, reason, run_id
        super().__init__(reason)


class RunLaunchError(AgentHubError):
    """The child could not be started or did not finish its command (answers 502)."""


class DecisionUnknownError(RunLaunchError):
    """A gate's decision child did not finish in time: it may have recorded the decision
    (answers 502; the gate or a resume tells)."""


@dataclass(frozen=True)
class LaunchSpec:
    """A live run to start: its id, hub folder, workflow, the inputs given and its issue."""

    run_id: str
    project: str
    hub_path: str
    workflow: str
    inputs: Mapping[str, JsonValue]
    issue: str | None


class RunLauncher(Protocol):
    """Starts and stops ``hub workflow run`` children of hub web."""

    def start(self, spec: LaunchSpec) -> None:
        """Start the run detached; ``RunLaunchError`` when it cannot start."""
        ...

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None:
        """Continue the run detached (``--resume``); ``issue`` goes to its pid file."""
        ...

    def abandon(self, hub_path: str, run_id: str) -> None:
        """End the run cancelled (``--abandon``), waiting for it; ``RunConflictError`` refused."""
        ...

    def decide(self, hub_path: str, run_id: str, *, gate_id: str, answer: GateAnswer) -> None:
        """Record ``answer`` to the run's open gate ``gate_id`` (``hub workflow decide``),
        waiting for it, without resuming; ``RunConflictError`` when the record refuses it."""
        ...

    def cancel(self, hub_path: str, run_id: str) -> bool:
        """Stop the run's child, then abandon it; False when no live child of ours runs it."""
        ...

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        """The runs whose launched child still runs, each with its issue."""
        ...


class WorkflowPlans(Protocol):
    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        """The project's hub folder and the workflow's plan; ``EntityNotFoundError`` else."""
        ...


def new_run_id() -> str:
    """A fresh run id, as the CLI mints one: 8 hex digits."""
    return uuid.uuid4().hex[:8]


def argv_text(value: JsonValue) -> str:
    """An input as ``--input`` takes it: ``true``/``false``, a number, or the text itself."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def launch_inputs(plan: WorkflowPlan, given: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """``given`` with the declared defaults filled in; ``RunInputError`` when an input is
    unknown, missing or of another type."""
    declared = plan.document.inputs
    size = sum(len(f"{name}={argv_text(value)}".encode()) for name, value in given.items())
    if size > MAX_INPUT_ARGV_BYTES:
        raise RunInputError(f"the inputs take more than {MAX_INPUT_ARGV_BYTES} bytes as arguments")
    for name, value in given.items():
        if name in declared and not declared[name].fits(value):
            raise RunInputError(f"the input {echo(name)} must be of type {declared[name].type}")
    try:
        return start_inputs(plan, given)
    except WorkflowEngineError as error:
        raise RunInputError(str(error)) from None


class RunGuard:
    """What every run command shares: one lock, held from the live check through the launch,
    so a start and a resume of one issue never race; the read model and the launcher."""

    def __init__(self, runs: EventReadModels, launcher: RunLauncher) -> None:
        self.runs, self.launcher = runs, launcher
        self.lock = threading.Lock()

    def refuse_live(
        self, project: str, hub_path: str, issue: str, *, besides: str | None = None
    ) -> None:
        """``RunConflictError`` (``live_run``) when a run of ``issue`` other than ``besides`` is
        live: held by the launcher, or folded ``running``. Call it holding ``lock``."""
        launched = self.launcher.live_runs(hub_path)
        live = next((run for run, of in launched.items() if of == issue and run != besides), None)
        live = live or self._folded_live(project, issue, besides)
        if live is not None:
            reason = f"the issue already has a live run ({live}); cancel or abandon it first"
            raise RunConflictError(code="live_run", reason=reason, run_id=live)

    def _folded_live(self, project: str, issue: str, besides: str | None) -> str | None:
        cursor: str | None = None
        for _ in range(MAX_LIVE_PAGES):
            page = self.runs.list_runs(
                RunFilter(project=project, issue=issue, cursor=cursor, limit=MAX_PAGE_LIMIT)
            )
            found = next(
                (run.id for run in page.items if run.status == "running" and run.id != besides),
                None,
            )
            if found is not None or page.next_cursor is None:
                return found
            cursor = page.next_cursor
        return None


class StartWorkflowRun:
    """``POST /workflow-runs``: always a live run (a dry run belongs to the CLI)."""

    def __init__(
        self, plans: WorkflowPlans, guard: RunGuard, *, mint: Callable[[], str] = new_run_id
    ) -> None:
        self._plans, self._guard, self._mint = plans, guard, mint

    def __call__(self, request: StartRunRequest) -> RunAccepted:
        run_id = self._mint()
        if request.workflow in TRACKER_WORKFLOWS:
            reason = f"{request.workflow} writes to the tracker; start it with hub run"
            raise RunConflictError(code="tracker_workflow", reason=reason)
        hub_path, plan = self._plans.workflow_plan(request.project, request.workflow)
        inputs = launch_inputs(plan, request.inputs)
        declared = ISSUE_INPUT in plan.document.inputs
        issue = issue_key(inputs.get(ISSUE_INPUT)) if declared else None
        spec = LaunchSpec(
            run_id=run_id,
            project=request.project,
            hub_path=hub_path,
            workflow=plan.document.name,
            inputs=dict(request.inputs),
            issue=issue,
        )
        with self._guard.lock:
            if issue is not None:
                self._guard.refuse_live(request.project, hub_path, issue)
            self._guard.launcher.start(spec)
        return RunAccepted(run_id=run_id, project=request.project, action="start")


class ControlWorkflowRun:
    """Cancel, resume and abandon an engine run (one with a pinned ``content_hash``)."""

    def __init__(self, hubs: ProjectHubs, guard: RunGuard) -> None:
        self._hubs, self._guard = hubs, guard
        self._runs, self._launcher = guard.runs, guard.launcher

    def cancel(self, run_id: str) -> RunAccepted:
        run, hub_path = self._target(run_id)
        if not self._launcher.cancel(hub_path, run_id):
            reason = "no live child started by hub web runs it; stop it where it runs"
            raise RunConflictError(code="not_running", reason=reason, run_id=run_id)
        return RunAccepted(run_id=run_id, project=run.project, action="cancel")

    def resume(self, run_id: str) -> RunAccepted:
        """Resume under the start's lock and its one-live-run-per-issue rule."""
        with self._guard.lock:
            run, hub_path = self._idle(run_id)
            ref = run.issue
            issue = None if ref is None else issue_key(ref.key)
            if issue is not None:
                self._guard.refuse_live(run.project, hub_path, issue, besides=run_id)
            self._launcher.resume(hub_path, run_id, issue=issue)
        return RunAccepted(run_id=run_id, project=run.project, action="resume")

    def abandon(self, run_id: str) -> RunAccepted:
        run, hub_path = self._idle(run_id)
        self._launcher.abandon(hub_path, run_id)
        return RunAccepted(run_id=run_id, project=run.project, action="abandon")

    def _idle(self, run_id: str) -> tuple[WorkflowRun, str]:
        run, hub_path = self._target(run_id)
        refuse_busy(run, hub_path, self._launcher)
        return run, hub_path

    def _target(self, run_id: str) -> tuple[WorkflowRun, str]:
        return engine_run_target(self._runs, self._hubs, run_id)


def engine_run_target(
    runs: EventReadModels, hubs: ProjectHubs, run_id: str
) -> tuple[WorkflowRun, str]:
    """The engine run (one with a pinned ``content_hash``) and its project's hub folder."""
    run = runs.get_run(run_id)
    if run.content_hash is None:
        reason = "the run is not a workflow engine run; use hub run for it"
        raise RunConflictError(code="not_engine_run", reason=reason, run_id=run_id)
    hub_path = next((path for name, path in hubs.project_hubs() if name == run.project), None)
    if hub_path is None:
        raise EntityNotFoundError(entity="project", entity_id=run.project)
    return run, hub_path


def refuse_busy(run: WorkflowRun, hub_path: str, launcher: RunLauncher) -> None:
    """``RunConflictError`` when the run ended done or cancelled, or its child still runs."""
    if run.status in {"done", "cancelled"}:
        reason = f"the run already ended {run.status}"
        raise RunConflictError(code="ended", reason=reason, run_id=run.id)
    if run.id in launcher.live_runs(hub_path):
        reason = "the run's child is still running; cancel it first"
        raise RunConflictError(code="in_use", reason=reason, run_id=run.id)
