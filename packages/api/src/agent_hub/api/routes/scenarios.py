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
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import (
    ScenarioCommandsDep,
    ScenarioInvestigationsDep,
    ScenarioReadsDep,
)
from agent_hub.api.openapi_paths import AGENT_SESSIONS, API_PREFIX
from agent_hub.api.scenario_catalog import (
    FINDING_ID_TEXT,
    FindingIssue,
    FindingIssueRequest,
    FindingNote,
    InvestigationAnswer,
    InvestigationAnswered,
    ScenarioCatalogView,
    ScenarioDetail,
    ScenarioPlanRequest,
    ScenarioPlanView,
    ScenarioRunDetail,
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


@router.get("/scenario-runs/{run_id}")
def get_scenario_run(run_id: ScenarioRunIdPath, reads: ScenarioReadsDep) -> ScenarioRunDetail:
    """A scenario run as its record holds it: timeline, polls, captures, decisions, findings,
    investigations, the latest proposal's options and the workarounds."""
    return reads.get_run(run_id)


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
