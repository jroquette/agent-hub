import asyncio

import pytest

from agent_hub.core.agent_sessions.driver import DriverHandle
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.live_session import LIVE_BUFFER, LiveSession, OpenRequest
from agent_hub.core.agent_sessions.records import StatusFrame
from agent_hub.core.agent_sessions.session_state import start_state
from agent_hub.core.testing.read_model_builders import (
    a_log_record,
    a_permission_request,
    an_agent_session,
    an_open_permission,
)

pytestmark = pytest.mark.anyio


def _live(**limits: int) -> LiveSession:
    return LiveSession(
        session=an_agent_session(last_seq=4),
        handle=DriverHandle("fake-1"),
        state=start_state(with_prompt=False),
        limits=SessionLimits(**limits),
    )


async def test_shows_oldest_open_request_and_last_seq_when_viewed() -> None:
    live = _live()
    live.requests["req-1"] = OpenRequest(request=a_permission_request(), view=an_open_permission())
    live.requests["req-2"] = OpenRequest(
        request=a_permission_request(request_id="req-2"),
        view=an_open_permission(request_id="req-2"),
    )
    live.last_seq = 9

    view = live.view()

    assert view.open_permission == an_open_permission()
    assert view.last_seq == 9


async def test_returns_frames_after_cursor_when_published() -> None:
    live = _live()
    subscriber = live.attach()

    await live.publish(a_log_record("text", 5))
    await live.publish(StatusFrame(status="idle"))
    frames = live.frames_after(subscriber.cursor)

    assert frames is not None
    assert [number for number, _ in frames] == [1, 2]
    assert live.frames_after(2) == []


async def test_returns_none_when_buffer_dropped_frames() -> None:
    live = _live()

    for seq in range(1, LIVE_BUFFER + 3):
        await live.publish(a_log_record("text", seq))

    assert live.frames_after(0) is None
    assert live.frames_after(2) is not None


async def test_detaches_oldest_when_subscriber_cap_reached() -> None:
    live = _live(subscribers=2)
    first, second = live.attach(), live.attach()

    third = live.attach()
    live.detach(second)

    assert (first.detached, second.detached, third.detached) == (True, True, False)


async def test_wakes_waiting_subscriber_when_frame_published_or_finished() -> None:
    live = _live()
    subscriber = live.attach()
    waiter = asyncio.create_task(live.wait_after(subscriber))
    await asyncio.sleep(0)

    await live.publish(StatusFrame(status="running"))
    async with asyncio.timeout(1):
        await waiter
    subscriber.cursor = 1
    finished = asyncio.create_task(live.wait_after(subscriber))
    await asyncio.sleep(0)
    await live.finish()
    async with asyncio.timeout(1):
        await finished

    assert live.finished
