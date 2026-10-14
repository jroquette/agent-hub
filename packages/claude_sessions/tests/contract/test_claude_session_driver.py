"""``ClaudeSdkSessionDriver`` honours ``SessionDriverContract`` against the stub CLI (AC-165.2)."""

from pathlib import Path

import pytest

from agent_hub.claude_sessions.sdk_driver import PROTOCOL_EXIT_CODE, ClaudeSdkSessionDriver
from agent_hub.claude_sessions.testing.scenarios import Scenario, TextStep, read_records
from agent_hub.core.agent_sessions.driver import (
    DriverError,
    DriverEvent,
    Exited,
    InitEvent,
    StartSpec,
)
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError
from agent_hub.core.testing.session_driver_contract import ContractScenario, SessionDriverContract

from .conftest import stub_environ, stub_scenario

pytestmark = pytest.mark.anyio


@pytest.fixture
def session_driver(tmp_path: Path, scenario: ContractScenario) -> ClaudeSdkSessionDriver:
    environ = stub_environ(tmp_path, stub_scenario(scenario.replies))
    return ClaudeSdkSessionDriver(environ=environ, lister=lambda _directory, _limit: [])


class TestClaudeSdkSessionDriver(SessionDriverContract):
    pytestmark = pytest.mark.anyio


async def _all(driver: ClaudeSdkSessionDriver, spec: StartSpec, text: str) -> list[DriverEvent]:
    handle = await driver.start(spec)
    await driver.send(handle, text)
    return [event async for event in driver.events(handle)]


async def test_fails_session_when_message_oversize(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    scenario = Scenario(replies={"big": [TextStep(text="x" * 20_000)]})
    driver = ClaudeSdkSessionDriver(
        environ=stub_environ(tmp_path, scenario), lister=lambda _d, _l: [], max_buffer_size=4096
    )

    events = await _all(driver, StartSpec(cwd=str(cwd), mode="default"), "big")

    assert isinstance(events[0], InitEvent)
    assert events[-2:] == [
        DriverError(message="claude sent a message over 4096 bytes or not JSON"),
        Exited(code=PROTOCOL_EXIT_CODE),
    ]
    assert "x" * 100 not in str(events)


async def test_passes_spec_to_cli_when_started(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    cwd.mkdir()
    environ = stub_environ(tmp_path, Scenario(replies={"hi": [TextStep(text="ok")]}))
    driver = ClaudeSdkSessionDriver(environ=environ, lister=lambda _d, _l: [])
    spec = StartSpec(
        cwd=str(cwd),
        mode="plan",
        model="haiku",
        session_id="44444444-4444-4444-8444-444444444444",
        environment_extra={"AGENT_HUB_WEB_URL": "http://127.0.0.1:7420"},
    )

    handle = await driver.start(spec)
    await driver.send(handle, "hi")
    events = driver.events(handle)
    init = await anext(events)
    await driver.close(handle)

    [start] = [
        r
        for r in read_records(Path(environ["STUB_CLAUDE_RECORD"]))
        if r.event == "start" and "-v" not in r.args
    ]
    assert start.argv0 == str(tmp_path / "bin" / "claude")
    assert {"--permission-mode", "plan", "--model", "haiku"} <= set(start.args)
    assert "--session-id=44444444-4444-4444-8444-444444444444" in start.args
    assert "AGENT_HUB_WEB_URL" in start.env_keys
    assert init == InitEvent(
        session_id="44444444-4444-4444-8444-444444444444",
        model="haiku",
        slash_commands=("compact", "review"),
    )


async def test_refuses_start_when_claude_missing(tmp_path: Path) -> None:
    driver = ClaudeSdkSessionDriver(environ={"PATH": str(tmp_path)})

    with pytest.raises(SessionsUnavailableError):
        await driver.start(StartSpec(cwd=str(tmp_path), mode="default"))
    capabilities = await driver.capabilities()

    assert not capabilities.available
