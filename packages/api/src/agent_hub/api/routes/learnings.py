"""``/learnings``: learnings and their status (decisions arrive in Phase 3)."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    MAX_QUERY_TEXT,
    PROBLEM_RESPONSES,
    CursorParam,
    LimitParam,
    ProjectParam,
)
from agent_hub.core.learnings.learning import Learning, LearningStatus
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["learnings"], responses=PROBLEM_RESPONSES)


@router.get("/learnings")
def list_learnings(
    *,
    project: ProjectParam = None,
    status: LearningStatus | None = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[Learning]:
    """Learnings, newest first."""
    raise NotImplementedInBuildError("list_learnings")


@router.get("/learnings/{learning_id}")
def get_learning(
    learning_id: Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)],
) -> Learning:
    """One learning."""
    raise NotImplementedInBuildError("get_learning")
