"""``InMemorySessionDriver``: a scriptable ``SessionDriver`` for core, API and web-smoke tests.

Each user message plays one scripted turn: the turn scripted for that exact text
(``replies``), else the next of ``turns``, else one ``TextBlock("ok")``. A turn is a list of
``DriverEvent``s and ``Hold``s; the first turn opens with ``InitEvent``, and a turn without its
own ``TurnResult`` ends with ``DEFAULT_RESULT``. A ``PermissionRequest`` parks the turn until
``answer_permission``; a ``Hold`` parks it until ``release``. ``interrupt`` denies what is
parked and ends the turn with ``ABORTED_TERMINAL_REASON``; ``close`` and ``fail_with`` end the
process (``Exited``). Every command is logged in ``calls``; every answer in ``answers``.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from agent_hub.core.agent_sessions.driver import (
    ABORTED_TERMINAL_REASON,
    Deny,
    DriverAnswer,
    DriverCapabilities,
    DriverError,
    DriverEvent,
    DriverHandle,
    Exited,
    InitEvent,
    PastSession,
    PermissionMode,
    PermissionRequest,
    StartSpec,
    TextBlock,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import (
    PermissionAnsweredError,
    SessionTerminalError,
    UnknownPermissionError,
)
from agent_hub.core.sessions.session import TokenUsage

DEFAULT_RESULT = TurnResult(
    subtype="success",
    terminal_reason="completed",
    cost_usd=Decimal("0.0012"),
    usage=TokenUsage(input=12, output=5, cache_read=0, cache_write=0),
    duration_ms=40,
    num_turns=1,
)
ABORTED_RESULT = TurnResult(
    subtype="error_during_execution",
    terminal_reason=ABORTED_TERMINAL_REASON,
    cost_usd=Decimal("0.0004"),
    usage=TokenUsage(input=12, output=1, cache_read=0, cache_write=0),
    duration_ms=10,
    num_turns=1,
)
DEFAULT_CAPABILITIES = DriverCapabilities(
    available=True, engine="in-memory", cli_version="0.0.0-synthetic"
)
INTERRUPTED = "interrupted"
CLOSED = "session closed"


@dataclass(frozen=True)
class Hold:
    """A scripted pause: the turn waits here until released, interrupted or closed."""


type ScriptItem = DriverEvent | Hold
type Turn = Sequence[ScriptItem]


@dataclass(frozen=True)
class DriverCall:
    """One command the driver received: its name, the handle (None for none) and arguments."""

    method: str
    handle: DriverHandle | None
    args: tuple[object, ...] = ()


@dataclass(frozen=True)
class _Stop:
    code: int | None
    message: str | None


@dataclass
class _Live:
    """One started session's state."""

    spec: StartSpec
    session_id: str
    inbox: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    pending: dict[str, asyncio.Future[DriverAnswer]] = field(default_factory=dict)
    answered: set[str] = field(default_factory=set)
    initialized: bool = False
    in_turn: bool = False
    interrupted: bool = False
    released: bool = False
    stop: _Stop | None = None

    def deny_pending(self, message: str) -> None:
        for request_id, future in self.pending.items():
            if not future.done():
                future.set_result(Deny(message=message))
            self.answered.add(request_id)
        self.pending.clear()


class InMemorySessionDriver:
    """A ``SessionDriver`` that plays scripted turns; see the module docstring."""

    def __init__(
        self,
        *,
        replies: Mapping[str, Turn] | None = None,
        turns: Sequence[Turn] = (),
        capabilities: DriverCapabilities = DEFAULT_CAPABILITIES,
        past_sessions: Sequence[PastSession] = (),
    ) -> None:
        self.calls: list[DriverCall] = []
        self.answers: dict[str, DriverAnswer] = {}
        self._replies = dict(replies or {})
        self._turns = list(turns)
        self._capabilities = capabilities
        self._past_sessions = tuple(past_sessions)
        self._sessions: dict[DriverHandle, _Live] = {}

    async def start(self, spec: StartSpec) -> DriverHandle:
        """A new handle; the Claude session id is the given one, the resumed one, or minted."""
        number = len(self._sessions) + 1
        handle = DriverHandle(f"fake-{number}")
        self.calls.append(DriverCall("start", None, (spec,)))
        session_id = spec.session_id or (
            spec.resume if spec.resume is not None and not spec.fork else None
        )
        minted = f"00000000-0000-4000-8000-{number:012d}"
        self._sessions[handle] = _Live(spec=spec, session_id=session_id or minted)
        return handle

    async def send(self, handle: DriverHandle, text: str) -> None:
        """Queue a message; it plays one turn once the running one ends."""
        live = self._open(handle, "send", text)
        live.inbox.put_nowait(text)

    async def interrupt(self, handle: DriverHandle) -> None:
        """Deny what is parked and end the running turn; nothing between turns."""
        live = self._open(handle, "interrupt")
        if not live.in_turn:
            return
        live.interrupted = True
        live.deny_pending(INTERRUPTED)
        live.wake.set()

    async def answer_permission(
        self, handle: DriverHandle, request_id: str, answer: DriverAnswer
    ) -> None:
        """Resolve a parked request: unknown raises, a second answer raises."""
        live = self._open(handle, "answer_permission", request_id, answer)
        future = live.pending.pop(request_id, None)
        if future is None:
            if request_id in live.answered:
                raise PermissionAnsweredError(request_id)
            raise UnknownPermissionError(request_id)
        live.answered.add(request_id)
        self.answers[request_id] = answer
        future.set_result(answer)

    async def set_mode(self, handle: DriverHandle, mode: PermissionMode) -> None:
        """Record the new mode."""
        self._open(handle, "set_mode", mode)

    async def set_model(self, handle: DriverHandle, model: str | None) -> None:
        """Record the new model."""
        self._open(handle, "set_model", model)

    async def close(self, handle: DriverHandle) -> None:
        """End the process (exit code 0); a second close does nothing."""
        self.calls.append(DriverCall("close", handle))
        self._end(self._live(handle), _Stop(code=0, message=None))

    def fail_with(self, handle: DriverHandle, code: int, message: str = "claude exited") -> None:
        """End the process as a crash: ``DriverError(message)``, then ``Exited(code)``."""
        self.calls.append(DriverCall("fail_with", handle, (code,)))
        self._end(self._live(handle), _Stop(code=code, message=message))

    def release(self, handle: DriverHandle) -> None:
        """Let a turn parked on a ``Hold`` go on."""
        live = self._live(handle)
        live.released = True
        live.wake.set()

    async def events(self, handle: DriverHandle) -> AsyncIterator[DriverEvent]:
        """The session's events: a turn per message, ``Exited`` last."""
        live = self._live(handle)
        while live.stop is None:
            text = await live.inbox.get()
            if text is None or live.stop is not None:
                break
            async for event in self._turn(live, text):
                yield event
        if live.stop is not None and live.stop.message is not None:
            yield DriverError(message=live.stop.message)
        yield Exited(code=None if live.stop is None else live.stop.code)

    async def list_resumable(self, cwd: str) -> tuple[PastSession, ...]:
        """The configured past sessions of ``cwd``."""
        self.calls.append(DriverCall("list_resumable", None, (cwd,)))
        return tuple(past for past in self._past_sessions if past.cwd == cwd)

    async def capabilities(self) -> DriverCapabilities:
        """The configured capabilities."""
        self.calls.append(DriverCall("capabilities", None))
        return self._capabilities

    async def _turn(self, live: _Live, text: str) -> AsyncIterator[DriverEvent]:
        live.in_turn = True
        if not live.initialized:
            live.initialized = True
            yield InitEvent(session_id=live.session_id, model=live.spec.model or "default")
        ended = False
        for item in self._script_for(text):
            if live.stop is not None or live.interrupted:
                break
            if isinstance(item, Hold):
                await self._hold(live)
                continue
            parked = self._park(live, item) if isinstance(item, PermissionRequest) else None
            yield item
            if parked is not None:
                await parked
            if isinstance(item, TurnResult):
                ended = True
                break
        live.in_turn = False
        if live.stop is None and not ended:
            yield ABORTED_RESULT if live.interrupted else DEFAULT_RESULT
        live.interrupted = False

    def _script_for(self, text: str) -> Turn:
        if text in self._replies:
            return self._replies[text]
        if self._turns:
            return self._turns.pop(0)
        return (TextBlock(block=0, text="ok"),)

    @staticmethod
    def _park(live: _Live, request: PermissionRequest) -> asyncio.Future[DriverAnswer]:
        # Parked before the request is yielded, so an answer that comes at once finds it.
        future: asyncio.Future[DriverAnswer] = asyncio.get_running_loop().create_future()
        live.pending[request.request_id] = future
        return future

    @staticmethod
    async def _hold(live: _Live) -> None:
        live.wake.clear()
        if not (live.released or live.interrupted or live.stop is not None):
            await live.wake.wait()
        live.released = False

    def _end(self, live: _Live, stop: _Stop) -> None:
        if live.stop is not None:
            return
        live.stop = stop
        live.deny_pending(CLOSED)
        live.wake.set()
        live.inbox.put_nowait(None)

    def _live(self, handle: DriverHandle) -> _Live:
        return self._sessions[handle]

    def _open(self, handle: DriverHandle, method: str, *args: object) -> _Live:
        self.calls.append(DriverCall(method, handle, args))
        live = self._live(handle)
        if live.stop is not None:
            raise SessionTerminalError(handle, status="ended")
        return live
