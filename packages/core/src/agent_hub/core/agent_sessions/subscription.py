"""One stream of an agent session (S4, S7, E8, E9): replay from a position, then live frames.

``frames`` yields, in order:

1. a ``ResetFrame`` when the position cannot be resumed (its ``seq`` is past the log: another
   session's id, or a store that was reset); the stream then goes on with live frames only
   (steps 4 and 5), and the client reloads the snapshot and the log;
2. the stored records after the position's ``seq``, in pages, as the store holds them
   (redacted, E9); no position (None) means live frames only: no replay and no ring deltas
   (the API route sends its own reset for a malformed ``Last-Event-ID``);
3. while the session is live, the deltas of its open block that the ring still holds after the
   position (``<seq>.<n>``); when the ring dropped one of them, none: the completed ``text``
   record brings the content instead;
4. the session's status;
5. while it is live, every frame as it is published (raw records, deltas, statuses), woken
   in-process (S7). Records the replay already sent and deltas older than the last record sent
   are skipped, so nothing comes twice and ``seq`` never goes back.

A subscriber that falls behind the live buffer replays the store again from its last record
(no record is lost); a subscriber detached by a newer one (the cap) gets a reset and ends. The
stream ends after the session's last frame, or after step 4 for an ended session.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from typing import Final

from agent_hub.core.agent_sessions.agent_session import AgentSession
from agent_hub.core.agent_sessions.delta_ring import DeltaRing
from agent_hub.core.agent_sessions.live_session import LiveSession, Subscriber
from agent_hub.core.agent_sessions.records import (
    DeltaFrame,
    LogRecord,
    ResetFrame,
    StatusFrame,
    StreamItem,
    StreamPosition,
)

# How many stored records one replay read takes.
REPLAY_PAGE: Final = 200
UNKNOWN_POSITION: Final = "the position is not in this session's log"
REPLACED: Final = "a newer stream of this session replaced this one"

# Reads stored records: ``(after, limit)`` → records after ``after``, in ``seq`` order.
type RecordReader = Callable[[int, int], Awaitable[tuple[LogRecord, ...]]]


class _Sent:
    """What a stream has sent: the last record's ``seq`` and the last delta's key."""

    def __init__(self, position: StreamPosition) -> None:
        self.seq = position.seq
        self.delta: tuple[int, int] | None = (
            None if position.delta is None else (position.seq, position.delta)
        )

    def wants(self, item: StreamItem) -> bool:
        """Whether ``item`` is new to the stream (and note it as sent)."""
        if isinstance(item, LogRecord):
            if item.seq <= self.seq:
                return False
            self.seq = item.seq
            return True
        if isinstance(item, DeltaFrame):
            key = (item.after_seq, item.index)
            if item.after_seq < self.seq or (self.delta is not None and key <= self.delta):
                return False
            self.delta = key
            return True
        return True


async def frames(
    session: AgentSession,
    after: StreamPosition | None,
    *,
    live: LiveSession | None,
    read: RecordReader,
) -> AsyncIterator[StreamItem]:
    """The stream of ``session`` from ``after`` (None: live frames only); see the module
    docstring. ``live`` is the session while the server drives it."""
    subscriber = None if live is None else live.attach()
    try:
        last_seq = session.last_seq if live is None else live.last_seq
        replay = after is not None and after.seq <= last_seq
        if after is not None and not replay:
            yield ResetFrame(reason=UNKNOWN_POSITION)
        position = after if after is not None and replay else StreamPosition(seq=last_seq)
        sent = _Sent(position)
        if replay:
            async for item in _replayed(read, sent, ring=None if live is None else live.ring):
                yield item
        if live is None or subscriber is None:
            yield StatusFrame(status=session.status, end_reason=session.end_reason)
            return
        yield StatusFrame(status=live.session.status, end_reason=live.session.end_reason)
        async for item in _live(live, subscriber, sent=sent, read=read):
            yield item
    finally:
        if live is not None and subscriber is not None:
            live.detach(subscriber)


def _new[T: StreamItem](items: Iterable[T], sent: _Sent) -> Iterator[T]:
    return (item for item in items if sent.wants(item))


async def _replayed(
    read: RecordReader, sent: _Sent, *, ring: DeltaRing | None = None
) -> AsyncIterator[StreamItem]:
    """The stored records after the last one sent, in pages; then, given the ring, the deltas
    it still holds after the position (none when it dropped one)."""
    position = (sent.seq, sent.delta)
    after = sent.seq
    while True:
        page = await read(after, REPLAY_PAGE)
        for record in _new(page, sent):
            yield record
        if len(page) < REPLAY_PAGE:
            break
        after = page[-1].seq
    if ring is not None:
        start, delta = position
        within = delta[1] if delta is not None and sent.seq == start else None
        for frame in _new(ring.since(sent.seq, within) or (), sent):
            yield frame


async def _live(
    live: LiveSession, subscriber: Subscriber, *, sent: _Sent, read: RecordReader
) -> AsyncIterator[StreamItem]:
    while not subscriber.detached:
        published = live.frames_after(subscriber.cursor)
        if published is None:
            # Behind the live buffer: replay what the store has since the last record sent.
            subscriber.cursor = live.published
            async for record in _replayed(read, sent):
                yield record
            continue
        for number, item in published:
            subscriber.cursor = number
            if sent.wants(item):
                yield item
        if not published:
            if live.finished:
                return
            await live.wait_after(subscriber)
    yield ResetFrame(reason=REPLACED)
