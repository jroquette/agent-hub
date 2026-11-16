import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from agent_hub.core.agent_sessions.driver import (
    Allow,
    DriverError,
    DriverEvent,
    DriverImage,
    Exited,
    InitEvent,
    PastSession,
    StartSpec,
    TextBlock,
    TextDelta,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import (
    PermissionAnsweredError,
    SessionTerminalError,
    UnknownPermissionError,
)
from agent_hub.core.testing.builders import a_png_bytes
from agent_hub.core.testing.read_model_builders import a_permission_request
from agent_hub.core.testing.session_driver_fakes import (
    DEFAULT_RESULT,
    Hold,
    InMemorySessionDriver,
)

pytestmark = pytest.mark.anyio
SPEC = StartSpec(cwd="/hubs/demo-hub", mode="default", model="sonnet")
BOUND = 5.0


async def _until_result(events: AsyncIterator[DriverEvent]) -> list[DriverEvent]:
    seen: list[DriverEvent] = []
    async with asyncio.timeout(BOUND):
        async for event in events:
            seen.append(event)
            if isinstance(event, TurnResult | Exited):
                return seen
    return seen


async def test_plays_reply_scripted_for_text_when_message_matches() -> None:
    driver = InMemorySessionDriver(
        replies={"hello": (TextDelta(block=0, index=0, text="Hi"), TextBlock(block=0, text="Hi"))}
    )
    handle = await driver.start(SPEC)
    await driver.send(handle, "hello")

    seen = await _until_result(driver.events(handle))

    assert [event.kind for event in seen] == ["init", "text.delta", "text", "result"]
    assert seen[0] == InitEvent(session_id=seen[0].session_id, model="sonnet")  # type: ignore[union-attr]
    assert seen[-1] == DEFAULT_RESULT


async def test_plays_turns_in_order_when_no_reply_matches() -> None:
    driver = InMemorySessionDriver(
        turns=[(TextBlock(block=0, text="first"),), (TextBlock(block=0, text="second"),)]
    )
    handle = await driver.start(SPEC)
    await driver.send(handle, "a")
    await driver.send(handle, "b")
    events = driver.events(handle)

    first = await _until_result(events)
    second = await _until_result(events)

    assert [e.text for e in first if isinstance(e, TextBlock)] == ["first"]
    assert [e.text for e in second if isinstance(e, TextBlock)] == ["second"]
    assert [e.kind for e in second][0] == "text"


async def test_keeps_given_session_id_when_spec_names_one() -> None:
    driver = InMemorySessionDriver()
    session_id = "5091b986-0000-4000-8000-00000000000a"
    handle = await driver.start(SPEC.model_copy(update={"session_id": session_id}))
    await driver.send(handle, "x")

    [init, *_] = await _until_result(driver.events(handle))

    assert init == InitEvent(session_id=session_id, model="sonnet")


async def test_ends_with_error_and_code_when_failed() -> None:
    driver = InMemorySessionDriver()
    handle = await driver.start(SPEC)

    driver.fail_with(handle, 2, "claude exited with code 2")
    seen = await _until_result(driver.events(handle))

    assert seen == [DriverError(message="claude exited with code 2"), Exited(code=2)]
    with pytest.raises(SessionTerminalError):
        await driver.send(handle, "again")


async def test_waits_on_hold_until_released_when_hold_scripted() -> None:
    driver = InMemorySessionDriver(replies={"slow": (Hold(), TextBlock(block=0, text="done"))})
    handle = await driver.start(SPEC)
    await driver.send(handle, "slow")
    events = driver.events(handle)
    assert isinstance(await anext(events), InitEvent)
    waiting = asyncio.ensure_future(anext(events))
    await asyncio.sleep(0.05)
    assert not waiting.done()

    driver.release(handle)

    assert await asyncio.wait_for(waiting, BOUND) == TextBlock(block=0, text="done")


async def test_refuses_answer_when_unknown_or_given_twice() -> None:
    request = a_permission_request()
    driver = InMemorySessionDriver(replies={"ask": (request,)})
    handle = await driver.start(SPEC)
    await driver.send(handle, "ask")
    events = driver.events(handle)
    await anext(events)
    assert await anext(events) == request

    with pytest.raises(UnknownPermissionError):
        await driver.answer_permission(handle, "req-other", Allow())
    await driver.answer_permission(handle, request.request_id, Allow())
    with pytest.raises(PermissionAnsweredError):
        await driver.answer_permission(handle, request.request_id, Allow())

    assert driver.answers == {request.request_id: Allow()}
    assert (await _until_result(events))[-1] == DEFAULT_RESULT


async def test_logs_every_command_when_called() -> None:
    past = PastSession(
        session_id="5091b986-0000-4000-8000-0000000000aa",
        title="Earlier work",
        last_activity=datetime(2026, 10, 9, 14, 0, tzinfo=UTC),
        cwd="/hubs/demo-hub",
    )
    driver = InMemorySessionDriver(past_sessions=[past])
    handle = await driver.start(SPEC)

    await driver.set_mode(handle, "plan")
    await driver.set_model(handle, "opus")
    await driver.interrupt(handle)
    resumable = await driver.list_resumable("/hubs/demo-hub")
    other = await driver.list_resumable("/hubs/other")
    capabilities = await driver.capabilities()
    await driver.close(handle)
    await driver.close(handle)

    assert [call.method for call in driver.calls] == [
        "start",
        "set_mode",
        "set_model",
        "interrupt",
        "list_resumable",
        "list_resumable",
        "capabilities",
        "close",
        "close",
    ]
    assert driver.calls[1].args == ("plan",)
    assert (resumable, other) == ((past,), ())
    assert capabilities.available


async def test_records_images_when_message_sent_with_image() -> None:
    driver = InMemorySessionDriver()
    handle = await driver.start(SPEC)
    image = DriverImage(media_type="image/png", data=a_png_bytes())

    await driver.send(handle, "What is on this screen?", images=(image,))
    await driver.send(handle, "And now?")
    await driver.close(handle)

    sends = [call.args for call in driver.calls if call.method == "send"]
    assert sends == [("What is on this screen?", (image,)), ("And now?", ())]
