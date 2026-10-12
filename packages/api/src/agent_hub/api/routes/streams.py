"""The Server-Sent Events streams: global, one session, live tiles, one run."""

from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.responses import StreamingResponse

from agent_hub.api.dependencies import StreamPorts, StreamPortsDep
from agent_hub.api.schemas import MAX_QUERY_TEXT, LastEventIdHeader, ProjectParam
from agent_hub.api.sse import StreamView, event_stream
from agent_hub.api.stream_views import (
    GlobalStreamView,
    LiveStreamView,
    RunStreamView,
    SessionStreamView,
)
from agent_hub.core.readmodels.filters import Scope

router = APIRouter(tags=["streams"])

IdPath = Annotated[str, Path(min_length=1, max_length=MAX_QUERY_TEXT)]


class EventStreamResponse(StreamingResponse):
    """A ``text/event-stream`` response."""

    media_type = "text/event-stream"


# A proxy or the browser must not buffer or keep a stream.
STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}


def _respond(
    view: StreamView, ports: StreamPorts, last_event_id: str | None
) -> EventStreamResponse:
    stream = event_stream(view, reader=ports.reader, feed=ports.feed, last_event_id=last_event_id)
    return EventStreamResponse(stream, headers=STREAM_HEADERS)


def _stream_doc(events: str) -> dict[int | str, dict[str, Any]]:
    # Problems are JSON even on a stream route, so their media type is spelled out here.
    problem_json = {"application/json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}}
    return {
        200: {
            "description": f"Server-Sent Events: {events}",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        "4XX": {"description": "A client error, as an RFC 9457 problem", "content": problem_json},
        "5XX": {"description": "A server error, as an RFC 9457 problem", "content": problem_json},
    }


@router.get(
    "/events/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc("heartbeat, counts, collector"),
)
def stream_events(
    ports: StreamPortsDep, *, project: ProjectParam = None, last_event_id: LastEventIdHeader = None
) -> EventStreamResponse:
    """The global stream."""
    view = GlobalStreamView(ports.models, ports.counters, Scope(project=project))
    return _respond(view, ports, last_event_id)


@router.get(
    "/sessions/{session_id}/events/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc("event, session, end, heartbeat"),
)
def stream_session_events(
    session_id: IdPath, ports: StreamPortsDep, *, last_event_id: LastEventIdHeader = None
) -> EventStreamResponse:
    """One session's events as they arrive."""
    return _respond(SessionStreamView(ports.models, session_id), ports, last_event_id)


@router.get(
    "/live-sessions/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc("tile.upsert, tile.remove, heartbeat"),
)
def stream_live_sessions(
    ports: StreamPortsDep, *, project: ProjectParam = None, last_event_id: LastEventIdHeader = None
) -> EventStreamResponse:
    """Live tiles as they change."""
    return _respond(LiveStreamView(ports.models, Scope(project=project)), ports, last_event_id)


@router.get(
    "/workflow-runs/{run_id}/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc("run, step, gate, heartbeat"),
)
def stream_run(
    run_id: IdPath, ports: StreamPortsDep, *, last_event_id: LastEventIdHeader = None
) -> EventStreamResponse:
    """One run's changes as they arrive."""
    return _respond(RunStreamView(ports.models, run_id), ports, last_event_id)
