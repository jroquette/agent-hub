"""``/scenario-runs``: a paused scenario run's investigation session (P-7, AM-2, AM-9).

``POST /scenario-runs/{run_id}/investigation`` starts the session once per investigation and
answers it again on a later call (``ScenarioInvestigations``); the chat goes through the
agent-session routes with the id it answers. A strict write that needs the launch cookie, like
the run commands (``RUN_WRITES``).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import ScenarioInvestigationsDep
from agent_hub.api.openapi_paths import AGENT_SESSIONS
from agent_hub.api.scenario_investigation import InvestigationSession
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.workflows.launch import RUN_ID_PATTERN

router = APIRouter(tags=["scenarios"], responses=PROBLEM_RESPONSES)

ScenarioRunIdPath = Annotated[str, Path(pattern=RUN_ID_PATTERN.pattern)]


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
