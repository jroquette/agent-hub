"""``/approvals``: open and decided approvals, and a workflow gate's decision (AC-213.18).

``GET /approvals/{id}/gate`` shows what answers an open workflow gate; ``POST
/approvals/{id}/decision`` is a strict write that needs the launch's cookie (checked before
routing): one call to core's ``DecideWorkflowGate``, which records the answer through the CLI
and resumes the run.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Response

from agent_hub.api.dependencies import (
    EventReadModelsDep,
    GateDecisionsDep,
    WorkflowGatesDep,
    parse_filter,
)
from agent_hub.api.openapi_paths import API_PREFIX
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    MAX_QUERY_TEXT,
    PROBLEM_RESPONSES,
    CursorParam,
    LimitParam,
    ProjectParam,
)
from agent_hub.core.approvals.approval import Approval, ApprovalKind
from agent_hub.core.readmodels.filters import ApprovalFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.workflows.gate_decisions import (
    GateDecided,
    GateDecisionRequest,
    WorkflowGate,
)

router = APIRouter(tags=["approvals"], responses=PROBLEM_RESPONSES)


@router.get("/approvals")
def list_approvals(
    models: EventReadModelsDep,
    *,
    project: ProjectParam = None,
    kind: ApprovalKind | None = None,
    status: Literal["open", "decided", "all"] = "open",
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[Approval]:
    """Approvals, oldest first."""
    approval_filter = parse_filter(
        ApprovalFilter, project=project, kind=kind, status=status, cursor=cursor, limit=limit
    )
    return models.list_approvals(approval_filter)


ApprovalIdPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: ApprovalIdPath, models: EventReadModelsDep) -> Approval:
    """One approval."""
    return models.get_approval(approval_id)


@router.get("/approvals/{approval_id}/gate")
def get_gate(approval_id: ApprovalIdPath, gates: WorkflowGatesDep) -> WorkflowGate:
    """What answers an open workflow gate: its decisions or options and whether it takes text."""
    return gates.gate(approval_id)


@router.post("/approvals/{approval_id}/decision", status_code=202)
def decide_gate(
    approval_id: ApprovalIdPath,
    *,
    body: GateDecisionRequest,
    decisions: GateDecisionsDep,
    response: Response,
) -> GateDecided:
    """Record a person's answer to an open workflow gate, then resume its run; its events tell
    the rest."""
    decided = decisions(approval_id, body)
    response.headers["Location"] = f"{API_PREFIX}/approvals/{approval_id}"
    return decided
