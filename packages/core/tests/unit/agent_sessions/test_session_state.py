import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_hub.core.agent_sessions.agent_session import (
    TERMINAL_STATUSES,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.driver import (
    Exited,
    InitEvent,
    TextBlock,
    TextDelta,
    ToolCall,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import (
    SessionBusyError,
    SessionTerminalError,
    UnknownPermissionError,
)
from agent_hub.core.agent_sessions.session_state import (
    Answer,
    ChangeSettings,
    Close,
    End,
    Interrupt,
    Send,
    SessionItem,
    SessionState,
    apply,
    refuse,
    start_state,
)
from agent_hub.core.testing.read_model_builders import a_permission_request

SESSION_ID = "01929a4e-7a11-7c00-8a00-00000000d001"
RESULT = TurnResult(subtype="success")
ABORTED = TurnResult(subtype="error_during_execution", terminal_reason="aborted_streaming")


def _run(state: SessionState, *items: SessionItem) -> SessionState:
    for item in items:
        state = apply(state, item)
    return state


def test_starts_running_when_created_with_prompt() -> None:
    assert start_state(with_prompt=True).status == AgentSessionStatus.RUNNING
    assert start_state(with_prompt=False).status == AgentSessionStatus.IDLE


def test_returns_idle_when_turn_result_arrives() -> None:
    state = _run(
        start_state(with_prompt=True),
        InitEvent(session_id="5091b986-0000-4000-8000-0000000000d1"),
        TextDelta(block=0, index=0, text="Hel"),
        TextBlock(block=0, text="Hello"),
        RESULT,
    )

    assert state.status == AgentSessionStatus.IDLE
    assert state.turns == 0


def test_stays_running_when_queued_message_follows_result() -> None:
    state = _run(start_state(with_prompt=True), Send(), RESULT)

    assert state.status == AgentSessionStatus.RUNNING
    assert _run(state, RESULT).status == AgentSessionStatus.IDLE


def test_waits_permission_when_request_open_and_runs_when_answered() -> None:
    request = a_permission_request(request_id="req-1")
    state = _run(start_state(with_prompt=True), request)

    assert state.status == AgentSessionStatus.WAITING_PERMISSION
    assert state.pending == frozenset({"req-1"})
    answered = apply(state, Answer(request_id="req-1"))
    assert answered.status == AgentSessionStatus.RUNNING
    assert answered.pending == frozenset()


def test_refuses_answer_when_request_not_pending() -> None:
    state = start_state(with_prompt=True)

    with pytest.raises(UnknownPermissionError):
        refuse(state, Answer(request_id="req-9"), agent_session_id=SESSION_ID)


def test_denies_pending_and_waits_result_when_interrupted() -> None:
    state = _run(start_state(with_prompt=True), a_permission_request(request_id="req-1"))

    interrupted = apply(state, Interrupt())

    assert interrupted.pending == frozenset()
    assert interrupted.interrupting
    assert interrupted.status == AgentSessionStatus.RUNNING
    with pytest.raises(SessionBusyError):
        refuse(interrupted, Send(), agent_session_id=SESSION_ID)
    ended_turn = apply(interrupted, ABORTED)
    assert ended_turn.status == AgentSessionStatus.IDLE
    assert not ended_turn.interrupting
    refuse(ended_turn, Send(), agent_session_id=SESSION_ID)


def test_ignores_interrupt_when_idle() -> None:
    state = start_state(with_prompt=False)

    assert apply(state, Interrupt()) == state


def test_ends_closed_when_close_applied_and_close_is_idempotent() -> None:
    state = _run(start_state(with_prompt=True), a_permission_request())

    closed = apply(state, Close())

    assert (closed.status, closed.end_reason) == (AgentSessionStatus.ENDED, EndReason.CLOSED)
    assert closed.pending == frozenset()
    refuse(closed, Close(), agent_session_id=SESSION_ID)
    assert apply(closed, Close()) == closed


def test_fails_when_process_exits_non_zero() -> None:
    state = apply(start_state(with_prompt=True), Exited(code=1))

    assert (state.status, state.end_reason) == (AgentSessionStatus.FAILED, EndReason.FAILED)


def test_ends_closed_when_process_exits_zero() -> None:
    state = apply(start_state(with_prompt=False), Exited(code=0))

    assert (state.status, state.end_reason) == (AgentSessionStatus.ENDED, EndReason.CLOSED)


def test_ends_with_reason_when_server_ends_session() -> None:
    for reason, status in (
        (EndReason.IDLE_TIMEOUT, AgentSessionStatus.ENDED),
        (EndReason.LOG_FULL, AgentSessionStatus.ENDED),
        (EndReason.SERVER_STOPPED, AgentSessionStatus.ENDED),
        (EndReason.FAILED, AgentSessionStatus.FAILED),
    ):
        state = apply(start_state(with_prompt=True), End(reason=reason))
        assert (state.status, state.end_reason) == (status, reason)


def test_keeps_terminal_state_when_late_events_arrive() -> None:
    closed = apply(start_state(with_prompt=True), Close())

    assert _run(closed, RESULT, a_permission_request(), Exited(code=1)) == closed


def test_refuses_commands_when_terminal() -> None:
    closed = apply(start_state(with_prompt=False), Close())

    for command in (Send(), Interrupt(), Answer(request_id="req-1"), ChangeSettings()):
        with pytest.raises(SessionTerminalError):
            refuse(closed, command, agent_session_id=SESSION_ID)
        assert apply(closed, command) == closed


COMMANDS_REFUSED_WHEN_ENDED = (Send, Interrupt, Answer, ChangeSettings)
COMMANDS = (*COMMANDS_REFUSED_WHEN_ENDED, Close, End)
_REQUEST_IDS = ("req-1", "req-2", "req-3")


def _items() -> st.SearchStrategy[SessionItem]:
    events: list[st.SearchStrategy[SessionItem]] = [
        st.just(InitEvent(session_id="5091b986-0000-4000-8000-0000000000d1")),
        st.just(TextDelta(block=0, index=0, text="a")),
        st.just(TextBlock(block=0, text="a")),
        st.just(ToolCall(tool_use_id="tu-1", name="Bash", input={"command": "ls"})),
        st.sampled_from(_REQUEST_IDS).map(lambda rid: a_permission_request(request_id=rid)),
        st.sampled_from((RESULT, ABORTED)),
        st.builds(Exited, code=st.sampled_from((None, 0, 1))),
        st.just(Send()),
        st.just(Interrupt()),
        st.sampled_from(_REQUEST_IDS).map(lambda rid: Answer(request_id=rid)),
        st.just(ChangeSettings()),
        st.just(Close()),
        st.sampled_from(tuple(EndReason)).map(lambda reason: End(reason=reason)),
    ]
    return st.one_of(events)


def _step(state: SessionState, item: SessionItem) -> SessionState:
    """Apply ``item`` as the use case would: a refused command leaves the state unchanged."""
    if not isinstance(item, COMMANDS):
        return apply(state, item)
    try:
        refuse(state, item, agent_session_id=SESSION_ID)
    except SessionTerminalError:
        assert state.status in TERMINAL_STATUSES
        return state
    except SessionBusyError, UnknownPermissionError:
        return state
    return apply(state, item)


def _invariants_hold(before: SessionState, after: SessionState) -> None:
    assert after.status in set(AgentSessionStatus)
    if before.status in TERMINAL_STATUSES:
        assert after == before, "ended and failed are terminal"
    terminal = after.status in TERMINAL_STATUSES
    waiting = after.status == AgentSessionStatus.WAITING_PERMISSION
    assert waiting == (bool(after.pending) and not terminal), "waiting exactly while pending"
    assert (after.end_reason is not None) == terminal
    assert after.turns >= 0


@settings(max_examples=200, deadline=None)
@given(
    with_prompt=st.booleans(),
    items=st.lists(_items(), max_size=60),
)
def test_keeps_status_valid_when_sequences_generated_property(
    with_prompt: bool,  # noqa: FBT001 -- a generated value
    items: list[SessionItem],
) -> None:
    state = start_state(with_prompt=with_prompt)
    for item in items:
        if state.status in TERMINAL_STATUSES and isinstance(item, COMMANDS_REFUSED_WHEN_ENDED):
            with pytest.raises(SessionTerminalError):
                refuse(state, item, agent_session_id=SESSION_ID)
        after = _step(state, item)
        _invariants_hold(state, after)
        state = after
