"""Server-Sent Events: the wire format, resumption after ``Last-Event-ID`` and the stream loop.

Every stream sends ``retry: 3000`` first; replays what came after ``Last-Event-ID`` (at most
10,000 events and 24 h, else ``event: reset``); then sends what each new batch of events
changes, and a heartbeat every 15 s carrying the last real id, so a reconnecting client resumes
exactly (design spec 02, "SSE contract"). What a batch changes is the view's business
(``stream_views``); this module knows only events, ids and time.
"""

import json
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import JsonValue
from starlette.concurrency import run_in_threadpool

from agent_hub.api.change_feed import ChangeFeed
from agent_hub.core.events.event_query import MAX_QUERY_LIMIT, EventQuery
from agent_hub.core.events.event_reader import EventReader
from agent_hub.core.events.stored_event import UUID_TEXT_PATTERN, StoredEvent
from agent_hub.core.readmodels.view_types import timestamp_text

RETRY_MILLISECONDS = 3000
HEARTBEAT_SECONDS = 15.0
MAX_REPLAY_EVENTS = 10_000
MAX_REPLAY_AGE = timedelta(hours=24)

_EVENT_ID = re.compile(UUID_TEXT_PATTERN)


@dataclass(frozen=True)
class SseMessage:
    """One message: its event name, its JSON data and the id a client resumes from."""

    event: str
    data: JsonValue
    id: str | None = None

    def encode(self) -> bytes:
        """The message on the wire: ``event``, ``id`` when known, one ``data`` line."""
        lines = [f"event: {self.event}"]
        if self.id is not None:
            lines.append(f"id: {self.id}")
        # json.dumps escapes every line break, so the data stays on one line.
        lines.append(f"data: {json.dumps(self.data, separators=(',', ':'))}")
        return ("\n".join(lines) + "\n\n").encode()


RETRY = f"retry: {RETRY_MILLISECONDS}\n\n".encode()


class StreamView(Protocol):
    """What one stream shows; every method is synchronous (it reads the store) and runs in a
    worker thread."""

    def scope(self) -> EventQuery:
        """The events that concern this stream (filters only; the window is the loop's)."""
        ...

    def prime(self) -> None:
        """Take the starting state that later batches are compared with."""
        ...

    def replay(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The messages for a client that resumes after missing ``events``."""
        ...

    def changes(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The messages a new batch of ``events`` causes."""
        ...

    def heartbeat(self, now: datetime) -> dict[str, JsonValue]:
        """The heartbeat's data."""
        ...


@dataclass(frozen=True)
class Window:
    """Events read between two marks; ``overflow`` when more than the cap were there."""

    events: tuple[StoredEvent, ...]
    overflow: bool


def read_window(reader: EventReader, scope: EventQuery, *, after: int, upto: int) -> Window:
    """The scoped events with ``after`` < seq <= ``upto``, in append order, at most 10,000."""
    events: list[StoredEvent] = []
    cursor = after
    while True:
        wanted = min(MAX_QUERY_LIMIT, MAX_REPLAY_EVENTS + 1 - len(events))
        page = reader.query(
            scope.model_copy(
                update={
                    "after_seq": cursor,
                    "before_seq": upto + 1,
                    "limit": wanted,
                    "order": "asc",
                }
            )
        )
        events.extend(page.items)
        if len(events) > MAX_REPLAY_EVENTS:
            return Window(events=tuple(events[:MAX_REPLAY_EVENTS]), overflow=True)
        if page.next_after_seq is None or not page.items:
            return Window(events=tuple(events), overflow=False)
        cursor = page.next_after_seq


def resume_seq(reader: EventReader, last_event_id: str, *, now: datetime) -> int | None:
    """The append sequence to replay after, or None when the id cannot be resumed from.

    An id that is not a stored event id, or names an event received more than 24 h ago, cannot.
    """
    if not _EVENT_ID.fullmatch(last_event_id):
        return None
    stored = reader.find(last_event_id)
    if stored is None:
        return None
    received = stored.received_at or stored.event.timestamp
    if now - received > MAX_REPLAY_AGE:
        return None
    return stored.seq


def reset_message() -> SseMessage:
    """``event: reset``: the client refetches its data and listens on."""
    return SseMessage(event="reset", data={"reason": "replay_unavailable"})


@dataclass
class _Position:
    seq: int
    last_id: str | None


async def event_stream(
    view: StreamView, *, reader: EventReader, feed: ChangeFeed, last_event_id: str | None
) -> AsyncIterator[bytes]:
    """The bytes of one stream, until the client leaves or the feed closes."""
    yield RETRY
    timer = feed.timer
    position = _Position(seq=await run_in_threadpool(reader.high_water_mark), last_id=None)
    await run_in_threadpool(view.prime)
    if last_event_id is not None:
        for message in await run_in_threadpool(
            _resume, view, reader, last_event_id, now=timer.now(), position=position
        ):
            yield message.encode()
    next_beat = timer.monotonic() + HEARTBEAT_SECONDS
    while True:
        mark = await feed.wait_beyond(position.seq, deadline=next_beat)
        if mark is None:
            return
        if mark > position.seq:
            for message in await run_in_threadpool(_advance, view, reader, mark, position=position):
                yield message.encode()
        if timer.monotonic() >= next_beat:
            beat = SseMessage("heartbeat", view.heartbeat(timer.now()), id=position.last_id)
            yield beat.encode()
            next_beat = timer.monotonic() + HEARTBEAT_SECONDS


def _resume(
    view: StreamView,
    reader: EventReader,
    last_event_id: str,
    *,
    now: datetime,
    position: _Position,
) -> list[SseMessage]:
    seq = resume_seq(reader, last_event_id, now=now)
    if seq is None:
        return [reset_message()]
    window = read_window(reader, view.scope(), after=seq, upto=position.seq)
    if window.overflow:
        return [reset_message()]
    position.last_id = window.events[-1].event_id if window.events else last_event_id
    return view.replay(window.events)


def _advance(
    view: StreamView, reader: EventReader, mark: int, *, position: _Position
) -> list[SseMessage]:
    window = read_window(reader, view.scope(), after=position.seq, upto=mark)
    position.seq = mark
    if window.overflow:
        view.prime()
        return [reset_message()]
    if not window.events:
        return []
    position.last_id = window.events[-1].event_id
    return view.changes(window.events)


def heartbeat_data(now: datetime) -> dict[str, JsonValue]:
    """The heartbeat data every stream shares: when it was sent."""
    return {"at": timestamp_text(now)}
