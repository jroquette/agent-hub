"""What a list read may filter on; the API turns query parameters into these (400 when invalid)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.events.event import UtcTimestamp
from agent_hub.core.learnings.learning import LearningStatus
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.sessions.session import Outcome, SessionStatus
from agent_hub.core.workflows.failures import FailureKind

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
# A session's events are read whole by its detail page: larger pages mean fewer round trips.
MAX_EVENTS_PAGE_LIMIT = 1_000

type SessionSort = Literal[
    "started_at", "-started_at", "last_activity_at", "-last_activity_at", "cost", "-cost"
]


class Scope(BaseModel):
    """The project a read is limited to; None reads every registered project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str | None = None


class PageRequest(Scope):
    """A scoped read of one page: the cursor the previous page returned, and a page size."""

    cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)


class EventPageRequest(PageRequest):
    """A page of one session's events: up to ``MAX_EVENTS_PAGE_LIMIT`` of them."""

    limit: int = Field(default=MAX_PAGE_LIMIT, ge=1, le=MAX_EVENTS_PAGE_LIMIT)


class SessionFilter(PageRequest):
    """Filters of ``GET /sessions``."""

    repo: str | None = None
    agent: str | None = None
    status: SessionStatus | None = None
    outcome: Outcome | None = None
    workflow: str | None = None
    run_id: str | None = None
    issue: str | None = None
    started_from: UtcTimestamp | None = None
    started_to: UtcTimestamp | None = None
    cost_min: Decimal | None = Field(default=None, ge=0)
    cost_max: Decimal | None = Field(default=None, ge=0)
    file: str | None = None
    tool: str | None = None
    guard_denial: bool | None = None
    sort: SessionSort = "-started_at"

    @model_validator(mode="after")
    def _ranges_in_order(self) -> Self:
        if _above(self.cost_min, self.cost_max):
            msg = "cost_min must not be above cost_max"
            raise ValueError(msg)
        if _above(self.started_from, self.started_to):
            msg = "started_from must not be after started_to"
            raise ValueError(msg)
        return self


def _above[T: (Decimal, datetime)](low: T | None, high: T | None) -> bool:
    return low is not None and high is not None and low > high


class RunFilter(PageRequest):
    """Filters of ``GET /workflow-runs``."""

    repo: str | None = None
    stage: Stage | None = None
    outcome: Literal["done", "failed"] | None = None
    failure_stage: Stage | None = None
    mode: Literal["live", "dry_run"] | None = None
    issue: str | None = None
    workflow: str | None = None
    failure_kind: FailureKind | None = None


class ApprovalFilter(PageRequest):
    """Filters of ``GET /approvals``: open ones by default."""

    kind: ApprovalKind | None = None
    status: Literal["open", "decided", "all"] = "open"


class LearningFilter(PageRequest):
    """Filters of ``GET /learnings``."""

    status: LearningStatus | None = None
