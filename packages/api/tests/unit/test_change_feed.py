import asyncio
from typing import Any

from agent_hub.api.change_feed import ChangeFeed, SystemTimer
from agent_hub.core.testing.builders import an_event


def test_returns_mark_when_store_passes_seen(fakes: Any) -> None:
    reader, clock = fakes.EventReader(), fakes.Clock()
    reader.add(an_event(), an_event())
    feed = ChangeFeed(reader, timer=clock)

    mark = asyncio.run(feed.wait_beyond(1, deadline=10))

    assert (mark, clock.elapsed) == (2, 0)


def test_wakes_when_event_appended_while_waiting(fakes: Any) -> None:
    reader, clock = fakes.EventReader(), fakes.Clock()
    clock.on_sleep = lambda elapsed: reader.add(an_event()) if elapsed == 1.5 else None
    feed = ChangeFeed(reader, timer=clock, interval=0.5)

    mark = asyncio.run(feed.wait_beyond(0, deadline=10))

    assert (mark, clock.elapsed) == (1, 1.5)


def test_returns_same_mark_when_deadline_passes(fakes: Any) -> None:
    reader, clock = fakes.EventReader(), fakes.Clock()
    feed = ChangeFeed(reader, timer=clock, interval=0.5)

    mark = asyncio.run(feed.wait_beyond(0, deadline=2.2))

    assert mark == 0
    assert clock.elapsed == 2.2


def test_reads_mark_once_per_interval_when_many_wait(fakes: Any) -> None:
    class CountingReader(fakes.EventReader):  # type: ignore[misc]
        reads = 0

        def high_water_mark(self) -> int:
            CountingReader.reads += 1
            return int(super().high_water_mark())

    clock = fakes.Clock()
    feed = ChangeFeed(CountingReader(), timer=clock, interval=0.5)

    async def wait_twice() -> None:
        await asyncio.gather(feed.wait_beyond(0, deadline=0), feed.wait_beyond(0, deadline=0))

    asyncio.run(wait_twice())

    assert CountingReader.reads == 1


def test_ends_waiting_when_closed(fakes: Any) -> None:
    reader, clock = fakes.EventReader(), fakes.Clock()
    feed = ChangeFeed(reader, timer=clock)
    clock.on_sleep = lambda elapsed: feed.close() if elapsed >= 1 else None

    assert asyncio.run(feed.wait_beyond(0, deadline=60)) is None
    assert feed.is_closed


def test_uses_real_clocks_when_system_timer_used(fakes: Any) -> None:
    timer = SystemTimer(lambda: fakes.Clock().now())
    before = timer.monotonic()

    asyncio.run(timer.sleep(0))

    assert timer.monotonic() >= before
    assert timer.now() == fakes.Clock().now()
