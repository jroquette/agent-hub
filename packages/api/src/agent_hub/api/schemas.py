"""The API's own request and response bodies, its shared parameters and problem responses.

Read models come from core; only what exists for HTTP alone is declared here.
"""

from typing import Annotated, Any

from fastapi import Header, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.readmodels.filters import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from agent_hub.core.readmodels.page import MAX_CURSOR_CHARS

MAX_QUERY_TEXT = 200
MAX_TYPES = 20


class ProblemDetails(BaseModel):
    """An RFC 9457 problem; extension members (``errors``) are allowed."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class HookAccepted(BaseModel):
    """``POST /events/hooks``: how many events the envelope added and how many were known."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    appended: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class HubCreate(BaseModel):
    """``POST /hubs``: the absolute path of a hub to register."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


# Every operation may answer a problem; listing the ranges keeps FastAPI's validation schema out.
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ProblemDetails, "description": "A client error, as an RFC 9457 problem"},
    "5XX": {"model": ProblemDetails, "description": "A server error, as an RFC 9457 problem"},
}

ProjectParam = Annotated[str | None, Query(min_length=1, max_length=MAX_QUERY_TEXT)]
CursorParam = Annotated[str | None, Query(max_length=MAX_CURSOR_CHARS)]
LimitParam = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
LastEventIdHeader = Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)]

DEFAULT_LIMIT = DEFAULT_PAGE_LIMIT
