"""``/approvals``: open and decided approvals (read-only in Phase 2)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import EventReadModelsDep, parse_filter
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


@router.get("/approvals/{approval_id}")
def get_approval(
    approval_id: Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)],
    models: EventReadModelsDep,
) -> Approval:
    """One approval."""
    return models.get_approval(approval_id)
