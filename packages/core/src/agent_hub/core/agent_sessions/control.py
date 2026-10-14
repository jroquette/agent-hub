"""``AgentSessionCommands``, what the agent-session routes call, and ``AgentSessionControl``,
the use case that implements it (UC).

``AgentSessionControl`` owns the live sessions in ``hub web``'s event loop. For each one a pump
task reads the driver's events, folds them into the status machine (``session_state``) and
turns each into a log record: the raw copy goes to the session's subscribers in memory, the
redacted copy (``record_text.redacted``), admitted by the log budget (``log_caps``), to the store
(P8). Store calls run off the loop (``asyncio.to_thread``) under one lock per session, so
``seq`` order is emit order (P10). Text deltas never reach the store: they go to the delta ring
and the subscribers (S4, E8).

- Commands (``create``, ``send``, ``interrupt``, ``answer``, ``change_settings``, ``close``)
  log their audit record before they reach the driver, one at a time per session; a command
  on an ended session raises ``SessionTerminalError`` (``LogFullError`` after ``log_full``).
- A session ends once (``closed``, ``idle_timeout``, ``log_full``, ``server_stopped``,
  ``failed``): requests still open are denied ``by: closed``, a ``close`` record names the
  reason, the store row becomes final, then the driver is closed. The process's own exit ends
  it too (``failed`` with an ``error`` record when its code is not 0).
- No wall clock in here (P9): ``sweep(now)`` applies permission deadlines, idle timeouts and
  retention; the clock is injected.
- ``shutdown`` ends every live session ``server_stopped``, interrupting a running turn before
  the driver disconnects (P12), all in parallel and bounded.

Errors are the ``errors`` module's; the API maps each to a problem. Messages and records never
carry conversation text outside the log itself.
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Final, Protocol

from pydantic import JsonValue

from agent_hub.core.agent_sessions import record_text, subscription
from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionList,
    AgentSessionStatus,
    CreateAgentSession,
    EndReason,
    MessageAccepted,
    OpenPermission,
    PermissionDecision,
    ResumableList,
    SendMessage,
    SessionSettings,
    WorkdirList,
)
from agent_hub.core.agent_sessions.diff import OFF_LOOP_BYTES, edit_diff, write_diff
from agent_hub.core.agent_sessions.driver import (
    DriverCapabilities,
    DriverError,
    DriverEvent,
    Exited,
    InitEvent,
    PastSession,
    PermissionRequest,
    SessionDriver,
    StartSpec,
    TextDelta,
    ToolCall,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    LiveLimitError,
    LogFullError,
    MessageTooLargeError,
    PermissionAnsweredError,
    SessionLiveError,
    SessionsUnavailableError,
    SessionTerminalError,
    UnknownPermissionError,
    UnknownResumeError,
)
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.links import AgentSessionLink, ObservedSessionLookup
from agent_hub.core.agent_sessions.live_session import LiveSession, OpenRequest
from agent_hub.core.agent_sessions.log_caps import Full, Truncated
from agent_hub.core.agent_sessions.permission_policy import (
    closed_answer,
    deadline,
    expired,
    offered_suggestions,
    timeout_answer,
    validate,
)
from agent_hub.core.agent_sessions.records import (
    LogRecord,
    LogRecordPage,
    LogTruncatedBody,
    PermissionDecisionBody,
    PermissionRequestBody,
    RecordBy,
    RecordKind,
    SettingsBody,
    StatusFrame,
    StreamItem,
    StreamPosition,
    UserMessageBody,
)
from agent_hub.core.agent_sessions.session_state import (
    Answer,
    ChangeSettings,
    Close,
    End,
    Interrupt,
    Send,
    SessionCommand,
    SessionState,
    apply,
    refuse,
    start_state,
)
from agent_hub.core.agent_sessions.store import AgentSessionFields, AgentSessionStore
from agent_hub.core.agent_sessions.workdirs import WorkdirListing
from agent_hub.core.sessions.session import TokenUsage

# The workdirs of a project, listed now (``api/workdir_listing.py`` over the hub registry); it
# raises for an unknown project. Called off the loop.
type WorkdirSource = Callable[[str], WorkdirListing]

# The bounds of ending a session: the interrupt before the disconnect, the close itself, and
# how long a close waits for the driver's last events (``exited``) to be logged.
INTERRUPT_SECONDS: Final = 0.5
CLOSE_SECONDS: Final = 1.0
DRAIN_SECONDS: Final = 1.0
# Records the server writes while a session ends, and the driver's last ones: they use the
# log's headroom (E12).
_RESERVED_KINDS: Final = frozenset({"result", "exited"})
_STOPPING: Final = "hub web is stopping"


def _uuid7() -> str:
    return str(uuid.uuid7())


def _uuid4() -> str:
    return str(uuid.uuid4())


def _sum_usage(total: TokenUsage | None, more: TokenUsage | None) -> TokenUsage | None:
    if more is None:
        return total
    if total is None:
        return more
    return TokenUsage(
        input=total.input + more.input,
        output=total.output + more.output,
        cache_read=total.cache_read + more.cache_read,
        cache_write=total.cache_write + more.cache_write,
    )


def _sum_cost(total: Decimal | None, more: Decimal | None) -> Decimal | None:
    if more is None:
        return total
    return more if total is None else total + more


def _event_body(event: DriverEvent) -> dict[str, JsonValue]:
    body: dict[str, JsonValue] = event.model_dump(mode="json", exclude={"kind"})
    return body


def _tool_call_body(call: ToolCall) -> dict[str, JsonValue]:
    """The record of a tool call; an ``Edit`` or ``Write`` also carries its unified diff."""
    body = _event_body(call)
    path = call.input.get("file_path")
    if not isinstance(path, str):
        return body
    old, new, content = (call.input.get(key) for key in ("old_string", "new_string", "content"))
    if call.name == "Edit" and isinstance(old, str) and isinstance(new, str):
        body["diff"] = edit_diff(path, old, new)
    elif call.name == "Write" and isinstance(content, str):
        body["diff"] = write_diff(path, content)
    return body


def _diff_input_bytes(call: ToolCall) -> int:
    """The UTF-8 bytes a file tool's diff compares (0 for other tools)."""
    if call.name not in {"Edit", "Write"}:
        return 0
    texts = (call.input.get(key) for key in ("old_string", "new_string", "content"))
    return sum(len(text.encode()) for text in texts if isinstance(text, str))


async def _tool_call_record(call: ToolCall) -> dict[str, JsonValue]:
    """``_tool_call_body``, off the event loop when its diff compares a large input."""
    if _diff_input_bytes(call) > OFF_LOOP_BYTES:
        return await asyncio.to_thread(_tool_call_body, call)
    return _tool_call_body(call)


async def _bounded(step: Awaitable[None], seconds: float) -> None:
    """Run a driver step while a session ends; a failure or a hang never keeps it open."""
    try:
        async with asyncio.timeout(seconds):
            await step
    except Exception:  # noqa: BLE001 -- ending must go on whatever the driver does
        return


class AgentSessionCommands(Protocol):
    """Every agent-session use case the routes reach (S3, P5)."""

    async def workdirs(self, project: str) -> WorkdirList:
        """The folders a session of ``project`` may start in (D6)."""
        ...

    async def capabilities(self) -> DriverCapabilities:
        """Whether sessions can start here, and the cloud commands (S8)."""
        ...

    async def resumable(self, project: str, workdir_id: str) -> ResumableList:
        """Past Claude sessions of one workdir (D7)."""
        ...

    async def list_sessions(
        self, *, project: str | None, status: AgentSessionStatus | None
    ) -> AgentSessionList:
        """Local agent sessions, newest first."""
        ...

    async def create(self, request: CreateAgentSession) -> AgentSession:
        """Start a session (and send its first prompt): ``running`` with a prompt, else
        ``idle`` (E13)."""
        ...

    async def snapshot(self, agent_session_id: str) -> AgentSession:
        """One session, with its open permission request while live (E10)."""
        ...

    async def delete(self, agent_session_id: str) -> None:
        """Remove an ended session and its log (L4); a live one raises."""
        ...

    async def events(self, agent_session_id: str, *, after: int, limit: int) -> LogRecordPage:
        """A page of the persisted log after ``after``."""
        ...

    async def subscribe(
        self, agent_session_id: str, after: StreamPosition | None
    ) -> AsyncIterator[StreamItem]:
        """The stream from ``after`` (E8): stored records, ring deltas, then live frames.

        Awaiting it checks the session (and the subscriber cap) before any byte is sent.
        """
        ...

    async def send(self, agent_session_id: str, message: SendMessage) -> MessageAccepted:
        """Log and pass on a user message."""
        ...

    async def interrupt(self, agent_session_id: str) -> AgentSession:
        """Interrupt the running turn; its result follows on the stream."""
        ...

    async def answer(
        self, agent_session_id: str, request_id: str, decision: PermissionDecision
    ) -> AgentSession:
        """Answer an open permission request (once)."""
        ...

    async def change_settings(
        self, agent_session_id: str, settings: SessionSettings
    ) -> AgentSession:
        """Change the mode or model."""
        ...

    async def close(self, agent_session_id: str) -> AgentSession:
        """End the session (idempotent)."""
        ...


class AgentSessionControl:
    """The agent-session use case (UC); see the module docstring.

    ``workdirs`` lists a project's workdirs (raises for an unknown project); ``clock`` is the
    app's; ``environment_extra`` is added to each child's environment (``AGENT_HUB_WEB_URL``,
    never the access token, L5); ``new_id`` mints agent-session ids (UUIDv7) and
    ``new_claude_session_id`` the Claude session id given to a new session (P13);
    ``observed_sessions`` fills ``observed_session_id`` on the listed and read sessions (D2).
    """

    def __init__(  # noqa: PLR0913 -- the use case's ports and settings, all injected
        self,
        driver: SessionDriver,
        store: AgentSessionStore,
        *,
        workdirs: WorkdirSource,
        clock: Callable[[], datetime],
        limits: SessionLimits | None = None,
        environment_extra: Mapping[str, str] | None = None,
        new_id: Callable[[], str] = _uuid7,
        new_claude_session_id: Callable[[], str] = _uuid4,
        observed_sessions: ObservedSessionLookup | None = None,
    ) -> None:
        self._driver = driver
        self._store = store
        self._workdirs = workdirs
        self._clock = clock
        self._limits = limits or SessionLimits()
        self._environment_extra = dict(environment_extra or {})
        self._new_id = new_id
        self._new_claude_session_id = new_claude_session_id
        self._observed_sessions = observed_sessions
        self._live: dict[str, LiveSession] = {}
        self._pumps: set[asyncio.Task[None]] = set()
        self._admission = asyncio.Lock()
        self._stopping = False

    # Reads

    async def workdirs(self, project: str) -> WorkdirList:
        """The folders a session of ``project`` may start in (D6)."""
        return (await self._listing(project)).view()

    async def capabilities(self) -> DriverCapabilities:
        """Whether sessions can start here, and the cloud commands (S8)."""
        return await self._driver.capabilities()

    async def resumable(self, project: str, workdir_id: str) -> ResumableList:
        """Past Claude sessions of one workdir (D7)."""
        resolved = (await self._listing(project)).resolve(workdir_id)
        return ResumableList(items=await self._driver.list_resumable(resolved.path))

    async def list_sessions(
        self, *, project: str | None, status: AgentSessionStatus | None
    ) -> AgentSessionList:
        """Local agent sessions, newest first; a live one with its open request."""
        stored = await asyncio.to_thread(
            lambda: self._store.list(project=project, status=status, kind="local")
        )
        views = [self._view(session) for session in stored]
        return AgentSessionList(items=tuple(await self._with_twins(views)))

    async def snapshot(self, agent_session_id: str) -> AgentSession:
        """One session, with its open permission request while live (E10)."""
        live = self._live.get(agent_session_id)
        if live is not None:
            session = live.view()
        else:
            session = await asyncio.to_thread(self._store.get, agent_session_id)
        return (await self._with_twins([session]))[0]

    async def events(self, agent_session_id: str, *, after: int, limit: int) -> LogRecordPage:
        """A page of the persisted (redacted) log after ``after``."""
        session = await self.snapshot(agent_session_id)
        records = await asyncio.to_thread(
            lambda: self._store.records(agent_session_id, after=after, limit=limit)
        )
        more = len(records) == limit and records[-1].seq < session.last_seq
        return LogRecordPage(items=records, next_after=records[-1].seq if more else None)

    async def delete(self, agent_session_id: str) -> None:
        """Remove an ended session and its log (L4); a live one raises ``SessionLiveError``."""
        if agent_session_id in self._live:
            raise SessionLiveError(agent_session_id)
        await asyncio.to_thread(self._store.delete, agent_session_id)

    def live_link(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The live session driving ``claude_session_id`` in ``project`` and whether it waits
        on a permission (``AgentSessionLinks``' first look); safe to call from a thread."""
        for live in list(self._live.values()):
            session = live.session
            if session.project == project and session.claude_session_id == claude_session_id:
                waiting = live.state.status == AgentSessionStatus.WAITING_PERMISSION
                return AgentSessionLink(agent_session_id=session.id, waiting=waiting)
        return None

    # Commands

    async def create(self, request: CreateAgentSession) -> AgentSession:
        """Start a session in a listed workdir (and send its first prompt): ``running`` with a
        prompt, else ``idle`` (E13)."""
        prompt = request.prompt
        if prompt is not None:
            self._check_size(prompt)
        async with self._admission:
            await self._check_can_start()
            resolved = (await self._listing(request.project)).resolve(request.workdir_id)
            past = await self._resumed(request, resolved.path)
            minted = (
                None if request.resume_session_id is not None else self._new_claude_session_id()
            )
            claude_session_id = minted if not request.fork else None
            if request.resume_session_id is not None and not request.fork:
                claude_session_id = request.resume_session_id
            state = start_state(with_prompt=prompt is not None)
            now = self._clock()
            session = AgentSession(
                id=self._new_id(),
                project=request.project,
                workdir_id=request.workdir_id,
                workdir_label=resolved.workdir.label,
                claude_session_id=claude_session_id,
                status=state.status,
                mode=request.mode,
                model=request.model,
                title=record_text.title(prompt) if prompt else (past.title if past else None),
                created_at=now,
                updated_at=now,
            )
            await asyncio.to_thread(self._store.create, session)
            spec = StartSpec(
                cwd=resolved.path,
                mode=request.mode,
                model=request.model,
                resume=request.resume_session_id,
                fork=request.fork,
                session_id=minted,
                environment_extra=self._environment_extra,
            )
            live = await self._start(session, spec, state)
            try:
                await self._begin(live, prompt)
            except Exception:
                await self._fail_start(live)
                raise
        return live.view()

    async def _begin(self, live: LiveSession, prompt: str | None) -> None:
        """Log the first prompt, start the pump, then send the prompt."""
        if prompt is not None:
            await self._emit(live, "user.message", UserMessageBody(text=prompt).as_body(), by="web")
        pump = asyncio.create_task(self._pump(live), name=f"agent-session-{live.id}")
        live.pump = pump
        self._pumps.add(pump)
        pump.add_done_callback(self._pumps.discard)
        if prompt is not None:
            await self._driver.send(live.handle, prompt)

    async def _fail_start(self, live: LiveSession) -> None:
        """End a session whose first record or prompt failed ``failed``; the caller re-raises
        the first failure, so one while ending is only suppressed."""
        with contextlib.suppress(Exception):
            await asyncio.shield(self._ending(live, EndReason.FAILED, by="server"))

    async def subscribe(
        self, agent_session_id: str, after: StreamPosition | None
    ) -> AsyncIterator[StreamItem]:
        """The stream from ``after`` (``subscription.frames``; None: live frames only). The
        session is checked here, before any byte is sent; past the subscriber cap the oldest
        stream of the session ends with a reset."""
        live = self._live.get(agent_session_id)
        session = (
            live.view()
            if live is not None
            else await asyncio.to_thread(self._store.get, agent_session_id)
        )

        async def read(after_seq: int, limit: int) -> tuple[LogRecord, ...]:
            return await asyncio.to_thread(
                lambda: self._store.records(agent_session_id, after=after_seq, limit=limit)
            )

        return subscription.frames(session, after, live=live, read=read)

    async def send(self, agent_session_id: str, message: SendMessage) -> MessageAccepted:
        """Log a user message, then pass it on: it plays after the running turn."""
        live = await self._commandable(agent_session_id)
        self._check_size(message.text)
        async with live.commands:
            self._refuse(live, Send())
            seq = await self._emit(
                live, "user.message", UserMessageBody(text=message.text).as_body(), by="web"
            )
            if seq is None:
                raise await self._log_full(live)
            live.state = apply(live.state, Send())
            await self._sync(live)
            await self._driver.send(live.handle, message.text)
        return MessageAccepted(seq=seq)

    async def interrupt(self, agent_session_id: str) -> AgentSession:
        """Interrupt the running turn: open requests are denied ``by: closed``, then the
        ``interrupt`` record; the turn's result follows on the stream (AC-165.17)."""
        live = await self._commandable(agent_session_id)
        async with live.commands:
            self._refuse(live, Interrupt())
            if await self._emit(live, "interrupt", {}, by="web") is None:
                raise await self._log_full(live)
            for request_id in list(live.requests):
                await self._close_request(live, request_id)
            live.state = apply(live.state, Interrupt())
            await self._sync(live)
            await self._driver.interrupt(live.handle)
        return live.view()

    async def answer(
        self, agent_session_id: str, request_id: str, decision: PermissionDecision
    ) -> AgentSession:
        """Answer an open permission request once (E7): the decision is logged ``by: web``,
        then the driver gets it; a plan approval's ``mode`` follows as ``settings`` (E6)."""
        live = await self._commandable(agent_session_id)
        async with live.commands:
            if request_id in live.answered:
                raise PermissionAnsweredError(request_id)
            self._refuse(live, Answer(request_id=request_id))
            answer = validate(live.requests[request_id].request, decision)
            open_request = live.requests.pop(request_id)
            live.answered.add(request_id)
            live.state = apply(live.state, Answer(request_id=request_id))
            body = PermissionDecisionBody(
                request_id=request_id,
                decision=decision.decision,
                message=decision.message,
                answers=decision.answers,
                suggestion=decision.suggestion,
                mode=decision.mode,
            ).as_body()
            seq = await self._emit(live, "permission.decision", body, by="web")
            if seq is None:
                # The decision is not in the log, so it is not applied: the driver is denied
                # and the session's end logs the request as denied ``by: closed``.
                live.requests[request_id] = open_request
                with contextlib.suppress(PermissionAnsweredError, UnknownPermissionError):
                    await self._driver.answer_permission(live.handle, request_id, closed_answer())
                raise await self._log_full(live)
            # Stored before the driver goes on, as ``interrupt`` does: the turn's own status
            # writes then always come after this one.
            await self._sync(live)
            await self._driver.answer_permission(live.handle, request_id, answer)
            if decision.mode is not None:
                await self._driver.set_mode(live.handle, decision.mode)
                await self._emit(
                    live, "settings", SettingsBody(mode=decision.mode).as_body(), by="web"
                )
                await self._sync(live, {"mode": decision.mode})
        return live.view()

    async def change_settings(
        self, agent_session_id: str, settings: SessionSettings
    ) -> AgentSession:
        """Change the mode or the model, logged as ``settings``."""
        live = await self._commandable(agent_session_id)
        async with live.commands:
            self._refuse(live, ChangeSettings())
            body = SettingsBody(mode=settings.mode, model=settings.model).as_body()
            if await self._emit(live, "settings", body, by="web") is None:
                raise await self._log_full(live)
            fields: AgentSessionFields = {}
            if settings.mode is not None:
                await self._driver.set_mode(live.handle, settings.mode)
                fields["mode"] = settings.mode
            if settings.model is not None:
                await self._driver.set_model(live.handle, settings.model)
                fields["model"] = settings.model
            await self._sync(live, fields)
        return live.view()

    async def close(self, agent_session_id: str) -> AgentSession:
        """End the session ``closed`` (idempotent: an ended one is answered as it is)."""
        live = self._live.get(agent_session_id)
        if live is None:
            return await asyncio.to_thread(self._store.get, agent_session_id)
        await asyncio.shield(self._ending(live, EndReason.CLOSED, by="web"))
        await self._drain(live)
        return await asyncio.to_thread(self._store.get, agent_session_id)

    async def sweep(self, now: datetime | None = None, *, purge: bool = True) -> None:
        """Apply time (P9): deny requests past their deadline (``by: timeout``), end sessions
        idle past the idle timeout (``idle_timeout``) and, with ``purge``, remove sessions that
        ended more than the retention ago (AC-165.53)."""
        now = now or self._clock()
        for live in list(self._live.values()):
            if live.pump is not None and live.pump.done() and not live.ended:
                # The pump died without ending the session (cancelled): reclaim it.
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._ending(live, EndReason.FAILED, by="server"))
                continue
            for request_id, open_request in list(live.requests.items()):
                if expired(open_request.view, now):
                    await self._time_out(live, request_id)
            idle_since = live.idle_since
            idle = live.state.status == AgentSessionStatus.IDLE
            if idle and idle_since is not None and now - idle_since >= self._limits.idle:
                await asyncio.shield(self._ending(live, EndReason.IDLE_TIMEOUT, by="timeout"))
        if purge:
            cutoff = now - self._limits.retention
            await asyncio.to_thread(self._store.purge_ended_before, cutoff)

    async def shutdown(self) -> None:
        """End every live session ``server_stopped`` (P12), in parallel; no session starts
        after this."""
        self._stopping = True
        lives = list(self._live.values())
        ends = [self._ending(live, EndReason.SERVER_STOPPED, by="server") for live in lives]
        await asyncio.gather(*ends, return_exceptions=True)
        pumps = set(self._pumps)
        if pumps:
            _, late = await asyncio.wait(pumps, timeout=DRAIN_SECONDS)
            for pump in late:
                pump.cancel()

    # Starting

    async def _listing(self, project: str) -> WorkdirListing:
        return await asyncio.to_thread(self._workdirs, project)

    def _check_size(self, text: str) -> None:
        size = len(text.encode())
        if size > self._limits.message_max_bytes:
            raise MessageTooLargeError(size=size, limit=self._limits.message_max_bytes)

    async def _check_can_start(self) -> None:
        if self._stopping:
            raise SessionsUnavailableError(_STOPPING)
        capabilities = await self._driver.capabilities()
        if not capabilities.available:
            raise SessionsUnavailableError(capabilities.reason or "sessions cannot start here")
        if len(self._live) >= self._limits.sessions_max:
            raise LiveLimitError(limit=self._limits.sessions_max)

    async def _resumed(self, request: CreateAgentSession, cwd: str) -> PastSession | None:
        wanted = request.resume_session_id
        if wanted is None:
            return None
        for past in await self._driver.list_resumable(cwd):
            if past.session_id == wanted:
                return past
        raise UnknownResumeError(wanted)

    async def _start(
        self, session: AgentSession, spec: StartSpec, state: SessionState
    ) -> LiveSession:
        try:
            handle = await self._driver.start(spec)
        except Exception:
            now = self._clock()
            await asyncio.to_thread(
                lambda: self._store.update(
                    session.id,
                    status=AgentSessionStatus.FAILED,
                    end_reason=EndReason.FAILED,
                    ended_at=now,
                    updated_at=now,
                )
            )
            raise
        live = LiveSession(session=session, handle=handle, state=state, limits=self._limits)
        if state.status == AgentSessionStatus.IDLE:
            live.idle_since = session.created_at
        self._live[session.id] = live
        return live

    # Commands' checks

    async def _with_twins(self, sessions: list[AgentSession]) -> list[AgentSession]:
        """``sessions`` with ``observed_session_id`` set where the twin was observed; the
        lookup folds events, so it runs off the loop."""
        lookup = self._observed_sessions
        if lookup is None or all(item.claude_session_id is None for item in sessions):
            return sessions

        def twinned(session: AgentSession) -> AgentSession:
            claude_id = session.claude_session_id
            if claude_id is None or not lookup.is_observed(session.project, claude_id):
                return session
            return session.model_copy(update={"observed_session_id": claude_id})

        return await asyncio.to_thread(lambda: [twinned(session) for session in sessions])

    def _view(self, session: AgentSession) -> AgentSession:
        live = self._live.get(session.id)
        return session if live is None else live.view()

    async def _commandable(self, agent_session_id: str) -> LiveSession:
        """The live session a command acts on; an ended (or unknown) one raises."""
        live = self._live.get(agent_session_id)
        if live is not None and not live.ended:
            return live
        session = await asyncio.to_thread(self._store.get, agent_session_id)
        if session.end_reason == EndReason.LOG_FULL:
            raise LogFullError(agent_session_id)
        raise SessionTerminalError(agent_session_id, status=session.status.value)

    def _refuse(self, live: LiveSession, command: SessionCommand) -> None:
        if live.state.terminal and live.state.end_reason == EndReason.LOG_FULL:
            raise LogFullError(live.id)
        refuse(live.state, command, agent_session_id=live.id)

    async def _log_full(self, live: LiveSession) -> LogFullError:
        """Wait until the full session has ended; the error to raise."""
        if live.end_task is not None:
            await asyncio.shield(live.end_task)
        return LogFullError(live.id)

    # The log

    async def _emit(
        self,
        live: LiveSession,
        kind: RecordKind,
        body: dict[str, JsonValue],
        *,
        by: RecordBy,
        reserved: bool = False,
    ) -> int | None:
        """Store the redacted copy of a record and publish the raw one; its ``seq``, or None
        when the log is full (the session then ends ``log_full``)."""
        reserved = reserved or live.ended or kind in _RESERVED_KINDS
        async with live.emit_lock:
            now = self._clock()
            raw = LogRecord(seq=live.last_seq + 1, at=now, kind=kind, by=by, body=body)
            admission = live.budget.admit(
                record_text.redacted(raw, self._limits), reserved=reserved
            )
            if not isinstance(admission, Full):
                try:
                    await asyncio.to_thread(self._store.append, live.id, [admission.record])
                except AgentSessionNotFoundError:
                    if live.ended:  # deleted while its last records came in
                        return None
                    raise
                live.last_seq = raw.seq
                await live.publish(self._live_copy(raw, admission.record, admission))
                return raw.seq
        if not live.ended:
            self._ending(live, EndReason.LOG_FULL, by="server", full=admission)
        return None

    def _live_copy(self, raw: LogRecord, stored: LogRecord, admission: object) -> LogRecord:
        """The record subscribers see now: raw text, cut as the stored copy is (P8, E9)."""
        body = dict(raw.body)
        limits = self._limits
        if isinstance(admission, Truncated):
            content = body.get("content")
            text = content if isinstance(content, str) else record_text.compact_json(content)
            body |= {
                "content": record_text.clip_bytes(text, limits.tool_result_bytes),
                "truncated": True,
                "original_bytes": len(text.encode()),
            }
        message = body.get("message")
        if raw.kind == "error" and isinstance(message, str):
            body["message"] = record_text.clip_bytes(message, limits.error_bytes)
        return raw.model_copy(update={"body": body, "text_bytes": stored.text_bytes})

    async def _sync(self, live: LiveSession, fields: AgentSessionFields | None = None) -> None:
        """Store the session's status (and ``fields``); publish a status frame on a change.

        Writes of one session run one at a time (``sync_lock``) and each reads the state once it
        holds the lock, right before its store write: a write that waited never stores a state
        older than the one stored before it, and frames follow the stored order.
        """
        async with live.sync_lock:
            now = self._clock()
            state = live.state
            changed = state.status != live.session.status
            update: AgentSessionFields = {"status": state.status, "updated_at": now}
            if state.terminal:
                update |= {"end_reason": state.end_reason, "ended_at": now}
            update |= fields or {}
            if state.status != AgentSessionStatus.IDLE:
                live.idle_since = None
            elif changed or live.idle_since is None:
                live.idle_since = now
            live.session = await asyncio.to_thread(lambda: self._store.update(live.id, **update))
            if changed:
                await live.publish(StatusFrame(status=state.status, end_reason=state.end_reason))

    async def _close_request(self, live: LiveSession, request_id: str) -> None:
        """Deny an open request because the session closes or is interrupted (``by: closed``);
        the driver denies it itself."""
        live.requests.pop(request_id, None)
        live.answered.add(request_id)
        body = PermissionDecisionBody(request_id=request_id, decision="deny").as_body()
        body["message"] = closed_answer().message
        await self._emit(live, "permission.decision", body, by="closed", reserved=True)

    async def _time_out(self, live: LiveSession, request_id: str) -> None:
        """Deny a request nobody answered before its deadline (AC-165.28)."""
        async with live.commands:
            if live.ended or request_id not in live.requests:
                return
            live.requests.pop(request_id)
            live.answered.add(request_id)
            live.state = apply(live.state, Answer(request_id=request_id))
            answer = timeout_answer()
            body = PermissionDecisionBody(
                request_id=request_id, decision="deny", message=answer.message
            ).as_body()
            await self._emit(live, "permission.decision", body, by="timeout", reserved=True)
            await self._sync(live)  # before the driver goes on, as in ``answer``
            # The driver may have ended the request itself meanwhile.
            with contextlib.suppress(PermissionAnsweredError, UnknownPermissionError):
                await self._driver.answer_permission(live.handle, request_id, answer)

    # Ending

    def _ending(
        self, live: LiveSession, reason: EndReason, *, by: RecordBy, full: Full | None = None
    ) -> asyncio.Task[None]:
        """The task that ends the session (the first reason wins)."""
        if live.end_task is None:
            live.end_task = asyncio.create_task(self._end(live, reason, by=by, full=full))
        return live.end_task

    async def _end(
        self, live: LiveSession, reason: EndReason, *, by: RecordBy, full: Full | None
    ) -> None:
        live.ended = True
        self._live.pop(live.id, None)
        exited = by == "driver"
        running = live.state.turns > 0
        live.state = apply(
            live.state, Close() if reason == EndReason.CLOSED else End(reason=reason)
        )
        try:
            if full is not None:
                truncated = LogTruncatedBody(cap=full.cap, limit=full.limit).as_body()
                await self._emit(live, "log.truncated", truncated, by="server")
            for request_id in list(live.requests):
                await self._close_request(live, request_id)
            if running and not exited and reason != EndReason.CLOSED:
                await self._emit(live, "interrupt", {}, by="server")
                await _bounded(self._driver.interrupt(live.handle), INTERRUPT_SECONDS)
            if not exited:
                await self._emit(live, "close", {"reason": reason.value}, by=by)
            await self._sync(live)
        finally:
            # A store that fails while the session ends never keeps the CLI running.
            await _bounded(self._driver.close(live.handle), CLOSE_SECONDS)

    async def _drain(self, live: LiveSession) -> None:
        """Wait (bounded) until the driver's last events are logged."""
        if live.pump is not None and not live.pump.done():
            await asyncio.wait({live.pump}, timeout=DRAIN_SECONDS)

    # The pump

    async def _pump(self, live: LiveSession) -> None:
        try:
            async for event in self._driver.events(live.handle):
                await self._on_event(live, event)
            if not live.ended:
                await self._fail(live, "the session's events ended without an exit")
        except Exception as error:  # noqa: BLE001 -- a driver failure fails the session
            if not live.ended:
                await self._fail(live, f"the session's driver failed ({type(error).__name__})")
        finally:
            try:
                if live.end_task is not None:
                    with contextlib.suppress(Exception):  # the end's own failure is its caller's
                        await asyncio.shield(live.end_task)
            finally:
                await live.finish()

    async def _fail(self, live: LiveSession, message: str) -> None:
        """End the session ``failed`` first (so a store that fails cannot keep it live), then
        log the ``error``; a failure to log it is suppressed."""
        self._ending(live, EndReason.FAILED, by="server")
        with contextlib.suppress(Exception):
            await self._emit(live, "error", {"message": message}, by="server")

    async def _on_event(self, live: LiveSession, event: DriverEvent) -> None:
        match event:
            case TextDelta(block=block, text=text):
                async with live.emit_lock:
                    await live.publish(live.ring.push(live.last_seq, block, text))
            case InitEvent():
                await self._on_init(live, event)
            case PermissionRequest():
                await self._on_permission(live, event)
            case TurnResult():
                await self._on_result(live, event)
            case Exited(code=code):
                await self._on_exit(live, code)
            case ToolCall():
                await self._emit(live, "tool.call", await _tool_call_record(event), by="driver")
            case DriverError():
                live.error_logged = True
                await self._emit(live, "error", _event_body(event), by="driver")
            case _:
                await self._emit(live, event.kind, _event_body(event), by="driver")

    async def _on_init(self, live: LiveSession, event: InitEvent) -> None:
        await self._emit(live, "init", _event_body(event), by="driver")
        fields: AgentSessionFields = {"claude_session_id": event.session_id}
        if event.model is not None:
            fields["model"] = event.model
        if not live.ended:
            await self._sync(live, fields)

    async def _on_permission(self, live: LiveSession, request: PermissionRequest) -> None:
        # Only the suggestions "Always allow" may apply reach the records and the browser (A11).
        offered = offered_suggestions(request.suggestions)
        if offered != request.suggestions:
            request = request.model_copy(update={"suggestions": offered})
        now = self._clock()
        limit = self._limits.summary_bytes
        view = OpenPermission(
            request_id=request.request_id,
            tool=request.tool,
            request_kind=request.request_kind,
            summary=record_text.summary(request.tool, request.input, limit=limit),
            input=None if request.request_kind == "tool" else request.input,
            suggestions=request.suggestions,
            asked_at=now,
            deadline_at=deadline(now, self._limits),
        )
        if live.ended:
            return
        live.requests[request.request_id] = OpenRequest(request=request, view=view)
        live.state = apply(live.state, request)
        body = PermissionRequestBody(
            request_id=view.request_id,
            tool=view.tool,
            request_kind=view.request_kind,
            summary=view.summary,
            input=view.input,
            suggestions=view.suggestions,
        ).as_body()
        await self._emit(live, "permission.request", body, by="driver")
        await self._sync(live)

    async def _on_result(self, live: LiveSession, result: TurnResult) -> None:
        await self._emit(live, "result", _event_body(result), by="driver")
        for request_id in list(live.requests):  # the driver ended the turn with them
            live.requests.pop(request_id)
            live.answered.add(request_id)
        session = live.session
        fields: AgentSessionFields = {
            "cost_usd": _sum_cost(session.cost_usd, result.cost_usd),
            "usage": _sum_usage(session.usage, result.usage),
        }
        if live.ended:
            async with live.sync_lock:
                live.session = await asyncio.to_thread(
                    lambda: self._store.update(live.id, **fields)
                )
            return
        live.state = apply(live.state, result)
        await self._sync(live, fields)

    async def _on_exit(self, live: LiveSession, code: int | None) -> None:
        failed = code != 0
        if failed and not live.ended and not live.error_logged:
            message = f"claude exited with code {code}"
            await self._emit(live, "error", {"message": message}, by="server")
        await self._emit(live, "exited", {"code": code}, by="driver")
        if not live.ended:
            reason = EndReason.FAILED if failed else EndReason.CLOSED
            await self._ending(live, reason, by="driver")
