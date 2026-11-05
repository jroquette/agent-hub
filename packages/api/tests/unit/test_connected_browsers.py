"""The count of open global streams (AGH-613): the app shell keeps one ``GET
/api/v1/events/stream`` open in every tab that shows the app, so the ticket warmer reads Linear
only while one is open, and the first one to open wakes it.

Seam: ``ConnectedBrowsers(on_first_open=None)`` with ``opened()``, ``closed()`` and
``connected()``; ``counted(stream, browsers)``, an async generator that counts its stream from
its first chunk until it ends, fails or is closed, and closes the stream; the stream route
functions over ``StreamPorts`` whose ``browsers`` is the count, and fake event ports.
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from agent_hub.api.change_feed import ChangeFeed
from agent_hub.api.connected_browsers import ConnectedBrowsers, counted
from agent_hub.api.dependencies import StreamPorts
from agent_hub.api.routes.streams import stream_events, stream_live_sessions


class BrokenStreamError(Exception):
    """What a fake stream raises after its first chunk."""


async def _chunks(name: str, ended: list[str], *, broken: bool = False) -> AsyncIterator[bytes]:
    """A stream of two chunks (or one, then ``BrokenStreamError``) that notes ``name`` in
    ``ended`` when it ends, however it ends."""
    try:
        yield b"retry: 3000\n\n"
        if broken:
            raise BrokenStreamError(name)
        yield b": still here\n\n"
    finally:
        ended.append(name)


@pytest.mark.anyio
async def test_counts_open_global_streams_when_streams_open_and_close() -> None:
    """A stream counts from its first chunk until it is closed or fails, and its own stream is
    closed with it; one stream still open keeps the count connected."""
    browsers = ConnectedBrowsers()
    ended: list[str] = []
    first = counted(_chunks("first", ended), browsers)
    second = counted(_chunks("second", ended, broken=True), browsers)
    assert not browsers.connected()

    await anext(first)
    await anext(second)
    both_open = browsers.connected()
    await first.aclose()
    one_open = browsers.connected()
    with pytest.raises(BrokenStreamError):
        await anext(second)

    assert (both_open, one_open) == (True, True)
    assert not browsers.connected()
    assert sorted(ended) == ["first", "second"]


@pytest.mark.anyio
async def test_counts_only_global_stream_when_any_stream_opens(fakes: SimpleNamespace) -> None:
    """AC-34: only ``GET /api/v1/events/stream`` counts a browser; the live tiles' stream, which
    a page may also hold open, does not."""
    browsers = ConnectedBrowsers()
    reader = fakes.EventReader()
    ports = StreamPorts(
        reader=reader,
        feed=ChangeFeed(reader, timer=fakes.Clock()),
        models=fakes.EventReadModels(),
        counters=None,
        browsers=browsers,
    )
    live = stream_live_sessions(ports).body_iterator
    events = stream_events(ports).body_iterator

    live_first = await anext(live)
    after_live = browsers.connected()
    events_first = await anext(events)
    after_events = browsers.connected()
    await events.aclose()
    await live.aclose()

    assert live_first.startswith(b"retry:")
    assert events_first.startswith(b"retry:")
    assert (after_live, after_events) == (False, True)
    assert not browsers.connected()


def test_calls_first_open_hook_only_when_count_leaves_zero() -> None:
    """``on_first_open`` runs when the count goes from 0 to 1, so the first tab to open gets the
    warmer's tick at once; a second tab, or a close that leaves one open, does not run it."""
    calls: list[int] = []
    browsers = ConnectedBrowsers(on_first_open=lambda: calls.append(len(calls) + 1))

    browsers.opened()
    after_first = list(calls)
    browsers.opened()
    browsers.closed()
    after_second_and_close = list(calls)
    browsers.closed()
    browsers.opened()

    assert after_first == [1]
    assert after_second_and_close == [1]
    assert calls == [1, 2]
    assert browsers.connected()


def test_stays_at_zero_when_closed_more_than_opened() -> None:
    """A close with no stream open leaves the count at 0, never below: the next open makes it
    connected and runs ``on_first_open``, so an extra close cannot hide a tab from the warmer."""
    calls: list[int] = []
    browsers = ConnectedBrowsers(on_first_open=lambda: calls.append(len(calls) + 1))

    browsers.closed()
    browsers.closed()
    after_extra_closes = browsers.connected()
    browsers.opened()
    after_open = browsers.connected()
    browsers.closed()

    assert after_extra_closes is False
    assert after_open is True
    assert calls == [1]
    assert not browsers.connected()
