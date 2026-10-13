from collections.abc import Callable
from datetime import timedelta

import pytest

from agent_hub.core.agent_sessions.agent_session import (
    AgentSessionStatus,
    EndReason,
    SendMessage,
    SessionSettings,
)
from agent_hub.core.agent_sessions.control import AgentSessionCommands, AgentSessionControl
from agent_hub.core.agent_sessions.driver import (
    DriverCapabilities,
    PastSession,
    StartSpec,
    TextBlock,
    Thinking,
    ToolCall,
    ToolResult,
)
from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    InvalidWorkdirError,
    LiveLimitError,
    LogFullError,
    MessageTooLargeError,
    SessionLiveError,
    SessionsUnavailableError,
    SessionTerminalError,
    UnknownResumeError,
)
from agent_hub.core.agent_sessions.limits import KIB, SessionLimits
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
