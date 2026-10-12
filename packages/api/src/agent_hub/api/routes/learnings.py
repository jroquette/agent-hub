"""``/learnings``: learnings with their inbox note, and the two decisions, each through a hub
pull request (ADR 0024)."""

from typing import Annotated

from fastapi import APIRouter, Path

from agent_hub.api.dependencies import LearningDecisionsDep, LearningReadsDep, parse_filter
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    LEARNING_ACTION_RESPONSES,
    MAX_QUERY_TEXT,
    PROBLEM_RESPONSES,
    AcceptLearningBody,
    CursorParam,
    LimitParam,
    ProjectParam,
    RejectLearningBody,
)
from agent_hub.core.learnings.learning import (
    Learning,
    LearningActionResult,
    LearningDetail,
    LearningStatus,
)
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.readmodels.page import Page

router = APIRouter(tags=["learnings"], responses=PROBLEM_RESPONSES)

LearningPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


@router.get("/learnings")
def list_learnings(
    reads: LearningReadsDep,
    *,
    project: ProjectParam = None,
    status: LearningStatus | None = None,
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[Learning]:
    """Learnings, newest first, each with its note's summary or why the note is unavailable."""
    learning_filter = parse_filter(
        LearningFilter, project=project, status=status, cursor=cursor, limit=limit
    )
    return reads.list_learnings(learning_filter)


@router.get("/learnings/{learning_id}")
def get_learning(learning_id: LearningPath, reads: LearningReadsDep) -> LearningDetail:
    """One learning with its note, the suggested target and the target choices."""
    return reads.get_learning(learning_id)


@router.post(
    "/learnings/{learning_id}/accept", status_code=201, responses=LEARNING_ACTION_RESPONSES
)
def accept_learning(
    learning_id: LearningPath, body: AcceptLearningBody, decisions: LearningDecisionsDep
) -> LearningActionResult:
    """Open a hub PR that moves the note into the brain; nothing changes until it is merged."""
    return decisions.accept(learning_id, target=body.target)


@router.post(
    "/learnings/{learning_id}/reject", status_code=201, responses=LEARNING_ACTION_RESPONSES
)
def reject_learning(
    learning_id: LearningPath, body: RejectLearningBody, decisions: LearningDecisionsDep
) -> LearningActionResult:
    """Open a hub PR that archives the note with the reason."""
    return decisions.reject(learning_id, reason=body.reason)
