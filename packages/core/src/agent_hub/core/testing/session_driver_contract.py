"""The ``SessionDriver`` contract suite (AC-165.2): the fake and every engine honour it.

An implementation's ``tests/contract/`` provides two fixtures, ``scenario`` (a
``ContractScenario``, usually ``contract_scenario()``) and ``session_driver`` (a driver that
plays that scenario's ``replies``: the fake takes them as they are, an engine's stub CLI is
scripted from them), and declares::

    class TestMyDriver(SessionDriverContract):
        pytestmark = pytest.mark.anyio

The tests are coroutines; anyio's plugin runs them on asyncio (root ``conftest.py``). Checks
raise ``AssertionError`` by hand: core ships this suite without depending on pytest.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

from agent_hub.core.agent_sessions.driver import (
    ABORTED_TERMINAL_REASON,
    Allow,
    DriverEvent,
    DriverHandle,
    Exited,
    InitEvent,
    PermissionRequest,
    PermissionSuggestion,
    SessionDriver,
    StartSpec,
    TextBlock,
    TextDelta,
    ToolCall,
    TurnResult,
)
from agent_hub.core.agent_sessions.errors import SessionTerminalError
from agent_hub.core.sessions.session import TokenUsage
from agent_hub.core.testing.session_driver_fakes import Hold, Turn

# How long any one event may take to arrive, and how long "nothing comes" is watched.
BOUND_SECONDS = 10.0
QUIET_SECONDS = 0.3

HELLO_RESULT = TurnResult(
    subtype="success",
    terminal_reason="completed",
    cost_usd=Decimal("0.0021"),
    usage=TokenUsage(input=20, output=4, cache_read=0, cache_write=0),
    duration_ms=50,
    num_turns=1,
)


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


@dataclass(frozen=True)
class ContractScenario:
    """The conversation the suite drives: a session spec and one scripted turn per prompt.

    ``hello`` streams text; ``ask`` asks permission for ``Bash`` before it answers; ``slow``
    streams one delta and then works until interrupted.
    """

    spec: StartSpec
    hello: str
    ask: str
    slow: str
    replies: Mapping[str, Turn] = field(default_factory=dict)


def contract_scenario(cwd: str = "/hubs/demo-hub") -> ContractScenario:
    """The standard scenario, in ``cwd``."""
    hello, ask, slow = "Say hello.", "Show the git status.", "Work on it slowly."
    request = PermissionRequest(
        request_id="contract-req-1",
        tool="Bash",
        input={"command": "git status", "description": "Show the working tree"},
        suggestions=(
            PermissionSuggestion(
                index=0,
                destination="localSettings",
                rule={
                    "type": "addRules",
                    "rules": [{"toolName": "Bash", "ruleContent": "git status"}],
                    "behavior": "allow",
                    "destination": "localSettings",
                },
            ),
        ),
    )
    return ContractScenario(
        spec=StartSpec(cwd=cwd, mode="default", model="sonnet"),
        hello=hello,
        ask=ask,
        slow=slow,
        replies={
            hello: (
                TextDelta(block=0, index=0, text="Hel"),
                TextDelta(block=0, index=1, text="lo."),
                TextBlock(block=0, text="Hello."),
                HELLO_RESULT,
            ),
            ask: (request, TextBlock(block=0, text="The tree is clean."), HELLO_RESULT),
            slow: (
                TextDelta(block=0, index=0, text="Working"),
                Hold(),
                TextBlock(block=0, text="Done."),
                HELLO_RESULT,
            ),
        },
    )


_END = object()


class _Pump:
    """Reads a handle's events in a task, so a test can wait for one with a deadline (and
    watch that none comes) without cancelling the driver's own iterator."""

    def __init__(self, events: AsyncIterator[DriverEvent]) -> None:
        self._queue: asyncio.Queue[object] = asyncio.Queue()
        self._peeked: list[object] = []
        self._task = asyncio.ensure_future(self._run(events))

    async def _run(self, events: AsyncIterator[DriverEvent]) -> None:
        async for event in events:
            await self._queue.put(event)
        await self._queue.put(_END)

    async def next(self) -> DriverEvent | None:
        """The next event, or None once the iterator ended."""
        if self._peeked:
            item = self._peeked.pop()
        else:
            item = await asyncio.wait_for(self._queue.get(), BOUND_SECONDS)
        if item is _END:
            self._peeked.append(_END)
            return None
        return cast("DriverEvent", item)

    async def turn(self) -> list[DriverEvent]:
        """Events up to and including the next ``TurnResult`` (or the end)."""
        seen: list[DriverEvent] = []
        while (event := await self.next()) is not None:
            seen.append(event)
            if isinstance(event, TurnResult):
                break
        return seen

    async def rest(self) -> list[DriverEvent]:
        """Every event until the iterator ends."""
        seen: list[DriverEvent] = []
        while (event := await self.next()) is not None:
            seen.append(event)
        return seen

    async def quiet(self) -> bool:
        """Whether no event arrives for ``QUIET_SECONDS``."""
        if self._peeked:
            return False
        try:
            item = await asyncio.wait_for(self._queue.get(), QUIET_SECONDS)
        except TimeoutError:
            return True
        self._peeked.append(item)
        return False

    async def stop(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


@asynccontextmanager
async def _session(
    driver: SessionDriver, scenario: ContractScenario
) -> AsyncIterator[tuple[DriverHandle, _Pump]]:
    handle = await driver.start(scenario.spec)
    pump = _Pump(driver.events(handle))
    try:
        yield handle, pump
    finally:
        await driver.close(handle)
        await pump.stop()


def _kinds(events: list[DriverEvent]) -> list[str]:
    return [event.kind for event in events]


class SessionDriverContract:
    """Event order, one result per turn, parked permissions, interrupt, settings, close."""

    async def test_emits_init_before_text_when_first_turn_runs(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        async with _session(session_driver, scenario) as (handle, pump):
            await session_driver.send(handle, scenario.hello)
            turn = await pump.turn()

        _check(turn[0].kind == "init", f"the first turn opens with init, got {_kinds(turn)}")
        init = turn[0]
        _check(isinstance(init, InitEvent) and bool(init.session_id), "init names the session")
        texts = [event.text for event in turn if isinstance(event, TextBlock)]
        _check(texts == ["Hello."], f"the completed text block arrives, got {texts}")
        deltas = "".join(event.text for event in turn if isinstance(event, TextDelta))
        _check(deltas in {"", "Hello."}, "deltas, when streamed, add up to the block")

    async def test_ends_each_turn_with_result_when_messages_sent(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        async with _session(session_driver, scenario) as (handle, pump):
            await session_driver.send(handle, scenario.hello)
            await session_driver.send(handle, scenario.hello)
            first = await pump.turn()
            second = await pump.turn()

        for turn in (first, second):
            result = turn[-1]
            _check(isinstance(result, TurnResult), f"a turn ends with a result: {_kinds(turn)}")
            _check(
                isinstance(result, TurnResult)
                and result.cost_usd is not None
                and result.usage is not None,
                "the result carries cost and usage",
            )
        _check(_kinds(first + second).count("init") == 1, "init comes once, on the first turn")

    async def test_parks_permission_until_answered_when_tool_asks(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        async with _session(session_driver, scenario) as (handle, pump):
            await session_driver.send(handle, scenario.ask)
            # A real CLI announces the tool use (init, tool.call) before it asks.
            request = await pump.next()
            while isinstance(request, InitEvent | ToolCall):
                request = await pump.next()
            _check(isinstance(request, PermissionRequest), f"a request comes, got {request}")
            _check(await pump.quiet(), "the turn waits while the request is unanswered")
            if isinstance(request, PermissionRequest):
                _check(request.tool == "Bash", "the request names the tool")
                await session_driver.answer_permission(handle, request.request_id, Allow())
            rest = await pump.turn()

        _check(_kinds(rest)[-1] == "result", f"the answered turn finishes, got {_kinds(rest)}")

    async def test_ends_turn_aborted_when_interrupted(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        async with _session(session_driver, scenario) as (handle, pump):
            await session_driver.send(handle, scenario.slow)
            started = [await pump.next(), await pump.next()]
            _check(_kinds([e for e in started if e is not None])[-1] == "text.delta", "it works")
            await session_driver.interrupt(handle)
            rest = await pump.turn()
            await session_driver.send(handle, scenario.hello)
            after = await pump.turn()

        result = rest[-1]
        _check(
            isinstance(result, TurnResult) and result.terminal_reason == ABORTED_TERMINAL_REASON,
            f"the interrupted turn ends aborted, got {rest}",
        )
        _check("Done." not in [e.text for e in rest if isinstance(e, TextBlock)], "it stops")
        _check(_kinds(after)[-1] == "result", "the next message plays a new turn")

    async def test_accepts_mode_and_model_when_between_turns(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        async with _session(session_driver, scenario) as (handle, pump):
            await session_driver.send(handle, scenario.hello)
            await pump.turn()
            await session_driver.set_mode(handle, "plan")
            await session_driver.set_mode(handle, "acceptEdits")
            await session_driver.set_model(handle, "opus")
            await session_driver.send(handle, scenario.hello)
            turn = await pump.turn()

        _check(_kinds(turn)[-1] == "result", "a turn after the changes still finishes")

    async def test_emits_exited_when_closed(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        handle = await session_driver.start(scenario.spec)
        pump = _Pump(session_driver.events(handle))
        try:
            await session_driver.send(handle, scenario.hello)
            await pump.turn()
            await session_driver.close(handle)
            await session_driver.close(handle)
            rest = await pump.rest()
        finally:
            await pump.stop()

        _check(bool(rest) and isinstance(rest[-1], Exited), f"exited comes last, got {rest}")
        try:
            await session_driver.send(handle, scenario.hello)
        except SessionTerminalError:
            return
        raise AssertionError("a closed session refuses messages")

    async def test_exits_when_closed_with_permission_pending(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        handle = await session_driver.start(scenario.spec)
        pump = _Pump(session_driver.events(handle))
        try:
            await session_driver.send(handle, scenario.ask)
            while not isinstance(await pump.next(), PermissionRequest):
                pass
            await session_driver.close(handle)
            rest = await pump.rest()
        finally:
            await pump.stop()

        _check(bool(rest) and isinstance(rest[-1], Exited), f"close ends the process: {rest}")
        _check("text" not in _kinds(rest), "the denied tool's turn does not go on")

    async def test_reports_capabilities_when_asked(
        self, session_driver: SessionDriver, scenario: ContractScenario
    ) -> None:
        capabilities = await session_driver.capabilities()

        _check(capabilities.available, f"the driver can start sessions: {capabilities.reason}")
        _check(bool(capabilities.models), "it offers models")
        past = await session_driver.list_resumable(scenario.spec.cwd)
        _check(isinstance(past, tuple), "past sessions are a tuple")
