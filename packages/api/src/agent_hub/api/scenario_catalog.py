"""The registered hubs' scenarios and their scenario runs as hub web shows and drives them
(AGH-350 plan T12, P-6, P-15, P-16, AM-5, AM-7, AM-8, AM-14; docs/API.md § Scenarios).

``ScenarioCatalog`` reads: each project hub's ``scenarios/`` through the generator's discovery
and core's ``check_workflows`` (an edited file shows on the next request), each scenario's
last runs from the folded events (``kind=scenario``, label ``scenario:<name>``), and a scenario
run's record (``<hub>/.agent-runs/workflows/<run>/records.jsonl``, never through a link, at most
8 MiB, a torn last line dropped) folded by core's ``run_record``: its timeline, polls,
captures, decisions, findings, investigations, workarounds, and the latest proposal's options,
each with its plan as shown, whether it needs acceptance (a draft action, with the commit line
that accepts it, AM-5) and whether it can be picked now (core's ``option_refusal``, the check
``hub workflow respond|decide`` makes).

``ScenarioCommands`` writes, each through the CLI as a child (the API never imports cli):

- ``plan`` waits for ``hub scenario plan --json`` (its plan-mode summaries, AM-8), after the
  inputs are checked against the scenario's;
- ``start`` plans in process (core's ``plan_scenario``) and refuses a plan with a problem or a
  ``deny`` (409 naming the denied steps), creating no run, then starts ``hub scenario run``;
- ``answer`` answers the open investigation: a ``pick`` is checked first (core's
  ``pick_problem``: a refused pick is 409 with its reason and records nothing), then, under the
  run commands' lock, ``hub workflow decide`` records it and the run resumes as an engine run
  does (``stop`` ends it ``cancelled``, ``retry`` runs the step again, ``pick`` runs the
  workaround first);
- ``finding_issue`` shows a finding's tracker issue draft (core's ``findings``, the CLI's text)
  and creates it only when the body confirms it (``confirm: true``, the terminal's ``y``), once:
  the marker ``finding-<id>.issue`` in the run folder (generator's ``finding_issues``, which
  ``hub scenario findings --issue`` claims too), made exclusively before the call, refuses a
  second create from either side,
  and a failed create is never retried here;
- ``finding_inbox`` writes the finding's ``brain/_inbox/`` note, never over another.
"""

import contextlib
import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Literal, Protocol, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    model_validator,
)

from agent_hub.api.agent_session_runtime import HubCredentials
from agent_hub.api.run_launcher import ScenarioLaunch
from agent_hub.api.scenario_investigation import (
    RECORDS,
    RUN_FOLDERS,
    SCENARIO_KIND,
    InvestigationRestrictions,
    linked_session,
    open_investigation,
    read_records,
)
from agent_hub.core.agent_sessions.errors import HubLocalInvalidError
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.effective_environments import EffectiveEnvironments
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.filters import MAX_PAGE_LIMIT, RunFilter, Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel
from agent_hub.core.runs.workflow_run import (
    RunEnvironment,
    WorkflowRun,
    WorkflowRunStatus,
    scenario_label,
)
from agent_hub.core.scenarios.access_policy import PolicyDecision, deny_reason
from agent_hub.core.scenarios.action_catalog import ActionEntry, ActionRefError, resolve_action
from agent_hub.core.scenarios.findings import (
    FindingIssueError,
    FindingsError,
    finding_of,
    inbox_note,
    issue_draft,
)
from agent_hub.core.scenarios.investigation import ProposedStep
from agent_hub.core.scenarios.run_record import (
    FindingView,
    InvestigationView,
    OptionView,
    ScenarioRunView,
    fold_records,
)
from agent_hub.core.scenarios.scenario_plan import ScenarioPlan, plan_scenario
from agent_hub.core.scenarios.workaround import (
    StepPlan,
    accept_command,
    option_refusal,
    pick_problem,
    plan_option,
    step_refusal,
)
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.core.workflows.catalog import check_workflows
from agent_hub.core.workflows.document import EnvironmentRef
from agent_hub.core.workflows.gate_decisions import ResumeAfterDecisionError
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.launch import (
    MAX_INPUTS,
    RUN_ID_PATTERN,
    InputName,
    InputValue,
    RunAccepted,
    RunConflictError,
    RunInputError,
    RunLaunchError,
    argv_text,
    launch_inputs,
    new_run_id,
)
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.workflow_reads import WorkflowInputView, WorkflowProblemView
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.finding_issues import HeldIssue, IssueMarked, claim_issue
from agent_hub.generator.scenario_discovery import DiscoveredScenarioSource

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

# A scenario's runs the detail lists, newest first.
RUN_PAGE: Final = 50
INBOX_FOLDER: Final = Path("brain", "_inbox")
FINDING_ID_TEXT: Final = r"^f[0-9]{1,6}$"
_NEW_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
# A scenario file loads only up to 256 KiB; an action's document or script is shown up to 64 KiB.
DOCUMENT_TEXT_BYTES: Final = 256 << 10
ACTION_TEXT_BYTES: Final = 64 << 10
# A run record's first line (its start record) is read up to this size for a run's facts.
HEADER_BYTES: Final = 64 << 10
ANSWERED: Final = "the investigation is answered; its options can no longer be picked"
LOCAL_UNREADABLE: Final = (
    "hub.local.json cannot be read or conflicts with hub.json, so the options cannot be planned now"
)
CONFIG_UNREADABLE: Final = "hub.json cannot be read, so the options cannot be planned now"

type ScenarioMode = Literal["interactive", "regression"]
type Choice = Literal["pick", "retry", "stop"]
type OptionId = Annotated[str, StringConstraints(strict=True, pattern=r"^o[0-9]{1,2}$")]
type Inputs = Annotated[dict[InputName, InputValue], Field(max_length=MAX_INPUTS)]


# Reads


class ScenarioRunRef(ViewModel):
    """A scenario run as the folded events show it, with the environment and mode its start
    record names (``None`` when the record cannot be read)."""

    run_id: str
    status: WorkflowRunStatus
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None
    environment: str | None = None
    mode: str | None = None


class ScenarioEnvironment(ViewModel):
    """An environment the project's hub declares, as the effective config reads now."""

    name: str
    access: str
    production: bool


class ScenarioSummary(ViewModel):
    """A scenario of a project's hub, its pack and its last scenario run."""

    project: str
    name: str
    pack: str
    description: str | None
    revision: int
    node_count: int
    inputs: tuple[WorkflowInputView, ...] = ()
    last_run: ScenarioRunRef | None = None


class StepRetryView(ViewModel):
    """A step's ``retry``: retries after the first attempt, the first delay (doubling each
    time) and which errors it retries."""

    max_attempts: int
    delay: str
    on_error: str


class ScenarioStepView(ViewModel):
    """A step in declaration order: its type, the action it calls (an action or expect step)
    and the steps it waits for, with the keys of its call as the document writes them (``with``
    values, ``capture`` refs, an expect's ``every``/``timeout``/``until_when``, ``retry``)."""

    id: str
    type: str
    action: str | None
    depends_on: tuple[str, ...]
    description: str | None = None
    with_: dict[str, JsonValue] = Field(default_factory=dict, alias="with")
    capture: dict[str, str] = Field(default_factory=dict)
    every: str | None = None
    timeout: str | None = None
    until_when: str | None = None
    retry: StepRetryView | None = None


class ActionInputSpec(ViewModel):
    """An action input as its document declares it."""

    name: str
    type: str
    required: bool
    default: JsonValue = None
    description: str | None = None


class ScenarioActionView(ViewModel):
    """An action the scenario's steps call (``ref`` as a step writes it), as the hub's files
    hold it now: its facts, whether it is committed (``draft`` else, with the line that
    accepts it), and the text of its document and script (each cut at ``ACTION_TEXT_BYTES``);
    ``problem`` says why it does not resolve, the other facts then empty."""

    ref: str
    name: str
    pack: str | None = None
    path: str | None = None
    description: str | None = None
    effect: str | None = None
    runtime: str | None = None
    script: str | None = None
    timeout: str | None = None
    inputs: tuple[ActionInputSpec, ...] = ()
    output_format: dict[str, JsonValue] = Field(default_factory=dict)
    draft: bool = False
    accept_command: str | None = None
    document_text: str | None = None
    script_text: str | None = None
    script_truncated: bool = False
    problem: str | None = None


class ScenarioDetail(ScenarioSummary):
    """A scenario's steps, its scenario runs, newest first, and the environments it can be
    planned in (empty when ``hub.local.json`` or ``hub.json`` cannot be read), with its file
    (hub-relative ``path`` and raw ``document_text``) and the actions its steps call."""

    steps: tuple[ScenarioStepView, ...]
    runs: tuple[ScenarioRunRef, ...]
    environments: tuple[ScenarioEnvironment, ...] = ()
    path: str | None = None
    document_text: str | None = None
    actions: tuple[ScenarioActionView, ...] = ()
    document: dict[str, JsonValue] | None = None
    content_hash: str | None = None


class ScenarioCatalogView(ViewModel):
    """The scenarios that load, by project then name, and every file that does not."""

    items: tuple[ScenarioSummary, ...]
    problems: tuple[WorkflowProblemView, ...]


class TimelineEntry(ViewModel):
    """A line of the run's timeline; an investigation read (``agent_action``) names its action
    and effect."""

    event: str
    node: str | None
    attempt: int | None
    status: str | None
    at: str | None
    action: str | None = None
    effect: str | None = None


class ActionCallEntry(ViewModel):
    """An action call's policy facts, from its record line: never its inputs or output."""

    node: str
    attempt: int | None
    poll: int | None
    action: str | None
    effect: str | None
    origin: str | None
    decision: str | None
    reason_kind: str | None
    content_hash: str | None
    approver: str | None
    status: str | None
    failure_kind: str | None
    at: str | None


class PollEntry(ViewModel):
    node: str
    attempt: int | None
    poll: int | None
    held: bool | None
    at: str | None


class CaptureEntry(ViewModel):
    node: str
    attempt: int | None
    name: str
    value: JsonValue


class DecisionEntry(ViewModel):
    node: str
    attempt: int | None
    choice: str | None
    text: str | None
    approver: str | None
    where: str | None
    at: str | None


class FindingEntry(ViewModel):
    finding_id: str
    step: str
    title: str
    text: str
    evidence: str


class InvestigationEntry(ViewModel):
    """An investigation; ``agent_session_id`` is the session its link file names, if any."""

    number: int
    step: str
    gate: str
    failure_kind: str | None
    choice: str | None
    text: str | None
    approver: str | None
    closed: bool
    agent_session_id: str | None = None


class OptionEntry(ViewModel):
    """An option of the latest proposal: its steps and their plan as shown, whether a step runs
    a draft action (``needs_acceptance``, with the commit lines that accept those still
    drafts), and whether it can be picked now, or why not."""

    option_id: str
    summary: str
    steps: tuple[dict[str, JsonValue], ...]
    plan: tuple[dict[str, JsonValue], ...]
    needs_acceptance: bool
    accept_commands: tuple[str, ...]
    pickable: bool
    refusal: str | None


class ProposalEntry(ViewModel):
    proposal: int
    investigation: int
    options: tuple[OptionEntry, ...]


class WorkaroundEntry(ViewModel):
    workaround_id: str
    number: int
    option: str
    steps: int
    approver: str | None
    status: str | None


class ScenarioRunDetail(ViewModel):
    """A scenario run as its record holds it. ``status`` is its end's, ``None`` while it has
    none; ``open_investigation`` is the number of the investigation waiting for an answer."""

    run_id: str
    project: str
    scenario: str | None
    pack: str | None
    environment: str | None
    mode: str | None
    status: str | None
    open_investigation: int | None
    paused_step: str | None
    timeline: tuple[TimelineEntry, ...]
    polls: tuple[PollEntry, ...]
    captures: tuple[CaptureEntry, ...]
    decisions: tuple[DecisionEntry, ...]
    findings: tuple[FindingEntry, ...]
    investigations: tuple[InvestigationEntry, ...]
    proposal: ProposalEntry | None
    workarounds: tuple[WorkaroundEntry, ...]
    actions: tuple[ActionCallEntry, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class ScenarioRun:
    """A scenario run's folder and record, as read now."""

    project: str
    hub: str
    folder: Path
    records: list[dict[str, JsonValue]]


@dataclass(frozen=True, kw_only=True, slots=True)
class _Planner:
    """Core's ``OptionPlanner`` over the hub's actions and environments as read now."""

    found: ActionDiscovery
    pack: str
    view: EffectiveEnvironments
    environment: str

    def option(self, steps: Sequence[ProposedStep]) -> tuple[StepPlan, ...]:
        return plan_option(
            steps,
            entries=self.found.actions,
            pack=self.pack,
            view=self.view,
            environment=self.environment,
        )

    def refusal(self, step: StepPlan) -> str:
        return step_refusal(step, view=self.view, environment=self.environment)


class ScenarioCatalog:
    """The scenario reads of hub web over the registered hubs (``credentials`` names them and
    reads their config) and the folded events (``runs``)."""

    def __init__(self, *, credentials: HubCredentials, runs: EventReadModels) -> None:
        self.credentials = credentials
        self._runs = runs
        self._restrictions = InvestigationRestrictions(credentials)

    def list_scenarios(self, scope: Scope) -> ScenarioCatalogView:
        """Every (or one) project's scenarios, each with its last scenario run, and problems."""
        items: list[ScenarioSummary] = []
        problems: list[WorkflowProblemView] = []
        for project, hub in self.credentials.project_hubs():
            if scope.project not in {None, project}:
                continue
            source = DiscoveredScenarioSource(Path(hub))
            catalog = check_workflows(source)
            last = self._last_runs(project, hub)
            for plan in catalog.plans:
                name = plan.document.name
                found = source.found[name]
                items.append(
                    _summary(project, plan, pack=found.pack, last=last.get(scenario_label(name)))
                )
            problems.extend(
                WorkflowProblemView(project=project, **problem._asdict())
                for problem in catalog.problems
            )
        return ScenarioCatalogView(items=tuple(items), problems=tuple(problems))

    def get_scenario(self, project: str, name: str) -> ScenarioDetail:
        """One scenario that loads, its steps and runs; ``EntityNotFoundError`` else."""
        hub, plan, pack, file = self._scenario_file(project, name)
        page = self._runs.list_runs(
            RunFilter(
                project=project, kind="scenario", workflow=scenario_label(name), limit=RUN_PAGE
            )
        )
        runs = tuple(_run_ref(run, hub) for run in page.items)
        summary = _summary(project, plan, pack=pack, last=runs[0] if runs else None)
        steps = tuple(_step_view(node) for node in plan.document.nodes)
        text = read_text_bounded(file, DOCUMENT_TEXT_BYTES)[0]
        refs = dict.fromkeys(step.action for step in steps if step.action is not None)
        found = discover_actions(Path(hub)) if refs else None
        return ScenarioDetail(
            **summary.model_dump(),
            steps=steps,
            runs=runs,
            environments=self._environments(hub, project),
            path=_hub_relative(file, hub),
            document_text=text,
            document=_document_of(text),
            content_hash=None if text is None else _hash_text(file),
            actions=tuple(action_view(ref, pack, found) for ref in refs if found is not None),
        )

    def _environments(self, hub: str, project: str) -> tuple[ScenarioEnvironment, ...]:
        """The environments to plan in, or none when the config cannot be read whole."""
        try:
            view = self.credentials.environments_of(hub, project)
        except HubLocalInvalidError, EntityNotFoundError:
            return ()
        return tuple(
            ScenarioEnvironment(name=item.name, access=item.access, production=item.production)
            for item in view.environments
        )

    def run_environment(self, project: str, run_id: str) -> RunEnvironment | None:
        """The environment a workflow run's own start record names (the best-effort banner,
        E-15), with its access and production flag as the effective config reads now (both
        ``None`` when it cannot be read or no longer declares it); None without one."""
        hub = next(
            (path for known, path in self.credentials.project_hubs() if known == project), None
        )
        header = None if hub is None else run_header(hub, run_id)
        name = None if header is None else header.get("environment")
        if not isinstance(name, str):
            return None
        try:
            view = self.credentials.environments_of(hub or "", project)
        except HubLocalInvalidError, EntityNotFoundError:
            return RunEnvironment(name=name, access=None, production=None)
        found = next((item for item in view.environments if item.name == name), None)
        if found is None:
            return RunEnvironment(name=name, access=None, production=None)
        return RunEnvironment(name=name, access=found.access, production=found.production)

    def hub_of(self, project: str) -> str:
        """The project's hub folder; ``EntityNotFoundError`` (``project``) else."""
        hub = next(
            (path for known, path in self.credentials.project_hubs() if known == project), None
        )
        if hub is None:
            raise EntityNotFoundError(entity="project", entity_id=project)
        return hub

    def scenario(self, project: str, name: str) -> tuple[str, WorkflowPlan, str]:
        """The project's hub, the scenario's plan and its pack; ``EntityNotFoundError`` when
        the project or a scenario of that name that loads is unknown."""
        hub, plan, pack, _ = self._scenario_file(project, name)
        return hub, plan, pack

    def _scenario_file(self, project: str, name: str) -> tuple[str, WorkflowPlan, str, Path]:
        """``scenario`` and the scenario's file."""
        hub = self.hub_of(project)
        source = DiscoveredScenarioSource(Path(hub), only=name)
        catalog = check_workflows(source)
        plan = next((item for item in catalog.plans if item.document.name == name), None)
        if plan is None:
            raise EntityNotFoundError(entity="scenario", entity_id=f"{project}/{name}")
        found = source.found[name]
        return hub, plan, found.pack, found.path

    def scenario_run(self, run_id: str) -> ScenarioRun:
        """Scenario run ``run_id``'s folder and record; ``EntityNotFoundError`` when no
        registered hub holds it or it is not a scenario run, ``RunRecordError`` when its record
        is too large or broken."""
        project, hub, folder = self._restrictions.run_folder(run_id)
        records = read_records(folder)
        if not records or records[0].get("kind") != SCENARIO_KIND:
            raise EntityNotFoundError(entity="scenario run", entity_id=run_id)
        return ScenarioRun(project=project, hub=hub, folder=folder, records=records)

    def planner(self, run: ScenarioRun) -> _Planner:
        """What the run's options are planned against now; ``HubLocalInvalidError`` when its
        hub's ``hub.local.json`` cannot be read."""
        header = run.records[0]
        view = self.credentials.environments_of(run.hub, run.project)
        return _Planner(
            found=discover_actions(Path(run.hub)),
            pack=str(header.get("pack")),
            view=view,
            environment=str(header.get("environment")),
        )

    def get_run(self, run_id: str) -> ScenarioRunDetail:
        """Scenario run ``run_id`` as its record holds it (see the module docstring)."""
        run = self.scenario_run(run_id)
        view = fold_records(run.records)
        pending = view.open_investigation
        waiting = pending if pending is not None and pending.choice is None else None
        return ScenarioRunDetail(
            run_id=run_id,
            project=run.project,
            scenario=view.scenario,
            pack=view.pack,
            environment=view.environment,
            mode=view.mode,
            status=view.status,
            open_investigation=None if waiting is None else waiting.number,
            paused_step=None if waiting is None else waiting.step,
            timeline=tuple(TimelineEntry.model_validate(_fields(item)) for item in view.timeline),
            polls=tuple(PollEntry.model_validate(_fields(item)) for item in view.polls),
            captures=tuple(CaptureEntry.model_validate(_fields(item)) for item in view.captures),
            decisions=tuple(DecisionEntry.model_validate(_fields(item)) for item in view.decisions),
            findings=tuple(FindingEntry.model_validate(_fields(item)) for item in view.findings),
            investigations=tuple(_investigation(item, run.folder) for item in view.investigations),
            proposal=self._proposal(run, view, waiting),
            workarounds=tuple(
                WorkaroundEntry.model_validate(_fields(item)) for item in view.workarounds
            ),
            actions=tuple(ActionCallEntry.model_validate(_fields(item)) for item in view.actions),
        )

    def _proposal(
        self, run: ScenarioRun, view: ScenarioRunView, waiting: InvestigationView | None
    ) -> ProposalEntry | None:
        last = view.investigations[-1] if view.investigations else None
        if last is None or last.proposal is None:
            return None
        planner: _Planner | None = None
        refusal: str | None = ANSWERED
        if waiting is not None and waiting.number == last.number:
            try:
                planner = self.planner(run)
            except HubLocalInvalidError:
                refusal = LOCAL_UNREADABLE
            except EntityNotFoundError:
                refusal = CONFIG_UNREADABLE
        # The actions are read only to judge a waiting investigation's options or to name the
        # commit line of a drafted step (no cache: E-14).
        found = None if planner is None else planner.found
        drafted = any(_drafted(option) for option in last.proposal.options)
        if found is None and drafted:
            found = discover_actions(Path(run.hub))
        options = tuple(
            _option(option, found, planner=planner, refusal=refusal)
            for option in last.proposal.options
        )
        return ProposalEntry(
            proposal=last.proposal.proposal, investigation=last.number, options=options
        )

    def _last_runs(self, project: str, hub: str) -> dict[str, ScenarioRunRef]:
        """The newest scenario run of each label, from one page of the project's scenario
        runs."""
        page = self._runs.list_runs(
            RunFilter(project=project, kind="scenario", limit=MAX_PAGE_LIMIT)
        )
        last: dict[str, ScenarioRunRef] = {}
        for run in page.items:
            if run.workflow not in last:
                last[run.workflow] = _run_ref(run, hub)
        return last


def _summary(
    project: str, plan: WorkflowPlan, *, pack: str, last: ScenarioRunRef | None
) -> ScenarioSummary:
    document = plan.document
    return ScenarioSummary(
        project=project,
        name=document.name,
        pack=pack,
        description=document.description,
        revision=document.revision,
        node_count=len(document.nodes),
        inputs=tuple(
            WorkflowInputView(
                name=name, type=item.type, required=item.required, description=item.description
            )
            for name, item in document.inputs.items()
        ),
        last_run=last,
    )


def _action_of(node: object) -> str | None:
    action = getattr(node, "action", None)
    return action if isinstance(action, str) else None


def _step_view(node: object) -> ScenarioStepView:
    """A step as the page reads it: the keys of an action or expect call as written."""
    retry = getattr(node, "retry", None)
    every, timeout, until = (getattr(node, key, None) for key in ("every", "timeout", "until_when"))
    return ScenarioStepView.model_validate(
        {
            "id": getattr(node, "id"),  # noqa: B009 -- every node has one; typed as object
            "type": getattr(node, "type"),  # noqa: B009
            "action": _action_of(node),
            "depends_on": tuple(getattr(node, "depends_on", ())),
            "description": getattr(node, "description", None),
            "with": dict(getattr(node, "with_", None) or {}),
            "capture": dict(getattr(node, "capture", None) or {}),
            "every": every if isinstance(every, str) else None,
            "timeout": timeout if isinstance(timeout, str) else None,
            "until_when": until if isinstance(until, str) else None,
            "retry": None
            if retry is None
            else StepRetryView(
                max_attempts=retry.max_attempts, delay=retry.delay, on_error=retry.on_error
            ),
        }
    )


def action_view(ref: str, pack: str, found: ActionDiscovery) -> ScenarioActionView:
    """The action ``ref`` (as a step of ``pack`` writes it), or why it does not resolve."""
    try:
        entry = resolve_action(found.actions, ref, pack=pack)
    except ActionRefError as error:
        return ScenarioActionView(ref=ref, name=ref.rsplit("/", 1)[-1], problem=str(error))
    document = entry.document
    files = dict(found.files.get(entry.document_path, ()))
    script, truncated = _text_of(files.get(entry.script_path), ACTION_TEXT_BYTES)
    return ScenarioActionView(
        ref=ref,
        name=document.name,
        pack=entry.pack,
        path=entry.document_path,
        description=document.description,
        effect=document.effect,
        runtime=document.runtime,
        script=entry.script_path,
        timeout=document.timeout,
        inputs=tuple(
            ActionInputSpec(
                name=name,
                type=item.type,
                required=item.required,
                default=item.default,
                description=item.description,
            )
            for name, item in document.inputs.items()
        ),
        output_format=dict(document.output_format),
        draft=entry.draft,
        accept_command=accept_command(_files_of(entry, found), entry.ref) if entry.draft else None,
        document_text=_text_of(files.get(entry.document_path), ACTION_TEXT_BYTES)[0],
        script_text=script,
        script_truncated=truncated,
    )


def _document_of(text: str | None) -> dict[str, JsonValue] | None:
    """The scenario file as the builder edits it: its mapping, keys as written."""
    if text is None:
        return None
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return value if isinstance(value, dict) else None


def _hash_text(path: Path) -> str | None:
    """``sha256:`` of the file's bytes, never through a link; None when unreadable."""
    try:
        descriptor = os.open(path, _READ_FILE)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        return f"sha256:{hashlib.sha256(file.read()).hexdigest()}"


def _hub_relative(path: Path, hub: str) -> str:
    try:
        return path.relative_to(hub).as_posix()
    except ValueError:
        return path.as_posix()


def _text_of(data: bytes | None, limit: int) -> tuple[str | None, bool]:
    """``data`` as text, cut at ``limit`` bytes (and whether it was); None without data."""
    if data is None:
        return None, False
    return data[:limit].decode(errors="replace"), len(data) > limit


def read_text_bounded(path: Path, limit: int) -> tuple[str | None, bool]:
    """A file's text read up to ``limit`` bytes, never through a link; None if unreadable."""
    try:
        descriptor = os.open(path, _READ_FILE)
    except OSError:
        return None, False
    with os.fdopen(descriptor, "rb") as file:
        data = file.read(limit + 1)
    return _text_of(data, limit)


def _run_ref(run: WorkflowRun, hub: str) -> ScenarioRunRef:
    header = run_header(hub, run.id) or {}
    environment, mode = header.get("environment"), header.get("mode")
    return ScenarioRunRef(
        run_id=run.id,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        environment=environment if isinstance(environment, str) else None,
        mode=mode if isinstance(mode, str) else None,
    )


def run_header(hub: str, run_id: str) -> Mapping[str, JsonValue] | None:
    """The start record (first line) of run ``run_id``'s record in ``hub``, never through a
    link and read up to ``HEADER_BYTES``; None when it cannot be read or is not one object."""
    folder = Path(hub) / RUN_FOLDERS / run_id
    if not RUN_ID_PATTERN.fullmatch(run_id) or folder.is_symlink():
        return None
    try:
        descriptor = os.open(folder / RECORDS, _READ_FILE)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        first = file.read(HEADER_BYTES).split(b"\n", 1)
    if len(first) < 2:  # noqa: PLR2004 -- the line and what follows its newline
        return None
    try:
        value = json.loads(first[0])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _fields(item: DataclassInstance) -> dict[str, object]:
    """A core view's fields (a dataclass), to build its API view."""
    return dataclasses.asdict(item)


def _investigation(item: InvestigationView, folder: Path) -> InvestigationEntry:
    return InvestigationEntry(
        number=item.number,
        step=item.step,
        gate=item.gate,
        failure_kind=item.failure_kind,
        choice=item.choice,
        text=item.text,
        approver=item.approver,
        closed=item.closed,
        agent_session_id=linked_session(folder, item.number),
    )


def _drafted(option: OptionView) -> list[Mapping[str, JsonValue]]:
    """The steps of ``option`` whose plan, as shown, runs a draft action."""
    return [step for step in option.plan if step.get("draft") is True]


def _option(
    option: OptionView,
    found: ActionDiscovery | None,
    *,
    planner: _Planner | None,
    refusal: str | None,
) -> OptionEntry:
    drafted = _drafted(option)
    if planner is not None:
        refusal = option_refusal(option, planner)
    return OptionEntry(
        option_id=option.option_id,
        summary=option.summary,
        steps=tuple(dict(step) for step in option.steps),
        plan=tuple(dict(step) for step in option.plan),
        needs_acceptance=bool(drafted),
        accept_commands=() if found is None else tuple(_accept_commands(drafted, found)),
        pickable=refusal is None,
        refusal=refusal,
    )


def _accept_commands(
    drafted: Iterable[Mapping[str, JsonValue]], found: ActionDiscovery
) -> Iterable[str]:
    """The commit line of each drafted step's action that is still a draft, once each."""
    seen: set[str] = set()
    for step in drafted:
        ref = str(step.get("action"))
        entry = next((item for item in found.actions if item.ref == ref), None)
        if entry is None or not entry.draft or ref in seen:
            continue
        seen.add(ref)
        yield accept_command(_files_of(entry, found), ref)


def _files_of(entry: ActionEntry, found: ActionDiscovery) -> list[str]:
    files = [path for path, _ in found.files.get(entry.document_path, ())]
    return files or [entry.document_path, entry.script_path]


# Writes


class ScenarioLauncher(Protocol):
    """What starts and drives scenario runs: ``ProcessRunLauncher``."""

    def start_scenario(self, spec: ScenarioLaunch) -> None: ...

    def plan_scenario(
        self, hub_path: str, name: str, *, environment: str, inputs: Mapping[str, str]
    ) -> tuple[int, bytes]: ...

    def decide(self, hub_path: str, run_id: str, *, gate_id: str, answer: GateAnswer) -> None: ...

    def resume(self, hub_path: str, run_id: str, *, issue: str | None) -> None: ...

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]: ...


class ScenarioPlanRequest(BaseModel):
    """The body of a plan: the environment and the inputs (``--input``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: EnvironmentRef
    inputs: Inputs = Field(default_factory=dict)


class ScenarioStartRequest(ScenarioPlanRequest):
    """The body of a start: a plan's, and the mode (``interactive`` by default)."""

    mode: ScenarioMode = "interactive"


class PlanEndpoint(ViewModel):
    service: str
    url: str | None
    resource: str | None


class ScenarioPlanRow(ViewModel):
    """One step of a plan, as ``hub scenario plan --json`` prints it, and whether its action
    needs acceptance (a draft), with the commit line that accepts it (AM-5)."""

    step: str
    type: str
    action: str
    effect: str
    args: dict[str, str]
    endpoints: dict[str, PlanEndpoint]
    every: str | None
    timeout: str | None
    content_hash: str
    draft: bool
    decision: str
    reason_kind: str | None
    reason: str | None
    plan: str
    needs_acceptance: bool
    accept_command: str | None


class ScenarioPlanView(ViewModel):
    """A scenario planned in one environment; ``denied`` when it may not start."""

    project: str
    scenario: str
    environment: str
    access: str | None
    production: bool
    denied: bool
    problems: tuple[str, ...]
    rows: tuple[ScenarioPlanRow, ...]


class _PrintedRow(BaseModel):
    """A row as the CLI prints it (its keys stable)."""

    step: str
    type: str
    action: str
    effect: str
    args: dict[str, str]
    endpoints: dict[str, PlanEndpoint]
    every: str | None
    timeout: str | None
    content_hash: str
    draft: bool
    decision: str
    reason_kind: str | None
    reason: str | None
    plan: str


class _PrintedPlan(BaseModel):
    scenario: str
    environment: str
    access: str | None
    production: bool
    denied: bool
    problems: tuple[str, ...]
    rows: tuple[_PrintedRow, ...]


class InvestigationAnswer(BaseModel):
    """The answer to an open investigation: ``pick`` with an option id, ``retry`` or ``stop``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice: Choice
    option: OptionId | None = None

    @model_validator(mode="after")
    def _option_with_pick(self) -> Self:
        if (self.choice == "pick") != (self.option is not None):
            msg = "a pick names its option, and only a pick does"
            raise ValueError(msg)
        return self


class InvestigationAnswered(ViewModel):
    """What an answer did: recorded for the investigation, and the run resumed."""

    run_id: str
    project: str
    investigation: int
    step: str
    choice: Choice
    option: str | None


class FindingIssueRequest(BaseModel):
    """``confirm: true`` creates the issue (the terminal's ``y``); without it, the draft."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirm: StrictBool = False


class CreatedIssue(ViewModel):
    id: str
    url: str


class FindingIssue(ViewModel):
    """A finding's tracker issue: its draft, the team it goes to, and the issue once created.
    ``recorded`` is whether the created issue reached its marker (``None`` before a create);
    when it did not, ``warning`` says so: the issue exists, do not create it again."""

    run_id: str
    finding_id: str
    team: str | None
    title: str
    description: str
    created: CreatedIssue | None
    recorded: bool | None = None
    warning: str | None = None


class FindingNote(ViewModel):
    """The inbox note written for a finding, hub-relative."""

    run_id: str
    finding_id: str
    path: str


type TrackerOf = Callable[[HubConfig, str], TrackerClient | None]


class ScenarioCommands:
    """The scenario writes of hub web (see the module docstring). ``lock`` is the run
    commands' (``RunGuard.lock``); ``tracker_of`` gives a hub's tracker client, None when it is
    not connected; ``today`` dates inbox notes."""

    def __init__(  # noqa: PLR0913 -- the commands' ports, all keyword-only
        self,
        *,
        catalog: ScenarioCatalog,
        launcher: ScenarioLauncher,
        lock: threading.Lock,
        tracker_of: TrackerOf,
        today: Callable[[], date],
        mint: Callable[[], str] = new_run_id,
    ) -> None:
        self._catalog = catalog
        self._launcher = launcher
        self._lock = lock
        self._tracker_of = tracker_of
        self._today = today
        self._mint = mint

    def plan(self, project: str, name: str, request: ScenarioPlanRequest) -> ScenarioPlanView:
        """The scenario planned in the asked environment, with its plan-mode summaries."""
        hub, plan, _pack = self._catalog.scenario(project, name)
        launch_inputs(plan, request.inputs)
        # As the CLI's plan, which exits on it: a local file that cannot be read or conflicts
        # with hub.json refuses before any child runs.
        self._catalog.credentials.environments_of(hub, project)
        texts = {key: argv_text(value) for key, value in request.inputs.items()}
        code, printed = self._launcher.plan_scenario(
            hub, name, environment=request.environment, inputs=texts
        )
        if code == 2:  # noqa: PLR2004 -- the CLI's usage exit
            raise RunInputError("the inputs do not fit the scenario's declared inputs")
        try:
            shown = _PrintedPlan.model_validate_json(printed)
        except ValidationError:
            raise RunLaunchError("hub scenario plan printed no plan") from None
        found = discover_actions(Path(hub)) if any(row.draft for row in shown.rows) else None
        rows = tuple(_plan_row(row, found) for row in shown.rows)
        return ScenarioPlanView(project=project, **shown.model_dump(exclude={"rows"}), rows=rows)

    def start(self, project: str, name: str, request: ScenarioStartRequest) -> RunAccepted:
        """Start a scenario run once its plan holds no problem and no ``deny``."""
        run_id = self._mint()
        hub, plan, pack = self._catalog.scenario(project, name)
        inputs = launch_inputs(plan, request.inputs)
        view = self._catalog.credentials.environments_of(hub, project)
        planned = plan_scenario(
            plan,
            pack=pack,
            actions=discover_actions(Path(hub)).actions,
            view=view,
            environment=request.environment,
            inputs=inputs,
        )
        if planned.denied:
            raise _refused_start(planned)
        spec = ScenarioLaunch(
            run_id=run_id,
            project=project,
            hub_path=hub,
            name=name,
            environment=request.environment,
            mode=request.mode,
            inputs=dict(request.inputs),
        )
        with self._lock:
            self._launcher.start_scenario(spec)
        return RunAccepted(run_id=run_id, project=project, action="start")

    def answer(self, run_id: str, request: InvestigationAnswer) -> InvestigationAnswered:
        """Record the answer to the run's open investigation, then resume the run."""
        with self._lock:
            run = self._catalog.scenario_run(run_id)
            pending = open_investigation(run.records, run_id)
            if run_id in self._launcher.live_runs(run.hub):
                reason = "the run's child is still running"
                raise RunConflictError(code="in_use", reason=reason, run_id=run_id)
            problem = pick_problem(
                run.records,
                node=pending.gate,
                attempt=pending.number,
                choice=request.choice,
                text=request.option,
                planner=lambda: self._catalog.planner(run),
            )
            if problem is not None:
                raise RunConflictError(code="pick_refused", reason=problem, run_id=run_id)
            gate_id = f"{run_id}:{pending.gate}:{pending.number}"
            answer = GateAnswer(request.choice, request.option)
            self._launcher.decide(run.hub, run_id, gate_id=gate_id, answer=answer)
            try:
                self._launcher.resume(run.hub, run_id, issue=None)
            except RunLaunchError as error:
                message = f"the decision is recorded, but the run did not resume: {error}"
                raise ResumeAfterDecisionError(message) from None
        return InvestigationAnswered(
            run_id=run_id,
            project=run.project,
            investigation=pending.number,
            step=pending.step,
            choice=request.choice,
            option=request.option,
        )

    def finding_issue(
        self, run_id: str, finding_id: str, request: FindingIssueRequest
    ) -> FindingIssue:
        """The finding's issue draft; with ``confirm``, the issue created once."""
        run = self._catalog.scenario_run(run_id)
        view = fold_records(run.records)
        finding = _finding(view, run_id, finding_id)
        try:
            draft = issue_draft(view, finding, record=_record(run_id))
        except FindingsError as error:
            raise RunConflictError(
                code="finding_unusable", reason=str(error), run_id=run_id
            ) from None
        # The draft needs only hub.json (its team); the create, the effective config.
        committed = self._catalog.credentials.config_of(run.hub)
        team = committed.tracker.team_keys[0] if committed is not None else None
        issue = FindingIssue(
            run_id=run_id,
            finding_id=finding_id,
            team=team,
            title=draft.title,
            description=draft.description,
            created=None,
        )
        if not request.confirm:
            return issue
        # As the CLI: hub.json with hub.local.json over it (a local tracker.transport wins);
        # a local file that cannot be read or conflicts with hub.json refuses (fail closed).
        config = self._catalog.credentials.effective_config_of(run.hub, run.project)
        team = config.tracker.team_keys[0]
        issue = issue.model_copy(update={"team": team})
        client = self._tracker_of(config, run.hub)
        if client is None:
            reason = (
                "the tracker is not connected: set LINEAR_API_KEY or connect Linear in"
                ' Settings, or set tracker.transport "mcp" in hub.json'
            )
            raise RunConflictError(code="tracker_not_connected", reason=reason, run_id=run_id)
        # The claim's lock is held across the create, so nothing retakes a running create.
        claim = _claim_issue(run.folder, run_id, finding_id)
        try:
            try:
                created = client.create_issue(team, draft.title, draft.description)
            except TrackerError:
                with contextlib.suppress(OSError):
                    claim.fail()
                msg = (
                    f"the tracker did not create the issue of finding {finding_id}; it may"
                    " exist: check the tracker"
                )
                raise FindingIssueError(msg) from None
            made = CreatedIssue(id=created.id, url=created.url)
            try:
                claim.record(issue_id=created.id, url=created.url)
            except OSError as error:
                warning = (
                    f"the issue {created.id} was created but could not be recorded:"
                    f" {error.strerror or error}; do not create it again"
                )
                return issue.model_copy(
                    update={"created": made, "recorded": False, "warning": warning}
                )
        finally:
            # Any other end leaves the marker unfinished and releases the claim.
            claim.release()
        return issue.model_copy(update={"created": made, "recorded": True})

    def finding_inbox(self, run_id: str, finding_id: str) -> FindingNote:
        """Write the finding's note in the hub's ``brain/_inbox/``, never over another."""
        run = self._catalog.scenario_run(run_id)
        view = fold_records(run.records)
        finding = _finding(view, run_id, finding_id)
        try:
            note = inbox_note(view, finding, record=_record(run_id), day=self._today())
        except FindingsError as error:
            raise RunConflictError(
                code="finding_unusable", reason=str(error), run_id=run_id
            ) from None
        shown = (INBOX_FOLDER / note.name).as_posix()
        folder = _inbox_folder(Path(run.hub), run_id)
        try:
            descriptor = os.open(folder / note.name, _NEW_FILE, 0o644)
        except FileExistsError:
            reason = f"{shown} already exists; nothing written"
            raise RunConflictError(code="note_exists", reason=reason, run_id=run_id) from None
        with os.fdopen(descriptor, "wb") as file:
            file.write(note.text.encode())
        return FindingNote(run_id=run_id, finding_id=finding_id, path=shown)


def _plan_row(row: _PrintedRow, found: ActionDiscovery | None) -> ScenarioPlanRow:
    command = None
    if row.draft and found is not None:
        entry = next((item for item in found.actions if item.ref == row.action), None)
        if entry is not None:
            command = accept_command(_files_of(entry, found), entry.ref)
    return ScenarioPlanRow(**row.model_dump(), needs_acceptance=row.draft, accept_command=command)


def _refused_start(planned: ScenarioPlan) -> RunConflictError:
    """409 naming each problem and each denied step (an undeclared environment once)."""
    lines = list(planned.problems)
    denied: list[str] = []
    for row in planned.rows:
        if row.decision == "deny" and row.reason_kind != "undeclared":
            reason = deny_reason(
                PolicyDecision(decision=row.decision, reason_kind=row.reason_kind),
                effect=row.effect,
                environment=planned.environment,
                access=planned.access,
            )
            lines.append(f"step {row.step}: deny ({reason})")
            denied.append(row.step)
    where = f"{planned.scenario} cannot start in {planned.environment}"
    reason = "; ".join([*lines, f"{where}; no scenario run was created"])
    if planned.access is None:
        code = "undeclared_environment"
    elif denied:
        code = "denied"
    else:
        code = "plan_problem"
    return RunConflictError(code=code, reason=reason, steps=tuple(denied))


def _finding(view: ScenarioRunView, run_id: str, finding_id: str) -> FindingView:
    found = finding_of(view, finding_id)
    if found is None:
        raise EntityNotFoundError(entity="finding", entity_id=f"{run_id}/{finding_id}")
    return found


def _record(run_id: str) -> str:
    """The run's record file, relative to the hub (the CLI's words)."""
    return (RUN_FOLDERS / run_id / RECORDS).as_posix()


def _claim_issue(folder: Path, run_id: str, finding_id: str) -> HeldIssue:
    """Claim the finding's issue (shared with ``hub scenario findings --issue``) and hold it;
    409 ``issue_exists`` when either side claimed it before or a create is running."""
    try:
        claimed = claim_issue(folder, finding_id)
    except OSError as error:
        raise RunLaunchError(f"cannot mark the finding's issue: {error.strerror}") from None
    if isinstance(claimed, IssueMarked):
        raise RunConflictError(code="issue_exists", reason=claimed.reason, run_id=run_id)
    return claimed


def _inbox_folder(hub: Path, run_id: str) -> Path:
    """``<hub>/brain/_inbox``, made when missing; 409 ``link_in_path`` when a part is a link."""
    folder = hub
    for part in INBOX_FOLDER.parts:
        folder = folder / part
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            reason = f"{INBOX_FOLDER.as_posix()} is not a folder of the hub"
            raise RunConflictError(code="link_in_path", reason=reason, run_id=run_id)
        try:
            folder.mkdir(exist_ok=True)
        except OSError as error:
            raise RunLaunchError(f"cannot make {INBOX_FOLDER}: {error.strerror}") from None
    return folder
