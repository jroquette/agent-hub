"""The Claude Agent SDK on Python 3.14 driving the stub ``claude`` via ``cli_path`` (S.1, AC-165.1).

Each test writes a synthetic scenario and a ``claude`` shim in ``tmp_path`` and points the SDK's
``cli_path`` at the shim, so the wheel's bundled binary never runs and nothing reaches the
network. The asyncio loop is run per test with ``asyncio.Runner``.
"""

import asyncio
import os
import signal
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    UserMessage,
)

from agent_hub.claude_sessions.testing.scenarios import (
    FORK_SESSION_ID,
    RECORD_ENV,
    SCENARIO_ENV,
    Scenario,
    StubRecord,
    held_turn,
    permission_turn,
    read_records,
    simple_turn,
    write_scenario,
    write_shim,
)

PARK_LIMIT_SECONDS = 600  # L3: a permission request waits up to 10 minutes for the browser
GRACE_SECONDS = 5


@dataclass
class Stub:
    """The files of one stub run: its shim, scenario and record."""

    shim: Path
    scenario: Path
    record: Path
    cwd: Path

    def options(self, **overrides: Any) -> ClaudeAgentOptions:
        values: dict[str, Any] = {
            "cli_path": str(self.shim),
            "cwd": str(self.cwd),
            "include_partial_messages": True,
            "permission_mode": "default",
            "env": {SCENARIO_ENV: str(self.scenario), RECORD_ENV: str(self.record)},
        }
        return ClaudeAgentOptions(**(values | overrides))

    def stream_start(self) -> StubRecord:
        """The record of the stream-json process (not the SDK's ``-v`` version probe)."""
        return next(
            r for r in read_records(self.record) if r.event == "start" and "-v" not in r.args
        )

    def spawn(self) -> StubRecord:
        return next(r for r in read_records(self.record) if r.event == "spawn")


def _stub(tmp_path: Path, scenario: Scenario) -> Stub:
    cwd = tmp_path / "work"
    cwd.mkdir()
    return Stub(
        shim=write_shim(tmp_path / "bin"),
        scenario=write_scenario(tmp_path, scenario),
        record=tmp_path / "record.jsonl",
        cwd=cwd,
    )


@dataclass
class Turn:
    """What one turn produced, by message type."""

    messages: list[Any] = field(default_factory=list)

    def of[T](self, kind: type[T]) -> list[T]:
        return [m for m in self.messages if isinstance(m, kind)]

    @property
    def result(self) -> ResultMessage:
        return self.of(ResultMessage)[-1]


async def _turn(
    client: ClaudeSDKClient, prompt: str, on_message: Callable[[Any], Awaitable[None]] | None = None
) -> Turn:
    await client.query(prompt)
    turn = Turn()
    async for message in client.receive_response():
        turn.messages.append(message)
        if on_message is not None:
            await on_message(message)
    return turn


@asynccontextmanager
async def _connected(options: ClaudeAgentOptions) -> AsyncIterator[ClaudeSDKClient]:
    client = ClaudeSDKClient(options)
    await client.connect()
    try:
        yield client
    finally:
        await client.disconnect()


def _alive(pid: int) -> bool:
    """Whether ``pid`` runs (a zombie counts as gone)."""
    stat = Path(f"/proc/{pid}/stat")
    if stat.parent.parent.exists() and Path("/proc/self").exists():
        if not stat.exists():
            return False
        return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _run[T](
    coroutine: Awaitable[T], loop_factory: Callable[[], asyncio.AbstractEventLoop] | None = None
) -> T:
    async def _main() -> T:
        return await coroutine

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(_main())


def test_streams_turn_when_sdk_drives_stub_on_python_three_fourteen(tmp_path: Path) -> None:
    stub = _stub(tmp_path, Scenario(turns=[simple_turn("Hello from the stub.")]))

    async def scenario() -> Turn:
        async with _connected(stub.options()) as client:
            return await _turn(client, "hi")

    turn = _run(scenario())

    assert sys.version_info >= (3, 14)
    init = turn.of(SystemMessage)[0]
    assert (init.subtype, init.data["session_id"], init.data["permissionMode"]) == (
        "init",
        Scenario().session_id,
        "default",
    )
    deltas = [e.event["delta"]["text"] for e in turn.of(StreamEvent)]
    assert "".join(deltas) == "Hello from the stub."
    assert len(deltas) == 2
    text = turn.of(AssistantMessage)[0].content[0]
    assert isinstance(text, TextBlock)
    assert text.text == "Hello from the stub."
    assert (turn.result.subtype, turn.result.terminal_reason) == ("success", "completed")
    assert turn.result.total_cost_usd == pytest.approx(0.0012)
    start = stub.stream_start()
    assert start.argv0 == str(stub.shim)
    assert "--include-partial-messages" in start.args
    assert start.args[-2:] == ["--input-format", "stream-json"]
    assert not any(arg.startswith("--setting-sources") for arg in start.args)


async def _no_op_hook(_input: Any, _tool_use_id: str | None, _context: Any) -> dict[str, Any]:
    return {}


@pytest.mark.parametrize("with_hook", [False, True], ids=["no_hook", "dummy_pre_tool_use_hook"])
def test_answers_permission_when_can_use_tool_parks(tmp_path: Path, *, with_hook: bool) -> None:
    stub = _stub(tmp_path, Scenario(turns=[permission_turn("npm run build")]))
    asked: list[tuple[str, dict[str, Any], ToolPermissionContext]] = []
    release = asyncio.Event()

    async def can_use_tool(name: str, data: dict[str, Any], context: ToolPermissionContext) -> Any:
        asked.append((name, data, context))
        await release.wait()
        return PermissionResultAllow(updated_permissions=context.suggestions)

    async def scenario() -> tuple[Turn, bool]:
        hooks = (
            {"PreToolUse": [HookMatcher(matcher=None, hooks=[_no_op_hook])]} if with_hook else None
        )
        options = stub.options(can_use_tool=can_use_tool, hooks=hooks)
        async with _connected(options) as client:
            pending = asyncio.create_task(_turn(client, "build it"))
            while not asked:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)
            still_parked = not pending.done()
            release.set()
            return await pending, still_parked

    turn, still_parked = _run(scenario())

    assert still_parked
    name, data, context = asked[0]
    assert (name, data["command"]) == ("Bash", "npm run build")
    assert context.tool_use_id == "toolu_stub_1"
    assert [s.to_dict()["destination"] for s in context.suggestions] == ["localSettings"]
    assert "--permission-prompt-tool" in stub.stream_start().args
    tool_result = turn.of(UserMessage)[0].content[0]
    assert (tool_result.content, tool_result.is_error) == ("ok", False)
    answer = next(r for r in read_records(stub.record) if r.subtype == "can_use_tool_answer")
    assert answer.data["behavior"] == "allow"
    assert answer.data["updatedPermissions"][0]["destination"] == "localSettings"
    assert turn.result.terminal_reason == "completed"


def test_sends_denial_when_can_use_tool_denies(tmp_path: Path) -> None:
    stub = _stub(tmp_path, Scenario(turns=[permission_turn()]))

    async def can_use_tool(
        _name: str, _data: dict[str, Any], _context: ToolPermissionContext
    ) -> Any:
        return PermissionResultDeny(message="Denied from the browser")

    async def scenario() -> Turn:
        async with _connected(stub.options(can_use_tool=can_use_tool)) as client:
            return await _turn(client, "build it")

    turn = _run(scenario())

    tool_result = turn.of(UserMessage)[0].content[0]
    assert (tool_result.content, tool_result.is_error) == ("Denied from the browser", True)


class _SkewedLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock a test can push forward, so every pending deadline fires."""

    skew = 0.0

    def time(self) -> float:
        return super().time() + self.skew


def test_waits_ten_minutes_when_permission_pending(tmp_path: Path) -> None:
    stub = _stub(tmp_path, Scenario(turns=[permission_turn()]))
    asked = asyncio.Event()
    release = asyncio.Event()

    async def can_use_tool(
        _name: str, _data: dict[str, Any], _context: ToolPermissionContext
    ) -> Any:
        asked.set()
        await release.wait()
        return PermissionResultAllow()

    async def scenario() -> Turn:
        loop = asyncio.get_running_loop()
        assert isinstance(loop, _SkewedLoop)
        async with _connected(stub.options(can_use_tool=can_use_tool)) as client:
            pending = asyncio.create_task(_turn(client, "build it"))
            await asyncio.wait_for(asked.wait(), timeout=10)
            loop.skew += PARK_LIMIT_SECONDS + 60
            await asyncio.sleep(0.5)
            assert not pending.done()
            release.set()
            return await pending

    turn = _run(scenario(), loop_factory=_SkewedLoop)

    assert (turn.result.subtype, turn.result.terminal_reason) == ("success", "completed")
    assert turn.of(UserMessage)[0].content[0].content == "ok"


def test_ends_turn_aborted_when_interrupted(tmp_path: Path) -> None:
    stub = _stub(tmp_path, Scenario(turns=[held_turn(), simple_turn("After the stop.")]))

    async def scenario() -> tuple[Turn, Turn]:
        async with _connected(stub.options()) as client:

            async def stop_on_first_delta(message: Any) -> None:
                if isinstance(message, StreamEvent):
                    await client.interrupt()

            stopped = await _turn(client, "long task", stop_on_first_delta)
            return stopped, await _turn(client, "next")

    stopped, following = _run(scenario())

    assert (stopped.result.subtype, stopped.result.terminal_reason) == (
        "error_during_execution",
        "aborted_streaming",
    )
    assert stopped.result.is_error
    assert following.result.terminal_reason == "completed"
    controls = [r.subtype for r in read_records(stub.record) if r.event == "control"]
    assert controls == ["initialize", "interrupt"]


@pytest.mark.parametrize(
    "case",
    [
        (
            {"resume": "22222222-2222-4222-8222-222222222222"},
            ["--resume=22222222-2222-4222-8222-222222222222"],
            "22222222-2222-4222-8222-222222222222",
        ),
        (
            {"resume": "22222222-2222-4222-8222-222222222222", "fork_session": True},
            ["--resume=22222222-2222-4222-8222-222222222222", "--fork-session"],
            FORK_SESSION_ID,
        ),
    ],
    ids=["resume", "fork"],
)
def test_passes_resume_and_fork_when_requested(
    tmp_path: Path, case: tuple[dict[str, Any], list[str], str]
) -> None:
    overrides, flags, session_id = case
    stub = _stub(tmp_path, Scenario(turns=[simple_turn()]))

    async def scenario() -> Turn:
        async with _connected(stub.options(**overrides)) as client:
            return await _turn(client, "continue")

    turn = _run(scenario())

    assert set(flags) <= set(stub.stream_start().args)
    assert turn.of(SystemMessage)[0].data["session_id"] == session_id
    assert turn.result.session_id == session_id


def test_passes_session_id_when_option_set(tmp_path: Path) -> None:
    session_id = "44444444-4444-4444-8444-444444444444"
    stub = _stub(tmp_path, Scenario(turns=[simple_turn()]))

    async def scenario() -> Turn:
        async with _connected(stub.options(session_id=session_id)) as client:
            return await _turn(client, "hi")

    turn = _run(scenario())

    assert f"--session-id={session_id}" in stub.stream_start().args
    assert turn.result.session_id == session_id


def test_maps_mode_and_model_when_changed_mid_session(tmp_path: Path) -> None:
    stub = _stub(tmp_path, Scenario(turns=[simple_turn()]))

    async def scenario() -> Turn:
        async with _connected(stub.options()) as client:
            await _turn(client, "one")
            await client.set_permission_mode("acceptEdits")
            await client.set_model("sonnet")
            return await _turn(client, "two")

    turn = _run(scenario())

    init = next(m for m in turn.of(SystemMessage) if m.subtype == "init")
    assert (init.data["permissionMode"], init.data["model"]) == ("acceptEdits", "sonnet")
    assert "--permission-mode" in stub.stream_start().args
    assert (
        stub.stream_start().args[stub.stream_start().args.index("--permission-mode") + 1]
        == "default"
    )


async def _disconnect_mid_turn(stub: Stub) -> float:
    """Start a held turn, disconnect while it runs, and return how long ``disconnect()`` took."""
    client = ClaudeSDKClient(stub.options())
    await client.connect()
    await client.query("long task")
    async for message in client.receive_messages():
        if isinstance(message, StreamEvent):
            break
    started = time.monotonic()
    await client.disconnect()
    return time.monotonic() - started


def _gone_within(pids: list[int], seconds: float) -> list[int]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    return [pid for pid in pids if _alive(pid)]


def test_leaves_no_process_when_disconnected(tmp_path: Path) -> None:
    scenario = Scenario(turns=[held_turn()], grandchild=True, linger_on_eof=True)
    stub = _stub(tmp_path, scenario)

    took = _run(_disconnect_mid_turn(stub))

    spawn = stub.spawn()
    assert spawn.grandchild_pid is not None
    assert _gone_within([spawn.pid, spawn.grandchild_pid], GRACE_SECONDS) == []
    # The SDK closes stdin, waits up to 5 s, then sends SIGTERM to the CLI (not its group).
    assert GRACE_SECONDS - 0.5 <= took < GRACE_SECONDS + 5


def test_keeps_grandchild_when_cli_leaves_it_on_exit(tmp_path: Path) -> None:
    scenario = Scenario(turns=[held_turn()], grandchild=True, reap_grandchild=False)
    stub = _stub(tmp_path, scenario)

    took = _run(_disconnect_mid_turn(stub))

    spawn = stub.spawn()
    assert spawn.grandchild_pid is not None
    try:
        assert _gone_within([spawn.pid], GRACE_SECONDS) == []
        assert _alive(spawn.grandchild_pid)
        assert took < GRACE_SECONDS
    finally:
        with suppress(ProcessLookupError):
            os.kill(spawn.grandchild_pid, signal.SIGKILL)
