"""``GET /doctor/findings``: the doctor findings of the registered hubs (Health)."""

from fastapi import APIRouter

from agent_hub.api.dependencies import HubReadModelsDep
from agent_hub.api.schemas import PROBLEM_RESPONSES, ProjectParam
from agent_hub.core.hubs.finding_view import FindingView
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["doctor"], responses=PROBLEM_RESPONSES)


@router.get("/doctor/findings")
def list_doctor_findings(
    models: HubReadModelsDep, *, project: ProjectParam = None
) -> Page[FindingView]:
    """Findings of every (or one) project, as ``hub doctor --json`` reports them."""
    return models.doctor_findings(Scope(project=project))
