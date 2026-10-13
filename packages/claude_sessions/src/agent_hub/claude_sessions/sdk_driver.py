"""``ClaudeSdkSessionDriver``: the ``SessionDriver`` port over the Claude Agent SDK (D.5, G0).

One ``ClaudeSDKClient`` per handle, in streaming-input mode, pointed at the ``claude`` on
``PATH`` (``options.sdk_options``). A reader task maps the SDK's messages to ``DriverEvent``s
(``message_mapping``) into the handle's queue; ``PermissionBridge`` puts the permission requests
there too. ``events`` drains that queue until ``Exited``.

- ``interrupt`` sends the CLI's interrupt, then denies what is parked; the turn's
  ``TurnResult`` (``ABORTED_TERMINAL_REASON``) follows from the CLI.
- ``close`` (idempotent): interrupt when a turn runs (at most ``INTERRUPT_SECONDS``), deny every
  request, then ``disconnect()``. Interrupting first lets the CLI end at once when stdin closes
  (spike: 0.05 s instead of the SDK's 5 s grace). If the CLI still runs after
  ``DISCONNECT_GRACE_SECONDS``, ``process_tree.terminate`` stops it (SIGTERM, then SIGKILL), so a
  close stays within the shutdown budget (P12). ``Exited(code=0)`` follows.
- When the CLI ends on its own, ``Exited`` carries its exit code (after a ``DriverError`` when it is
  not 0). When the stream breaks (a message over ``max_buffer_size``, a lost pipe), a
  ``DriverError`` naming the cause and ``Exited(code=PROTOCOL_EXIT_CODE)`` end the events and the
  CLI is stopped. Error messages never hold conversation text.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    ProcessError,
)

from agent_hub.claude_sessions.capabilities import CapabilityCache, Runner, bounded_runner, detect
from agent_hub.claude_sessions.message_mapping import EventMapper
from agent_hub.claude_sessions.options import MAX_BUFFER_BYTES, claude_path, sdk_options
from agent_hub.claude_sessions.permission_bridge import INTERRUPTED, PermissionBridge
from agent_hub.claude_sessions.process_tree import terminate
from agent_hub.claude_sessions.resumable import SessionLister, list_resumable, sdk_lister
from agent_hub.core.agent_sessions.driver import (
    ABORTED_TERMINAL_REASON,
    DriverAnswer,
    DriverCapabilities,
    DriverError,
    DriverEvent,
    DriverHandle,
    Exited,
    PastSession,
    PermissionMode,
    StartSpec,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError, SessionTerminalError

INTERRUPT_SECONDS: Final = 0.5
DISCONNECT_GRACE_SECONDS: Final = 1.5
TERMINATE_GRACE_SECONDS: Final = 0.5
READER_SECONDS: Final = 2.0
PROTOCOL_EXIT_CODE: Final = 1
NO_CLAUDE: Final = "no claude executable on PATH: install Claude Code"
NOT_STARTED: Final = "claude did not start"

type ClientFactory = Callable[..., ClaudeSDKClient]


@dataclass
class _Session:
    """One handle's client, queue and turn state."""

    client: ClaudeSDKClient
    bridge: PermissionBridge
    queue: asyncio.Queue[DriverEvent]
    pid: int | None = None
    reader: asyncio.Task[None] | None = None
    turns: int = 0
    closing: bool = False
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    exited: bool = False

    def emit(self, event: DriverEvent) -> None:
        """Queue ``event`` (nothing after ``Exited``) and count the turns still open."""
        if self.exited:
            return
        if isinstance(event, TurnResult):
            aborted = event.terminal_reason == ABORTED_TERMINAL_REASON
            self.turns = 0 if aborted else max(self.turns - 1, 0)
        if isinstance(event, Exited):
            self.exited = True
        self.queue.put_nowait(event)


def _failure(error: Exception, *, limit: int) -> tuple[str, int]:
    """What a broken stream is reported as: a message without conversation text, and a code."""
    match error:
        case ProcessError(exit_code=int() as code) if code != 0:
            return f"claude exited with code {code}", code
        case CLIJSONDecodeError():
            return f"claude sent a message over {limit} bytes or not JSON", (PROTOCOL_EXIT_CODE)
        case _:
            return f"lost the connection to claude ({type(error).__name__})", PROTOCOL_EXIT_CODE


class ClaudeSdkSessionDriver:
    """Drives the user's own ``claude`` through the SDK; see the module docstring."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        run: Runner = bounded_runner,
        lister: SessionLister = sdk_lister,
        cloud_followup: bool = False,
        max_buffer_size: int = MAX_BUFFER_BYTES,
        client_factory: ClientFactory = ClaudeSDKClient,
    ) -> None:
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        self._lister = lister
        self._max_buffer_size = max_buffer_size
        self._client_factory = client_factory
        self._sessions: dict[DriverHandle, _Session] = {}

        async def probe() -> DriverCapabilities:
            return await detect(self._environ, run, cloud_followup=cloud_followup)

        self._capabilities = CapabilityCache(probe)

    async def start(self, spec: StartSpec) -> DriverHandle:
        """Start ``claude`` for ``spec`` (no event before the first ``send``)."""
        cli = claude_path(self._environ)
        if cli is None:
            raise SessionsUnavailableError(NO_CLAUDE)
        queue: asyncio.Queue[DriverEvent] = asyncio.Queue()
        bridge = PermissionBridge(queue.put_nowait)
        options = sdk_options(
            spec,
            can_use_tool=bridge.can_use_tool,
            cli_path=cli,
            environ=self._environ,
            max_buffer_size=self._max_buffer_size,
        )
        client = self._client_factory(options)
        try:
            await client.connect()
            info = await client.get_server_info()
        except ClaudeSDKError as failed:
            with suppress(Exception):
                await client.disconnect()
            raise SessionsUnavailableError(NOT_STARTED) from failed
        session = _Session(client=client, bridge=bridge, queue=queue)
        pid = None if info is None else info.get("pid")
        session.pid = pid if isinstance(pid, int) and pid > 0 else None
        handle = DriverHandle(f"claude-{uuid.uuid4().hex}")
        self._sessions[handle] = session
        session.reader = asyncio.create_task(self._read(session))
        return handle

    async def send(self, handle: DriverHandle, text: str) -> None:
        """Send a user message; the CLI queues it behind a running turn."""
        session = self._open(handle)
        session.turns += 1
        try:
            await session.client.query(text)
        except CLIConnectionError as lost:
            session.turns -= 1
            raise SessionTerminalError(handle, status="ended") from lost

    async def interrupt(self, handle: DriverHandle) -> None:
        """End the running turn (its aborted result follows); nothing between turns."""
        session = self._open(handle)
        if session.turns == 0:
            return
        await session.client.interrupt()
        session.bridge.deny_all(INTERRUPTED)

    async def answer_permission(
        self, handle: DriverHandle, request_id: str, answer: DriverAnswer
    ) -> None:
        """Answer a parked permission request."""
        self._open(handle).bridge.answer(request_id, answer)

    async def set_mode(self, handle: DriverHandle, mode: PermissionMode) -> None:
        """Change the permission mode (``default``, ``acceptEdits`` or ``plan``)."""
        await self._open(handle).client.set_permission_mode(mode)

    async def set_model(self, handle: DriverHandle, model: str | None) -> None:
        """Change the model (None: the CLI's default)."""
        await self._open(handle).client.set_model(model)

    async def close(self, handle: DriverHandle) -> None:
        """Deny what is pending and end ``claude``; a second close waits for the first."""
        session = self._sessions[handle]
        if session.closing:
            await session.closed.wait()
            return
        session.closing = True
        try:
            if session.turns > 0 and not session.exited:
                with suppress(Exception):
                    await asyncio.wait_for(session.client.interrupt(), INTERRUPT_SECONDS)
            session.bridge.close()
            await self._disconnect(session)
            await self._finish_reader(session)
            session.emit(Exited(code=0))
        finally:
            session.closed.set()

    async def events(self, handle: DriverHandle) -> AsyncIterator[DriverEvent]:
        """The handle's events in order, ending after ``Exited``."""
        session = self._sessions[handle]
        while True:
            event = await session.queue.get()
            yield event
            if isinstance(event, Exited):
                return

    async def list_resumable(self, cwd: str) -> tuple[PastSession, ...]:
        """Past sessions of ``cwd``, newest first, at most 200."""
        return await list_resumable(cwd, lister=self._lister)

    async def capabilities(self) -> DriverCapabilities:
        """What this machine can do (cached 60 s)."""
        return await self._capabilities.get()

    def _open(self, handle: DriverHandle) -> _Session:
        session = self._sessions[handle]
        if session.closing or session.exited:
            raise SessionTerminalError(handle, status="ended")
        return session

    async def _read(self, session: _Session) -> None:
        failure = await self._pump(session, limit=self._max_buffer_size)
        if session.closing:
            return
        session.closing = True
        session.bridge.close()
        if failure is not None:
            session.emit(DriverError(message=failure[0]))
        await self._disconnect(session)
        session.emit(Exited(code=0 if failure is None else failure[1]))
        session.closed.set()

    @staticmethod
    async def _pump(session: _Session, *, limit: int) -> tuple[str, int] | None:
        """Map messages until the stream ends; the failure, when it broke on its own."""
        mapper = EventMapper()
        try:
            async for message in session.client.receive_messages():
                for event in mapper.to_events(message):
                    session.emit(event)
        except Exception as error:  # noqa: BLE001 - every broken stream ends the session
            return None if session.closing else _failure(error, limit=limit)
        return None

    async def _disconnect(self, session: _Session) -> None:
        disconnect = asyncio.ensure_future(session.client.disconnect())
        done, _ = await asyncio.wait({disconnect}, timeout=DISCONNECT_GRACE_SECONDS)
        if not done and session.pid is not None:
            await terminate(session.pid, grace=TERMINATE_GRACE_SECONDS)
        with suppress(Exception):
            await disconnect

    async def _finish_reader(self, session: _Session) -> None:
        reader = session.reader
        if reader is None or reader is asyncio.current_task():
            return
        done, _ = await asyncio.wait({reader}, timeout=READER_SECONDS)
        if not done:
            reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
