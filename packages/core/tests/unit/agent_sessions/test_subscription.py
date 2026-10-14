from collections.abc import AsyncIterator, Callable

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, SendMessage
from agent_hub.core.agent_sessions.driver import TextBlock, TextDelta
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.records import (
    DeltaFrame,
    LogRecord,
    ResetFrame,
    StatusFrame,
    StreamItem,
    StreamPosition,
)
from agent_hub.core.testing.agent_session_rig import Rig
from agent_hub.core.testing.session_driver_fakes import Hold, Turn

type MakeRig = Callable[..., Rig]

pytestmark = pytest.mark.anyio

GITHUB_TOKEN = "ghp_" + "Ab1" * 12
STREAMED = (
    TextDelta(block=0, index=0, text="Hel"),
    TextDelta(block=0, index=1, text="lo, "),
    TextDelta(block=0, index=2, text="you."),
    Hold(),
    TextBlock(block=0, text="Hello, you."),
)


def _label(item: StreamItem) -> str:
    match item:
        case LogRecord(seq=seq, kind=kind):
            return f"{seq}:{kind}"
        case DeltaFrame(after_seq=after_seq, index=index):
            return f"{after_seq}.{index}"
        case StatusFrame(status=status):
            return f"status:{status}"
        case ResetFrame():
            return "reset"


async def _take(stream: AsyncIterator[StreamItem], until: str) -> list[str]:
    labels: list[str] = []
    async for item in stream:
        labels.append(_label(item))
        if labels[-1] == until:
            break
    return labels


async def _streaming(make_rig: MakeRig, *, more: Turn = (), **options: object) -> tuple[Rig, str]:
    rig = make_rig(replies={"Greet me.": STREAMED, "More.": more}, **options)
    created = await rig.create("Greet me.")
    live = rig.control._live[created.id]  # noqa: SLF001 -- wait until the deltas are in
    await rig.until(lambda: live.ring.since(2) is not None and len(live.ring.since(2) or []) == 3)
    return rig, created.id


async def test_replays_store_then_ring_when_reconnected(make_rig: MakeRig) -> None:
    rig, session_id = await _streaming(make_rig)

    stream = await rig.control.subscribe(session_id, StreamPosition(seq=1))
    replayed = await _take(stream, "status:running")
    rig.driver.release(rig.handle())
    live = await _take(stream, "4:result")
    again = await rig.control.subscribe(session_id, StreamPosition(seq=2, delta=0))
    resumed = await _take(again, "4:result")

    assert replayed == ["2:init", "2.0", "2.1", "2.2", "status:running"]
    assert live == ["3:text", "4:result"]
    assert resumed[:2] == ["3:text", "4:result"]


async def test_sends_only_later_deltas_when_position_inside_block(make_rig: MakeRig) -> None:
    rig, session_id = await _streaming(make_rig)

    stream = await rig.control.subscribe(session_id, StreamPosition(seq=2, delta=0))

    assert await _take(stream, "status:running") == ["2.1", "2.2", "status:running"]


async def test_sends_text_block_when_ring_evicted(make_rig: MakeRig) -> None:
    more = (
        *(TextDelta(block=0, index=n, text="x") for n in range(3)),
        TextBlock(block=0, text="xxx"),
    )
    rig, session_id = await _streaming(make_rig, more=more, limits=SessionLimits(delta_ring=3))
    await rig.control.send(session_id, SendMessage(text="More."))
    rig.driver.release(rig.handle())
    await rig.until(lambda: rig.kinds(session_id).count("result") == 2)

    stream = await rig.control.subscribe(session_id, StreamPosition(seq=2, delta=0))
    labels = await _take(stream, "status:idle")

    assert labels[:2] == ["3:user.message", "4:text"]
    assert not [label for label in labels if label.startswith("2.")]


async def test_sends_live_frames_only_when_no_position(make_rig: MakeRig) -> None:
    rig, session_id = await _streaming(make_rig)

    stream = await rig.control.subscribe(session_id, None)
    first = await _take(stream, "status:running")
    rig.driver.release(rig.handle())

    assert first == ["status:running"]
    assert await _take(stream, "4:result") == ["3:text", "4:result"]


async def test_sends_reset_when_id_from_other_session(make_rig: MakeRig) -> None:
    rig, session_id = await _streaming(make_rig)

    stream = await rig.control.subscribe(session_id, StreamPosition(seq=99, delta=3))
    labels = await _take(stream, "status:running")

    assert labels == ["reset", "status:running"]


async def test_streams_raw_live_and_replays_redacted_when_text_holds_token(
    make_rig: MakeRig,
) -> None:
    secret = f"token {GITHUB_TOKEN}"
    rig = make_rig(replies={"Show it.": (Hold(), TextBlock(block=0, text=secret))})
    created = await rig.create("Show it.")
    await rig.until(lambda: "init" in rig.kinds(created.id))
    stream = await rig.control.subscribe(created.id, StreamPosition(seq=2))
    await _take(stream, "status:running")

    rig.driver.release(rig.handle())
    live_text = await anext(aiter(stream))
    replay = await rig.control.subscribe(created.id, StreamPosition(seq=2))
    stored_text = await anext(aiter(replay))

    assert isinstance(live_text, LogRecord)
    assert isinstance(stored_text, LogRecord)
    assert live_text.body["text"] == secret
    assert GITHUB_TOKEN not in str(stored_text.body)


async def test_ends_stream_after_status_when_session_ended(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create("Say hello.")
    await rig.until_status(created.id, "idle")
    await rig.control.close(created.id)

    stream = await rig.control.subscribe(created.id, StreamPosition(seq=0))
    labels = [_label(item) async for item in stream]
    live_only = [_label(item) async for item in await rig.control.subscribe(created.id, None)]

    assert live_only == [f"status:{AgentSessionStatus.ENDED}"]
    assert labels[0] == "1:user.message"
    assert labels[-1] == f"status:{AgentSessionStatus.ENDED}"
    assert "6:exited" in labels


async def test_ends_live_stream_when_session_closes(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create()
    stream = await rig.control.subscribe(created.id, None)
    await _take(stream, "status:idle")

    await rig.control.close(created.id)
    labels = [_label(item) async for item in stream]

    assert labels == ["1:close", "status:ended", "2:exited"]


async def test_ends_oldest_stream_when_subscriber_cap_reached(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(subscribers=1))
    created = await rig.create()
    first = await rig.control.subscribe(created.id, None)
    await _take(first, "status:idle")

    second = await rig.control.subscribe(created.id, None)
    await _take(second, "status:idle")
    rest = [_label(item) async for item in first]

    assert rest == ["reset"]


async def test_raises_not_found_when_session_unknown(make_rig: MakeRig) -> None:
    rig = make_rig()

    with pytest.raises(AgentSessionNotFoundError):
        await rig.control.subscribe("01929a4e-0000-7000-8000-000000000000", None)
