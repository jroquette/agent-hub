"""The status machine of one agent session (P18), over driver events and commands.

Pure: ``apply`` folds one item (a ``DriverEvent`` or a command below) into a new
``SessionState``; ``refuse`` says whether a command may run at all, before the use case calls
the driver. The use case calls ``refuse`` then ``apply`` for each command, and ``apply`` alone
for each driver event.

- ``idle`` has no turn; ``running`` has one (a message sent, its result not yet in);
  ``waiting_permission`` holds exactly while at least one request is unanswered.
- ``ended`` and ``failed`` are terminal: ``apply`` leaves a terminal state as it is, and
  ``refuse`` raises ``SessionTerminalError`` for every command but ``Close`` (idempotent) and
  ``End``.
- ``Interrupt`` denies what is pending and marks the turn as ending: until its ``TurnResult``
  a message is refused with ``SessionBusyError`` (AC-165.17).
- Messages sent during a turn queue behind it (``turns`` counts them); a ``TurnResult`` ends
  one turn, and the session is ``idle`` once none is left.
- ``Exited`` ends a live session: ``failed`` unless the code is 0 (an unknown code is a
  failure, since nothing asked the process to stop).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.agent_sessions.agent_session import (
    TERMINAL_STATUSES,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.driver import DriverEvent, Exited, PermissionRequest, TurnResult
from agent_hub.core.agent_sessions.errors import (
    SessionBusyError,
    SessionTerminalError,
    UnknownPermissionError,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Send(_Frozen):
    """The owner sent a message: it starts a turn or queues behind the running one."""

    command: Literal["send"] = "send"


class Interrupt(_Frozen):
    """The owner interrupted the running turn (a no-op between turns)."""

    command: Literal["interrupt"] = "interrupt"


class Answer(_Frozen):
    """A permission request was answered (by the owner, a deadline or a plan approval)."""

    command: Literal["answer"] = "answer"
    request_id: str


class ChangeSettings(_Frozen):
    """The owner changed the mode or the model; the status does not move."""

    command: Literal["settings"] = "settings"


class Close(_Frozen):
    """The owner closed the session: ``ended``/``closed``, idempotent."""

    command: Literal["close"] = "close"


class End(_Frozen):
    """The server ended the session (idle timeout, log full, shutdown, a failure)."""

    command: Literal["end"] = "end"
    reason: EndReason


type SessionCommand = Send | Interrupt | Answer | ChangeSettings | Close | End
type SessionItem = DriverEvent | SessionCommand


class SessionState(_Frozen):
    """Where a session is: its status, the unanswered requests, the turns not yet ended, and
    whether an interrupt waits for its result."""

    status: AgentSessionStatus
    pending: frozenset[str] = frozenset()
    turns: int = Field(default=0, ge=0)
    interrupting: bool = False
    end_reason: EndReason | None = None

    @property
    def terminal(self) -> bool:
        """Whether the session has ended or failed."""
        return self.status in TERMINAL_STATUSES


def start_state(*, with_prompt: bool) -> SessionState:
    """A new session: ``running`` when created with a first prompt, else ``idle`` (E13)."""
    if with_prompt:
        return SessionState(status=AgentSessionStatus.RUNNING, turns=1)
    return SessionState(status=AgentSessionStatus.IDLE)


def refuse(state: SessionState, command: SessionCommand, *, agent_session_id: str) -> None:
    """Raise when ``command`` may not run now; return when it may.

    ``SessionTerminalError`` on a terminal session (all but ``Close`` and ``End``),
    ``SessionBusyError`` for a message while an interrupt waits for its result,
    ``UnknownPermissionError`` for an answer to a request that is not pending.
    """
    if isinstance(command, Close | End):
        return
    if state.terminal:
        raise SessionTerminalError(agent_session_id, status=state.status.value)
    if isinstance(command, Send) and state.interrupting:
        raise SessionBusyError(agent_session_id)
    if isinstance(command, Answer) and command.request_id not in state.pending:
        raise UnknownPermissionError(command.request_id)


def apply(state: SessionState, item: SessionItem) -> SessionState:
    """The state after ``item``; a terminal state never changes."""
    if state.terminal:
        return state
    if isinstance(item, Send | Interrupt | Answer | ChangeSettings | Close | End):
        return _after_command(state, item)
    return _after_event(state, item)


def _after_command(state: SessionState, command: SessionCommand) -> SessionState:
    match command:
        case Send():
            return _settled(state, turns=state.turns + 1)
        case Interrupt():
            if state.turns == 0 and not state.pending:
                return state
            return _settled(state, pending=frozenset(), interrupting=state.turns > 0)
        case Answer(request_id=request_id):
            return _settled(state, pending=state.pending - {request_id})
        case Close():
            return _ended(EndReason.CLOSED)
        case End(reason=reason):
            return _ended(reason)
        case ChangeSettings():
            return state


def _after_event(state: SessionState, event: DriverEvent) -> SessionState:
    match event:
        case PermissionRequest(request_id=request_id):
            return _settled(state, pending=state.pending | {request_id})
        case TurnResult():
            return _settled(
                state, turns=max(state.turns - 1, 0), pending=frozenset(), interrupting=False
            )
        case Exited(code=0):
            return _ended(EndReason.CLOSED)
        case Exited():
            return _ended(EndReason.FAILED)
        case _:
            return state


def _ended(reason: EndReason) -> SessionState:
    status = AgentSessionStatus.FAILED if reason == EndReason.FAILED else AgentSessionStatus.ENDED
    return SessionState(status=status, end_reason=reason)


def _settled(
    state: SessionState,
    *,
    pending: frozenset[str] | None = None,
    turns: int | None = None,
    interrupting: bool | None = None,
) -> SessionState:
    """A live state with its status derived from what is pending and the turns left."""
    pending = state.pending if pending is None else pending
    turns = state.turns if turns is None else turns
    interrupting = state.interrupting if interrupting is None else interrupting
    if pending:
        status = AgentSessionStatus.WAITING_PERMISSION
    elif turns > 0:
        status = AgentSessionStatus.RUNNING
    else:
        status = AgentSessionStatus.IDLE
    return SessionState(status=status, pending=pending, turns=turns, interrupting=interrupting)
