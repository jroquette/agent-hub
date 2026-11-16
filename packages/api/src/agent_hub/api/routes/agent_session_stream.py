"""``/agent-sessions/{id}/stream``: one agent session's log and text deltas as Server-Sent
Events, resumed from ``Last-Event-ID`` (or ``?after=``) as ``<seq>`` or ``<seq>.<n>`` (E8).

The route awaits ``subscribe`` before it answers, so an unknown session (or any refusal of the
use case) is a problem, not a stream: no byte of the stream is sent before the subscription
exists. The stream then sends ``retry``, a ``reset`` when the position cannot be read (and
subscribes with no position: live frames only, the client reloads the snapshot and the log),
each item as ``agent_session_sse.frame`` encodes it, and a heartbeat carrying the last id sent
whenever nothing was sent for ``HEARTBEAT_SECONDS``. It ends when the subscription ends or the
client leaves, and closes the subscription either way.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query

from agent_hub.api.agent_session_sse import (
    MAX_POSITION_CHARS,
    RETRY,
    frame,
    heartbeat_frame,
    resume_position,
)
from agent_hub.api.dependencies import AgentSessionControlDep, SettingsDep
from agent_hub.api.routes.streams import STREAM_HEADERS, EventStreamResponse
from agent_hub.api.schemas import LastEventIdHeader
from agent_hub.api.sse import HEARTBEAT_SECONDS
from agent_hub.core.agent_sessions.records import ResetFrame, StreamItem, StreamPosition

router = APIRouter(prefix="/agent-sessions", tags=["agent-sessions"])


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


def _position_id(position: StreamPosition) -> str:
    return str(position.seq) if position.delta is None else f"{position.seq}.{position.delta}"


async def _close(items: AsyncIterator[StreamItem]) -> None:
    closer = getattr(items, "aclose", None)
    if closer is not None:
        await closer()


async def session_stream(
    items: AsyncIterator[StreamItem],
    *,
    reset: ResetFrame | None,
    last_id: str | None,
    now: Callable[[], datetime],
) -> AsyncIterator[bytes]:
    """The bytes of one agent-session stream (module docstring)."""
    pending: asyncio.Task[StreamItem] | None = None
    try:
        yield RETRY
        if reset is not None:
            yield frame(reset).encode()
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(items))
            done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
            if not done:
                yield heartbeat_frame(now(), last_id=last_id).encode()
                continue
            finished, pending = pending, None
            try:
                item = finished.result()
            except StopAsyncIteration:
                return
            message = frame(item)
            if message.id is not None:
                last_id = message.id
            yield message.encode()
    finally:
        if pending is not None:
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await pending
        await _close(items)


@router.get(
    "/{agent_session_id:uuid}/stream",
    response_class=EventStreamResponse,
    responses=_stream_doc(),
)
async def stream_agent_session(
    agent_session_id: Annotated[UUID, Path()],
    control: AgentSessionControlDep,
    settings: SettingsDep,
    *,
    after: Annotated[str | None, Query(max_length=MAX_POSITION_CHARS)] = None,
    last_event_id: LastEventIdHeader = None,
) -> EventStreamResponse:
    """The session's records and deltas as they happen, after a replay from the position."""
    start = resume_position(last_event_id, after=after)
    reset = start if isinstance(start, ResetFrame) else None
    position = None if isinstance(start, ResetFrame) else start
    # Awaited here, before the response starts: a refusal answers its problem (E8, P11).
    items = await control.subscribe(str(agent_session_id), position)
    explicit = last_event_id is not None or after is not None
    last_id = _position_id(position) if position is not None and explicit else None
    stream = session_stream(items, reset=reset, last_id=last_id, now=settings.clock)
    return EventStreamResponse(stream, headers=STREAM_HEADERS)
