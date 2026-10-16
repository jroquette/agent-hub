"""One live agent session in ``hub web``'s event loop (P10, P11).

``LiveSession`` holds what only memory knows about a session the server drives: the driver
handle, the status machine's state, the delta ring, the log budget, the open permission
requests (raw summaries, E10), and the live frames its subscribers read.

Frames: ``publish`` appends a frame (a raw record, a delta or a status) to a short buffer
numbered from 1 and wakes every subscriber through one ``asyncio.Condition`` (S7: in-process,
never a poll). A subscriber keeps the number of the last frame it read; ``frames_after``
answers the newer ones, or None when the buffer dropped some of them (the subscriber then
replays the store, which loses nothing but deltas the ``text`` record supersedes).

At most ``limits.subscribers`` subscribers are attached; attaching one more detaches the
oldest, whose stream ends with a reset (a reloaded tab replaces its stale stream).
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from agent_hub.core.agent_sessions.agent_session import AgentSession, OpenPermission
from agent_hub.core.agent_sessions.delta_ring import DeltaRing
from agent_hub.core.agent_sessions.driver import DriverHandle, PermissionRequest
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.log_caps import LogBudget
from agent_hub.core.agent_sessions.records import StreamItem
from agent_hub.core.agent_sessions.session_state import SessionState

# How many live frames a session keeps for subscribers that are a little behind.
LIVE_BUFFER: Final = 512


@dataclass(eq=False)
class Subscriber:
    """One attached stream: the number of the last live frame it read."""

    cursor: int
    detached: bool = False


@dataclass(frozen=True)
class OpenRequest:
    """A permission request the session waits on: what the driver asked and what the browser
    sees."""

    request: PermissionRequest
    view: OpenPermission


@dataclass(eq=False)
class LiveSession:
    """What memory holds about one session the server drives; see the module docstring."""

    session: AgentSession
    handle: DriverHandle
    state: SessionState
    limits: SessionLimits
    # The folder the session runs in: where Claude Code keeps the title it gives the session.
    cwd: str | None = None
    ring: DeltaRing = field(init=False)
    budget: LogBudget = field(init=False)
    # ``emit_lock`` keeps seq order equal to emit order (``last_seq`` moves only under it);
    # ``commands`` runs one command at a time; ``sync_lock`` serializes the session's store
    # writes, so the last write and the last status frame show the state current at that write;
    # ``end_task`` ends the session once.
    emit_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    commands: asyncio.Lock = field(default_factory=asyncio.Lock)
    sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    requests: dict[str, OpenRequest] = field(default_factory=dict)
    answered: set[str] = field(default_factory=set)
    last_seq: int = 0
    idle_since: datetime | None = None
    error_logged: bool = False
    ended: bool = False
    pump: asyncio.Task[None] | None = None
    end_task: asyncio.Task[None] | None = None
    _frames: deque[tuple[int, StreamItem]] = field(
        default_factory=lambda: deque(maxlen=LIVE_BUFFER)
    )
    _number: int = 0
    _finished: bool = False
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    _subscribers: list[Subscriber] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.ring = DeltaRing(self.limits.delta_ring)
        self.budget = LogBudget(self.limits)
        self.last_seq = self.session.last_seq

    @property
    def id(self) -> str:
        """The agent session's id."""
        return self.session.id

    @property
    def published(self) -> int:
        """The number of the last frame published."""
        return self._number

    @property
    def finished(self) -> bool:
        """Whether no frame will come any more (the driver's events ended)."""
        return self._finished

    def view(self) -> AgentSession:
        """The session as ``GET /{id}`` shows it: its last ``seq`` and the oldest open request
        (raw, E10)."""
        oldest = next(iter(self.requests.values()), None)
        return self.session.model_copy(
            update={
                "last_seq": self.last_seq,
                "open_permission": None if oldest is None else oldest.view,
            }
        )

    async def publish(self, item: StreamItem) -> None:
        """Add a live frame and wake the subscribers."""
        async with self._condition:
            self._number += 1
            self._frames.append((self._number, item))
            self._condition.notify_all()

    async def finish(self) -> None:
        """No more frames: wake the subscribers so their streams end."""
        async with self._condition:
            self._finished = True
            self._condition.notify_all()

    def attach(self) -> Subscriber:
        """A new subscriber that reads the frames published from now on; the oldest one is
        detached when the cap is reached."""
        while len(self._subscribers) >= self.limits.subscribers:
            self._subscribers.pop(0).detached = True
        subscriber = Subscriber(cursor=self._number)
        self._subscribers.append(subscriber)
        return subscriber

    def detach(self, subscriber: Subscriber) -> None:
        """Forget a subscriber whose stream ended."""
        subscriber.detached = True
        if subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def frames_after(self, cursor: int) -> list[tuple[int, StreamItem]] | None:
        """The frames after number ``cursor``; None when the buffer dropped one of them."""
        if self._frames and self._frames[0][0] > cursor + 1:
            return None
        return [(number, item) for number, item in self._frames if number > cursor]

    async def wait_after(self, subscriber: Subscriber) -> None:
        """Wait until a frame after the subscriber's cursor exists, the session finished or
        the subscriber was detached."""
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._number > subscriber.cursor or self._finished or subscriber.detached
            )

    async def wake(self) -> None:
        """Wake the subscribers (one was detached)."""
        async with self._condition:
            self._condition.notify_all()
