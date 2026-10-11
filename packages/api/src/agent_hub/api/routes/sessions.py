"""``/sessions``: the Sessions list and Session detail (timeline, files, cost, summary)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Path, Query

from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.schemas import (
    DEFAULT_LIMIT,
    MAX_QUERY_TEXT,
    MAX_TYPES,
    PROBLEM_RESPONSES,
    CursorParam,
    LimitParam,
    ProjectParam,
)
from agent_hub.core.events.event import EventType
from agent_hub.core.readmodels.filters import MAX_PAGE_LIMIT, SessionSort
from agent_hub.core.readmodels.page import Page
from agent_hub.core.sessions.session import (
    Outcome,
    Session,
    SessionCost,
    SessionFileChange,
    SessionStatus,
    SessionSummary,
    TimelineEvent,
)

router = APIRouter(tags=["sessions"], responses=PROBLEM_RESPONSES)

SessionPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]
TextParam = Annotated[str | None, Query(min_length=1, max_length=MAX_QUERY_TEXT)]
CostParam = Annotated[Decimal | None, Query(ge=0)]


@router.get("/sessions")
def list_sessions(  # noqa: PLR0913 -- one keyword per documented filter of the endpoint
    *,
    project: ProjectParam = None,
    repo: TextParam = None,
    agent: TextParam = None,
    status: SessionStatus | None = None,
    outcome: Outcome | None = None,
    workflow: TextParam = None,
    run_id: TextParam = None,
    started_from: Annotated[datetime | None, Query(alias="from")] = None,
    started_to: Annotated[datetime | None, Query(alias="to")] = None,
    cost_min: CostParam = None,
    cost_max: CostParam = None,
    file: TextParam = None,
    tool: TextParam = None,
    guard_denial: bool | None = None,
    sort: SessionSort = "-started_at",
    cursor: CursorParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
) -> Page[Session]:
    """Sessions matching the filters, one page."""
    raise NotImplementedInBuildError("list_sessions")


@router.get("/sessions/{session_id}")
def get_session(session_id: SessionPath) -> Session:
    """One session."""
    raise NotImplementedInBuildError("get_session")


@router.get("/sessions/{session_id}/summary")
def get_session_summary(session_id: SessionPath) -> SessionSummary:
    """The session's summary lines."""
    raise NotImplementedInBuildError("get_session_summary")


@router.get("/sessions/{session_id}/events")
def list_session_events(
    session_id: SessionPath,
    *,
    types: Annotated[list[EventType] | None, Query(max_length=MAX_TYPES)] = None,
    cursor: CursorParam = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = MAX_PAGE_LIMIT,
) -> Page[TimelineEvent]:
    """The session's events in timestamp order."""
    raise NotImplementedInBuildError("list_session_events")


@router.get("/sessions/{session_id}/files")
def list_session_files(session_id: SessionPath) -> Page[SessionFileChange]:
    """The paths the session touched."""
    raise NotImplementedInBuildError("list_session_files")


@router.get("/sessions/{session_id}/cost")
def get_session_cost(session_id: SessionPath) -> SessionCost:
    """The session's estimated cost."""
    raise NotImplementedInBuildError("get_session_cost")
