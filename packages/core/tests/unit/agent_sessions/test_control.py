from collections.abc import Callable
from datetime import timedelta

import pytest
from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import (
    AgentSessionStatus,
    EndReason,
    PermissionDecision,
    SendMessage,
    SessionSettings,
)
from agent_hub.core.agent_sessions.control import AgentSessionCommands, AgentSessionControl
from agent_hub.core.agent_sessions.driver import (
    Allow,
    Deny,
    DriverCapabilities,
    PastSession,
    PermissionRequest,
    PermissionSuggestion,
    StartSpec,
    TextBlock,
    Thinking,
    ToolCall,
    ToolResult,
)
from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    InvalidDecisionError,
    InvalidWorkdirError,
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
from agent_hub.core.agent_sessions.limits import KIB, SessionLimits
from agent_hub.core.agent_sessions.permission_policy import TIMEOUT_MESSAGE
from agent_hub.core.testing.agent_session_rig import HUB_PATH, START, WEB_URL, Rig
from agent_hub.core.testing.session_driver_fakes import Hold, InMemorySessionDriver

type MakeRig = Callable[..., Rig]

pytestmark = pytest.mark.anyio

PAST = PastSession(
    session_id="11111111-2222-4333-8444-555555555555",
    title="Fix the flaky test",
    last_activity=START - timedelta(days=1),
    cwd=HUB_PATH,
)
GITHUB_TOKEN = "ghp_" + "Ab1" * 12


def _start_spec(driver: InMemorySessionDriver, number: int = 0) -> StartSpec:
    starts = [call.args[0] for call in driver.calls if call.method == "start"]
    spec = starts[number]
    assert isinstance(spec, StartSpec)
    return spec


async def test_implements_agent_session_commands_when_built(make_rig: MakeRig) -> None:
    control: AgentSessionCommands = make_rig().control

    assert isinstance(control, AgentSessionControl)


async def test_logs_message_then_init_when_created_with_prompt(make_rig: MakeRig) -> None:
    rig = make_rig()

    created = await rig.create("Say hello.", mode="plan", model="sonnet")
    ended_turn = await rig.until_status(created.id, "idle")

    assert created.status == AgentSessionStatus.RUNNING
    assert rig.kinds(created.id) == ["user.message", "init", "text", "result"]
    assert [record.seq for record in rig.records(created.id)] == [1, 2, 3, 4]
    assert rig.records(created.id)[0].by == "web"
    spec = _start_spec(rig.driver)
    assert (spec.cwd, spec.mode, spec.model) == (HUB_PATH, "plan", "sonnet")
    assert spec.environment_extra == {"AGENT_HUB_WEB_URL": WEB_URL}
    assert spec.session_id is not None
    assert ended_turn.claude_session_id == spec.session_id
    assert ended_turn.cost_usd is not None
    assert ended_turn.usage is not None
    assert ended_turn.title == "Say hello."
    assert ended_turn.last_seq == 4


async def test_starts_idle_without_init_when_created_without_prompt(make_rig: MakeRig) -> None:
    rig = make_rig()

    created = await rig.create()

    assert created.status == AgentSessionStatus.IDLE
    assert rig.kinds(created.id) == []
    assert [call.method for call in rig.driver.calls] == ["capabilities", "start"]


async def test_refuses_third_when_limit_two(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(sessions_max=2))
    first = await rig.create()
    await rig.create()

    with pytest.raises(LiveLimitError) as refused:
        await rig.create()
    await rig.control.close(first.id)
    third = await rig.create()

    assert refused.value.limit == 2
    assert third.status == AgentSessionStatus.IDLE


async def test_refuses_create_when_workdir_not_listed(make_rig: MakeRig) -> None:
    rig = make_rig()

    with pytest.raises(InvalidWorkdirError):
        await rig.create(workdir_id="0123456789abcdef")

    assert [call.method for call in rig.driver.calls if call.method == "start"] == []
    assert rig.store.list() == ()


async def test_refuses_create_when_prompt_over_byte_limit(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(message_max_bytes=KIB))

    with pytest.raises(MessageTooLargeError):
        await rig.create("é" * 600)

    assert rig.store.list() == ()


async def test_refuses_create_when_sessions_unavailable(make_rig: MakeRig) -> None:
    driver = InMemorySessionDriver(
        capabilities=DriverCapabilities(available=False, reason="claude is not on PATH")
    )
    rig = make_rig(driver=driver)

    with pytest.raises(SessionsUnavailableError) as refused:
        await rig.create("Say hello.")

    assert refused.value.reason == "claude is not on PATH"
    assert rig.store.list() == ()


async def test_resumes_session_when_listed_for_workdir(make_rig: MakeRig) -> None:
    rig = make_rig(past_sessions=(PAST,))

    resumed = await rig.create(resume_session_id=PAST.session_id)
    forked = await rig.create("Go on.", resume_session_id=PAST.session_id, fork=True)
    await rig.until_status(forked.id, "idle")

    first, second = _start_spec(rig.driver, 0), _start_spec(rig.driver, 1)
    assert (first.resume, first.fork, first.session_id) == (PAST.session_id, False, None)
    assert (second.resume, second.fork) == (PAST.session_id, True)
    assert resumed.claude_session_id == PAST.session_id
    assert resumed.title == PAST.title
    assert rig.store.get(forked.id).claude_session_id not in {None, PAST.session_id}


async def test_refuses_resume_when_not_listed(make_rig: MakeRig) -> None:
    rig = make_rig(past_sessions=(PAST,))

    with pytest.raises(UnknownResumeError):
        await rig.create(resume_session_id="99999999-2222-4333-8444-555555555555")


async def test_logs_message_in_order_when_sent_during_turn(make_rig: MakeRig) -> None:
    rig = make_rig(replies={"Work slowly.": (Hold(), TextBlock(block=0, text="done"))})
    created = await rig.create("Work slowly.")
    await rig.until(lambda: "init" in rig.kinds(created.id))

    accepted = await rig.control.send(created.id, SendMessage(text="And then this."))
    rig.driver.release(rig.handle())
    await rig.until(lambda: rig.kinds(created.id).count("result") == 2)

    assert accepted.seq == 3
    assert rig.kinds(created.id)[:3] == ["user.message", "init", "user.message"]
    sent = [call.args[0] for call in rig.driver.calls if call.method == "send"]
    assert sent == ["Work slowly.", "And then this."]
    assert rig.store.get(created.id).status == AgentSessionStatus.IDLE


async def test_refuses_message_when_over_byte_limit(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(message_max_bytes=KIB))
    created = await rig.create()

    with pytest.raises(MessageTooLargeError) as refused:
        await rig.control.send(created.id, SendMessage(text="x" * (KIB + 1)))

    assert (refused.value.size, refused.value.limit) == (KIB + 1, KIB)
    assert rig.kinds(created.id) == []


async def test_logs_interrupt_then_result_when_interrupted(make_rig: MakeRig) -> None:
    rig = make_rig(replies={"Work slowly.": (TextBlock(block=0, text="working"), Hold())})
    created = await rig.create("Work slowly.")
    await rig.until(lambda: "text" in rig.kinds(created.id))

    await rig.control.interrupt(created.id)
    await rig.until_status(created.id, "idle")
    await rig.control.send(created.id, SendMessage(text="Next."))
    await rig.until(lambda: rig.kinds(created.id).count("result") == 2)

    kinds = rig.kinds(created.id)
    assert kinds[:6] == ["user.message", "init", "text", "interrupt", "result", "user.message"]
    assert rig.records(created.id)[4].body["terminal_reason"] == "aborted_streaming"
    assert [call.method for call in rig.driver.calls].count("interrupt") == 1


async def test_logs_settings_when_mode_and_model_changed(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create()

    await rig.control.change_settings(created.id, SessionSettings(mode="plan"))
    await rig.control.change_settings(created.id, SessionSettings(mode="acceptEdits"))
    changed = await rig.control.change_settings(created.id, SessionSettings(model="opus"))

    assert (changed.mode, changed.model) == ("acceptEdits", "opus")
    assert [record.body for record in rig.records(created.id)] == [
        {"mode": "plan"},
        {"mode": "acceptEdits"},
        {"model": "opus"},
    ]
    calls = [(call.method, call.args) for call in rig.driver.calls if call.method.startswith("set")]
    assert calls == [
        ("set_mode", ("plan",)),
        ("set_mode", ("acceptEdits",)),
        ("set_model", ("opus",)),
    ]


async def test_closes_once_when_closed_twice(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create("Say hello.")
    await rig.until_status(created.id, "idle")

    closed = await rig.control.close(created.id)
    again = await rig.control.close(created.id)

    assert (closed.status, closed.end_reason) == (AgentSessionStatus.ENDED, EndReason.CLOSED)
    assert closed.ended_at == START
    assert again == rig.store.get(created.id)
    assert [call.method for call in rig.driver.calls].count("close") == 1
    assert rig.kinds(created.id)[-2:] == ["close", "exited"]
    with pytest.raises(SessionTerminalError):
        await rig.control.send(created.id, SendMessage(text="More?"))


async def test_fails_session_when_driver_exits_non_zero(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create()

    rig.driver.fail_with(rig.handle(), 3, "claude crashed")
    failed = await rig.until_status(created.id, "failed")

    assert failed.end_reason == EndReason.FAILED
    assert rig.kinds(created.id) == ["error", "exited"]
    assert rig.records(created.id)[1].body == {"code": 3}
    assert await rig.create() is not None


async def test_logs_error_when_exit_non_zero_without_message(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create()

    rig.driver.fail_with(rig.handle(), 9, "")
    await rig.until_status(created.id, "failed")

    assert rig.kinds(created.id) == ["error", "exited"]


async def test_ends_log_full_when_cap_reached(make_rig: MakeRig) -> None:
    turn = tuple(Thinking(text=f"step {number}") for number in range(120))
    limits = SessionLimits(log_records=100, log_bytes=64 * KIB, headroom=16)
    rig = make_rig(replies={"Think a lot.": turn}, limits=limits)
    created = await rig.create("Think a lot.")

    ended = await rig.until_status(created.id, "ended")
    await rig.until(lambda: "exited" in rig.kinds(created.id))

    assert ended.end_reason == EndReason.LOG_FULL
    kinds = rig.kinds(created.id)
    assert len(kinds) <= 100
    assert kinds.count("thinking") == 100 - 16 - 2
    assert "log.truncated" in kinds
    assert rig.records(created.id)[kinds.index("log.truncated")].body == {
        "cap": "records",
        "limit": 100,
    }
    with pytest.raises(LogFullError):
        await rig.control.send(created.id, SendMessage(text="More?"))


async def test_truncates_tool_result_when_over_limit(make_rig: MakeRig) -> None:
    content = "x" * (70 * KIB)
    turn = (
        ToolCall(tool_use_id="toolu_1", name="Read", input={"file_path": "big.txt"}),
        ToolResult(tool_use_id="toolu_1", content=content),
    )
    rig = make_rig(replies={"Read it.": turn})
    created = await rig.create("Read it.")
    await rig.until_status(created.id, "idle")

    stored = next(r for r in rig.records(created.id) if r.kind == "tool.result")

    assert stored.body["truncated"] is True
    assert stored.body["original_bytes"] == 70 * KIB


async def test_adds_diff_when_edit_called(make_rig: MakeRig) -> None:
    edit = ToolCall(
        tool_use_id="toolu_1",
        name="Edit",
        input={"file_path": "src/app.py", "old_string": "a = 1\n", "new_string": "a = 2\n"},
    )
    rig = make_rig(replies={"Edit it.": (edit,)})
    created = await rig.create("Edit it.")
    await rig.until_status(created.id, "idle")

    call = next(r for r in rig.records(created.id) if r.kind == "tool.call")

    assert call.body["diff"] == "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-a = 1\n+a = 2\n"


async def test_redacts_stored_copy_when_text_holds_token(make_rig: MakeRig) -> None:
    rig = make_rig(replies={"Show it.": (TextBlock(block=0, text=f"token {GITHUB_TOKEN}"),)})
    created = await rig.create("Show it.")
    await rig.until_status(created.id, "idle")

    text = next(r for r in rig.records(created.id) if r.kind == "text")

    assert GITHUB_TOKEN not in str(text.body)
    assert "[redacted" in str(text.body)


async def test_deletes_session_when_ended(make_rig: MakeRig) -> None:
    rig = make_rig()
    created = await rig.create()

    with pytest.raises(SessionLiveError):
        await rig.control.delete(created.id)
    await rig.control.close(created.id)
    await rig.control.delete(created.id)

    with pytest.raises(AgentSessionNotFoundError):
        await rig.control.snapshot(created.id)


async def test_lists_sessions_and_pages_events_when_read(make_rig: MakeRig) -> None:
    rig = make_rig()
    first = await rig.create("Say hello.")
    await rig.until_status(first.id, "idle")
    rig.clock.advance(1)
    second = await rig.create()

    listed = await rig.control.list_sessions(project="demo", status=None)
    idle = await rig.control.list_sessions(project=None, status=AgentSessionStatus.IDLE)
    page = await rig.control.events(first.id, after=1, limit=2)
    last = await rig.control.events(first.id, after=3, limit=2)

    assert [item.id for item in listed.items] == [second.id, first.id]
    assert {item.id for item in idle.items} == {first.id, second.id}
    assert [record.seq for record in page.items] == [2, 3]
    assert page.next_after == 3
    assert ([record.seq for record in last.items], last.next_after) == ([4], None)


async def test_lists_workdirs_resumable_and_capabilities_when_asked(make_rig: MakeRig) -> None:
    rig = make_rig(past_sessions=(PAST,))

    workdirs = await rig.control.workdirs("demo")
    resumable = await rig.control.resumable("demo", workdirs.items[0].workdir_id)
    capabilities = await rig.control.capabilities()

    assert [item.label for item in workdirs.items] == ["demo-hub"]
    assert resumable.items == (PAST,)
    assert capabilities.available is True


# Permissions and time (UC.2)

ASK = PermissionRequest(
    request_id="req-1",
    tool="Bash",
    input={"command": f"curl -H 'token: {GITHUB_TOKEN}' https://example.test"},
    suggestions=(
        PermissionSuggestion(index=0, destination="localSettings", rule={"tool": "Bash"}),
        PermissionSuggestion(index=1, destination="session", rule={"tool": "Bash"}),
    ),
)


async def _waiting(make_rig: MakeRig, request: PermissionRequest = ASK, **options: object) -> Rig:
    rig = make_rig(replies={"Ask first.": (request, TextBlock(block=0, text="done"))}, **options)
    created = await rig.create("Ask first.")
    await rig.until_status(created.id, "waiting_permission")
    return rig


def _decisions(rig: Rig) -> list[tuple[str | None, JsonValue]]:
    records = rig.records(rig.created[0].id)
    return [(r.by, r.body.get("decision")) for r in records if r.kind == "permission.decision"]


async def test_keeps_raw_open_request_and_stores_redacted_when_permission_requested(
    make_rig: MakeRig,
) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id

    snapshot = await rig.control.snapshot(session_id)
    stored = next(r for r in rig.records(session_id) if r.kind == "permission.request")

    assert snapshot.status == AgentSessionStatus.WAITING_PERMISSION
    assert snapshot.open_permission is not None
    assert GITHUB_TOKEN in snapshot.open_permission.summary
    assert snapshot.open_permission.deadline_at == START + timedelta(minutes=10)
    assert GITHUB_TOKEN not in str(stored.body)
    assert stored.body["request_id"] == "req-1"
    assert len(stored.body["suggestions"]) == 2  # type: ignore[arg-type]


async def test_allows_once_when_permission_answer_allow(make_rig: MakeRig) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id

    answered = await rig.control.answer(session_id, "req-1", PermissionDecision(decision="allow"))
    await rig.until_status(session_id, "idle")

    assert answered.open_permission is None
    assert rig.driver.answers == {"req-1": Allow()}
    assert _decisions(rig) == [("web", "allow")]
    assert rig.kinds(session_id)[-3:] == ["permission.decision", "text", "result"]


async def test_allows_local_suggestion_when_permission_answer_always(make_rig: MakeRig) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id

    with pytest.raises(InvalidDecisionError):
        await rig.control.answer(
            session_id, "req-1", PermissionDecision(decision="always", suggestion=1)
        )
    await rig.control.answer(
        session_id, "req-1", PermissionDecision(decision="always", suggestion=0)
    )

    assert rig.driver.answers == {"req-1": Allow(updated_permissions=(ASK.suggestions[0],))}
    assert _decisions(rig) == [("web", "always")]


async def test_refuses_second_permission_answer_when_already_answered(make_rig: MakeRig) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id
    await rig.control.answer(
        session_id, "req-1", PermissionDecision(decision="deny", message="not now")
    )

    with pytest.raises(PermissionAnsweredError):
        await rig.control.answer(session_id, "req-1", PermissionDecision(decision="allow"))
    with pytest.raises(UnknownPermissionError):
        await rig.control.answer(session_id, "req-9", PermissionDecision(decision="allow"))

    assert rig.driver.answers == {"req-1": Deny(message="not now")}


async def test_passes_answers_when_ask_user_question_answered(make_rig: MakeRig) -> None:
    question = PermissionRequest(
        request_id="req-q",
        tool="AskUserQuestion",
        input={"questions": [{"question": "Which runner?"}]},
        request_kind="ask_user_question",
    )
    rig = await _waiting(make_rig, question)
    session_id = rig.created[0].id
    snapshot = await rig.control.snapshot(session_id)

    await rig.control.answer(
        session_id,
        "req-q",
        PermissionDecision(decision="allow", answers={"Which runner?": "pytest"}),
    )

    assert snapshot.open_permission is not None
    assert snapshot.open_permission.input == question.input
    assert rig.driver.answers["req-q"] == Allow(
        updated_input=question.input | {"answers": {"Which runner?": "pytest"}}
    )
    decision = next(r for r in rig.records(session_id) if r.kind == "permission.decision")
    assert decision.body["answers"] == {"Which runner?": "pytest"}


async def test_allows_then_sets_mode_when_plan_approval_answered(make_rig: MakeRig) -> None:
    plan = PermissionRequest(
        request_id="req-p",
        tool="ExitPlanMode",
        input={"plan": "1. Fix the test"},
        request_kind="plan_approval",
    )
    rig = await _waiting(
        make_rig,
        plan,
    )
    session_id = rig.created[0].id

    approved = await rig.control.answer(
        session_id, "req-p", PermissionDecision(decision="allow", mode="acceptEdits")
    )

    assert rig.driver.answers["req-p"] == Allow()
    methods = [call.method for call in rig.driver.calls]
    assert methods.index("answer_permission") < methods.index("set_mode")
    assert rig.kinds(session_id)[3:5] == ["permission.decision", "settings"]
    assert rig.records(session_id)[4].body == {"mode": "acceptEdits"}
    assert approved.mode == "acceptEdits"


async def test_denies_by_timeout_when_deadline_passes(make_rig: MakeRig) -> None:
    rig = await _waiting(make_rig, limits=SessionLimits(permission_timeout_seconds=1))
    session_id = rig.created[0].id

    await rig.control.sweep(rig.clock.advance(0.5))
    still = await rig.control.snapshot(session_id)
    await rig.control.sweep(rig.clock.advance(0.5))
    await rig.until_status(session_id, "idle")

    assert still.open_permission is not None
    assert rig.driver.answers == {"req-1": Deny(message=TIMEOUT_MESSAGE)}
    assert _decisions(rig) == [("timeout", "deny")]


async def test_records_closed_when_session_closed_with_pending_permission_timeout(
    make_rig: MakeRig,
) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id

    closed = await rig.control.close(session_id)

    assert closed.status == AgentSessionStatus.ENDED
    assert _decisions(rig) == [("closed", "deny")]
    assert rig.kinds(session_id)[-3:] == ["permission.decision", "close", "exited"]


async def test_denies_pending_by_closed_when_interrupted(make_rig: MakeRig) -> None:
    rig = await _waiting(make_rig)
    session_id = rig.created[0].id

    await rig.control.interrupt(session_id)
    await rig.until_status(session_id, "idle")

    assert _decisions(rig) == [("closed", "deny")]
    assert rig.kinds(session_id)[3:6] == ["interrupt", "permission.decision", "result"]


async def test_ends_idle_timeout_when_idle_past_limit(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(idle_seconds=2))
    created = await rig.create("Say hello.")
    await rig.until_status(created.id, "idle")

    await rig.control.sweep(rig.clock.advance(1))
    still = await rig.control.snapshot(created.id)
    await rig.control.sweep(rig.clock.advance(1))
    ended = await rig.until_status(created.id, "ended")
    await rig.until(lambda: "exited" in rig.kinds(created.id))

    assert still.status == AgentSessionStatus.IDLE
    assert ended.end_reason == EndReason.IDLE_TIMEOUT
    close = next(r for r in rig.records(created.id) if r.kind == "close")
    assert (close.by, close.body) == ("timeout", {"reason": "idle_timeout"})
    assert len(rig.records(created.id)) == 6


async def test_keeps_running_session_when_idle_limit_passes(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(idle_seconds=2), replies={"Work.": (Hold(),)})
    created = await rig.create("Work.")

    await rig.control.sweep(rig.clock.advance(60))

    assert (await rig.control.snapshot(created.id)).status == AgentSessionStatus.RUNNING


async def test_purges_ended_after_retention_when_swept(make_rig: MakeRig) -> None:
    rig = make_rig(limits=SessionLimits(retention_days=30, idle_seconds=86_400))
    old = await rig.create()
    await rig.control.close(old.id)
    rig.clock.advance(timedelta(days=29).total_seconds())
    recent = await rig.create()
    await rig.control.close(recent.id)
    live = await rig.create()

    await rig.control.sweep(rig.clock.advance(timedelta(days=1, seconds=1).total_seconds()))

    assert {session.id for session in rig.store.list()} == {recent.id, live.id}


async def test_ends_server_stopped_when_shutdown(make_rig: MakeRig) -> None:
    rig = make_rig(replies={"Work.": (TextBlock(block=0, text="working"), Hold())})
    working = await rig.create("Work.")
    idle = await rig.create()
    await rig.until(lambda: "text" in rig.kinds(working.id))

    await rig.control.shutdown()

    for session_id in (working.id, idle.id):
        stopped = rig.store.get(session_id)
        assert (stopped.status, stopped.end_reason) == (
            AgentSessionStatus.ENDED,
            EndReason.SERVER_STOPPED,
        )
    assert rig.kinds(working.id)[3:5] == ["interrupt", "close"]
    assert rig.kinds(idle.id) == ["close", "exited"]
    calls = [(call.method, call.handle) for call in rig.driver.calls]
    assert calls.index(("interrupt", rig.handle(1))) < calls.index(("close", rig.handle(1)))
    with pytest.raises(SessionsUnavailableError):
        await rig.create()
