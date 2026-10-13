"""``/agent-sessions/{id}/stream``: one agent session's log and text deltas as Server-Sent
Events, resumed from ``Last-Event-ID`` (or ``?after=``) as ``<seq>`` or ``<seq>.<n>`` (E8).

The encoder (``agent_session_sse``) and the subscription arrive in later streams; until then
the route answers the contract's 501.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query

from agent_hub.api.dependencies import AgentSessionControlDep
from agent_hub.api.rfc9457 import NotImplementedInBuildError
from agent_hub.api.routes.streams import EventStreamResponse
from agent_hub.api.schemas import LastEventIdHeader

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"])

MAX_POSITION_CHARS = 32


def _stream_doc() -> dict[int | str, dict[str, Any]]:
    # Problems are JSON even on a stream route, so their media type is spelled out here.
    problem_json = {"application/json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}}
    events = "record.<kind>, delta, status, reset, heartbeat"
    return {
        200: {
            "description": f"Server-Sent Events: {events}",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        "4XX": {"description": "A client error, as an RFC 9457 problem", "content": problem_json},
        "5XX": {"description": "A server error, as an RFC 9457 problem", "content": problem_json},
    }


@router.get(
    "/{agent_session_id:uuid}/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc(),
)
async def stream_agent_session(
    agent_session_id: Annotated[UUID, Path()],
    control: AgentSessionControlDep,
    *,
    after: Annotated[str | None, Query(max_length=MAX_POSITION_CHARS)] = None,
    last_event_id: LastEventIdHeader = None,
) -> EventStreamResponse:
    """The session's records and deltas as they happen, after a replay from the position."""
    raise NotImplementedInBuildError("stream_agent_session")
