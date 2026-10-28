"""``/scenarios`` and ``/scenario-runs``: the hubs' scenarios, their plans and starts, a
scenario run's record, its investigation's session and answer, and its findings (AGH-350
P-6, P-7, AM-2, AM-5, AM-9, plan T12; docs/API.md § Scenarios).

The reads (list, detail, a run's record) need no cookie. Every POST is a strict write that
needs the launch cookie, like the run commands (``RUN_WRITES``), and answers 404 in the
container: a plan runs the scenario's scripts in plan mode, a start, an answer and an
investigation start processes, an issue reaches the tracker and a note writes into the hub.
``POST /scenario-runs/{run_id}/investigation`` starts the session once per investigation and
answers it again on a later call (``ScenarioInvestigations``); the chat goes through the
agent-session routes with the id it answers.

Debugging a scenario written as blocks (ADR 0049): ``PUT
/scenario-runs/{run_id}/breakpoints``, ``POST .../step`` and ``.../continue`` are run writes
like the others; ``GET .../values`` needs the launch cookie as the agent-session routes do (and
answers 404 in the container); ``POST /scenarios/{project}/{name}/migrate`` is an item write,
as the builder's save is.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import (
    ItemVersionWritesDep,
    ScenarioCommandsDep,
    ScenarioInvestigationsDep,
    ScenarioReadsDep,
)
from agent_hub.api.openapi_paths import AGENT_SESSIONS, API_PREFIX
from agent_hub.api.scenario_builder import (
    ActionLibrary,
    MigrateRequest,
    NewAction,
    ProposalView,
    SaveRequest,
    SaveResult,
    ScenarioBuilder,
    ScenarioMigration,
    ValidateRequest,
    ValidateResult,
    create_action,
    drop_proposal,
    read_proposal,
)
from agent_hub.api.scenario_catalog import (
    FINDING_ID_TEXT,
    Breakpoints,
    BreakpointsRequest,
    FindingIssue,
    FindingIssueRequest,
    FindingNote,
    InvestigationAnswer,
    InvestigationAnswered,
    ScenarioActionView,
    ScenarioCatalogView,
    ScenarioDetail,
    ScenarioPlanRequest,
    ScenarioPlanView,
    ScenarioRunDetail,
    ScenarioRunValues,
    ScenarioStartRequest,
)
from agent_hub.api.scenario_investigation import InvestigationSession
from agent_hub.api.schemas import MAX_QUERY_TEXT, PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.workflows.launch import RUN_ID_PATTERN, RunAccepted

router = APIRouter(tags=["scenarios"], responses=PROBLEM_RESPONSES)

ScenarioRunIdPath = Annotated[str, Path(pattern=RUN_ID_PATTERN.pattern)]
NamePath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]
FindingIdPath = Annotated[str, Path(pattern=FINDING_ID_TEXT)]


@router.get("/scenarios")
def list_scenarios(reads: ScenarioReadsDep, *, project: ProjectParam = None) -> ScenarioCatalogView:
    """The scenarios of every (or one) project, each with its last scenario run, and the
    files that do not load."""
    return reads.list_scenarios(Scope(project=project))


@router.get("/scenarios/{project}/{name}")
def get_scenario(project: NamePath, name: NamePath, reads: ScenarioReadsDep) -> ScenarioDetail:
    """One scenario: its steps and its scenario runs, newest first."""
    return reads.get_scenario(project, name)


@router.post("/projects/{project}/scenarios/validate")
def validate_scenario(
    project: NamePath, *, body: ValidateRequest, reads: ScenarioReadsDep
) -> ValidateResult:
    """The scenario builder's check: the document as the YAML Save would write, whether it
    loads, and each problem on its node. Writes nothing."""
    return ScenarioBuilder(reads).validate(project, body)


@router.get("/projects/{project}/actions")
def list_actions(project: NamePath, reads: ScenarioReadsDep) -> ActionLibrary:
    """The hub's actions (the builder's palette), with output fields and their scenarios."""
    return ScenarioBuilder(reads).library(project)


@router.put("/scenarios/{project}/{name}")
def save_scenario(
    project: NamePath,
    name: NamePath,
    *,
    body: SaveRequest,
    reads: ScenarioReadsDep,
    writes: ItemVersionWritesDep,
) -> SaveResult:
    """Write the scenario file from the builder's document (a strict write that needs the
    launch cookie): only a document that loads, over the file the builder last read
    (409 ``stale_document`` else), recorded as a version; no git command runs."""
    return ScenarioBuilder(reads).save(project, name, request=body, writes=writes)


@router.delete("/scenarios/{project}/{name}", status_code=204, response_class=Response)
def delete_scenario(project: NamePath, name: NamePath, reads: ScenarioReadsDep) -> None:
    """Remove the scenario's file (and Claude's proposal for it) from the hub folder (a strict
    write that needs the launch cookie); its recorded scenario runs stay; no git command runs."""
    ScenarioBuilder(reads).delete(project, name)


@router.get("/scenarios/{project}/{name}/proposal")
def get_proposal(project: NamePath, name: NamePath, reads: ScenarioReadsDep) -> ProposalView:
    """Claude's proposal for the scenario (a file in the hub's ignored ``.agent-runs/``),
    checked as Save would check it; 404 when there is none."""
    return read_proposal(ScenarioBuilder(reads), project, name)


@router.post("/scenarios/{project}/{name}/proposal/dismiss", status_code=204)
def delete_proposal(project: NamePath, name: NamePath, reads: ScenarioReadsDep) -> Response:
    """Removes Claude's proposal once the owner accepted it into the draft or rejected it."""
    drop_proposal(ScenarioBuilder(reads), project, name)
    return Response(status_code=204)


@router.post("/projects/{project}/actions", status_code=201)
def post_action(
    project: NamePath,
    *,
    body: NewAction,
    reads: ScenarioReadsDep,
    writes: ItemVersionWritesDep,
) -> ScenarioActionView:
    """Writes a new action (its document and its script) into the hub as a draft: a strict
    write that needs the launch cookie; it runs nothing and commits nothing."""
    return create_action(ScenarioBuilder(reads), project, body, writes=writes)


@router.put("/projects/{project}/actions/{pack}/{name}")
def put_action(
    project: NamePath,
    pack: NamePath,
    name: NamePath,
    *,
    body: NewAction,
    reads: ScenarioReadsDep,
    writes: ItemVersionWritesDep,
) -> ScenarioActionView:
    """Rewrites an action of the hub (its document and its script): a strict write; the
    action is a draft until it is committed again."""
    action = body.model_copy(update={"pack": pack, "name": name})
    return create_action(ScenarioBuilder(reads), project, action, writes=writes, replace=True)


@router.post("/scenarios/{project}/{name}/plan")
def plan_scenario(
    project: NamePath, name: NamePath, *, body: ScenarioPlanRequest, commands: ScenarioCommandsDep
) -> ScenarioPlanView:
    """What each step would do in the environment, and the policy's decision; nothing runs
    but the scripts' plan mode, with no credential and only when a step's args are known."""
    return commands.plan(project, name, body)


@router.post("/scenarios/{project}/{name}/runs", status_code=202)
def start_scenario(
    project: NamePath,
    name: NamePath,
    *,
    body: ScenarioStartRequest,
    commands: ScenarioCommandsDep,
    response: Response,
) -> RunAccepted:
    """Start a scenario run once its plan holds no problem and no deny (409 naming the denied
    steps, no run created); its events tell the rest."""
    accepted = commands.start(project, name, body)
    response.headers["Location"] = f"{API_PREFIX}/scenario-runs/{accepted.run_id}"
    return accepted


@router.post("/scenarios/{project}/{name}/migrate")
def migrate_scenario(
    project: NamePath,
    name: NamePath,
    *,
    body: MigrateRequest,
    reads: ScenarioReadsDep,
    writes: ItemVersionWritesDep,
) -> ScenarioMigration:
    """Write a graph scenario (version 1) again as blocks (version 2), or with ``check`` say
    what would be written; a node a tree cannot hold is a problem and nothing is written."""
    return ScenarioBuilder(reads).migrate(project, name, request=body, writes=writes)


@router.get("/scenario-runs/{run_id}")
def get_scenario_run(run_id: ScenarioRunIdPath, reads: ScenarioReadsDep) -> ScenarioRunDetail:
    """A scenario run as its record holds it: timeline, polls, captures, decisions, findings,
    investigations, the latest proposal's options, the workarounds and its debug pause."""
    return reads.get_run(run_id)


@router.get("/scenario-runs/{run_id}/values")
def get_scenario_run_values(
    run_id: ScenarioRunIdPath, reads: ScenarioReadsDep
) -> ScenarioRunValues:
    """A paused run's inputs and each finished block's inputs, status and output, from its
    record (needs the launch cookie; never on a production environment)."""
    return reads.run_values(run_id)


@router.put("/scenario-runs/{run_id}/breakpoints")
def put_breakpoints(
    run_id: ScenarioRunIdPath, *, body: BreakpointsRequest, commands: ScenarioCommandsDep
) -> Breakpoints:
    """Replace a run's breakpoints, blocks of its pinned tree (none clears them); a run that
    runs takes them at its next block. Refused on production, but for clearing them."""
    return commands.set_breakpoints(run_id, body)


@router.post("/scenario-runs/{run_id}/step", status_code=202)
def step_run(
    run_id: ScenarioRunIdPath, commands: ScenarioCommandsDep, response: Response
) -> RunAccepted:
    """Run the next block of a run in a debug pause, then pause before the one after it."""
    accepted = commands.debug(run_id, "step")
    response.headers["Location"] = f"{API_PREFIX}/scenario-runs/{run_id}"
    return accepted


@router.post("/scenario-runs/{run_id}/continue", status_code=202)
def continue_run(
    run_id: ScenarioRunIdPath, commands: ScenarioCommandsDep, response: Response
) -> RunAccepted:
    """Run a run in a debug pause to its next breakpoint, or its end."""
    accepted = commands.debug(run_id, "continue")
    response.headers["Location"] = f"{API_PREFIX}/scenario-runs/{run_id}"
    return accepted


@router.post(
    "/scenario-runs/{run_id}/investigation",
    status_code=201,
    responses={200: {"model": InvestigationSession, "description": "The session already started"}},
)
async def open_investigation(
    run_id: ScenarioRunIdPath, investigations: ScenarioInvestigationsDep, response: Response
) -> InvestigationSession:
    """Start the investigation session of a scenario run paused at an open investigation, or
    answer the one already started (200); 409 when the run is not paused there."""
    opened = await investigations.open(run_id)
    if opened.started:
        response.headers["Location"] = f"{AGENT_SESSIONS}/{opened.agent_session_id}"
    else:
        response.status_code = 200
    return opened


@router.post("/scenario-runs/{run_id}/answer", status_code=202)
def answer_investigation(
    run_id: ScenarioRunIdPath,
    *,
    body: InvestigationAnswer,
    commands: ScenarioCommandsDep,
    response: Response,
) -> InvestigationAnswered:
    """Answer the open investigation (pick an option, retry the step or stop the run), then
    resume the run; a pick that cannot stand is 409 with its reason and records nothing."""
    answered = commands.answer(run_id, body)
    response.headers["Location"] = f"{API_PREFIX}/scenario-runs/{run_id}"
    return answered


@router.post(
    "/scenario-runs/{run_id}/findings/{finding_id}/issue",
    responses={201: {"model": FindingIssue, "description": "The issue was created"}},
)
def finding_issue(
    run_id: ScenarioRunIdPath,
    finding_id: FindingIdPath,
    *,
    body: FindingIssueRequest,
    commands: ScenarioCommandsDep,
    response: Response,
) -> FindingIssue:
    """A finding's tracker issue draft; with ``confirm: true``, the issue created once (201)."""
    issue = commands.finding_issue(run_id, finding_id, body)
    if issue.created is not None:
        response.status_code = 201
    return issue


@router.post("/scenario-runs/{run_id}/findings/{finding_id}/inbox", status_code=201)
def finding_inbox(
    run_id: ScenarioRunIdPath, finding_id: FindingIdPath, commands: ScenarioCommandsDep
) -> FindingNote:
    """Write the finding as a ``brain/_inbox/`` note (``provenance: agent-from-external``),
    never over another."""
    return commands.finding_inbox(run_id, finding_id)
