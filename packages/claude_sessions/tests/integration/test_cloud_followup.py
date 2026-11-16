"""A cloud follow-up against the stub ``claude`` (argv level; no cloud is ever reached)."""

import json
import os
from pathlib import Path

import pytest

from agent_hub.claude_sessions.cloud_launcher import ClaudeCloudLauncher
from agent_hub.claude_sessions.testing.scenarios import (
    RECORD_ENV,
    SCENARIO_ENV,
    Scenario,
    read_records,
    write_scenario,
    write_shim,
)
from agent_hub.core.agent_sessions.cloud import CloudReply
from agent_hub.core.agent_sessions.errors import CloudFailedError

pytestmark = pytest.mark.anyio

CLOUD_ID = "cse_01synthetic"


def _environ(tmp_path: Path, scenario: Scenario) -> dict[str, str]:
    shim = write_shim(tmp_path / "bin")
    return {
        **os.environ,
        "PATH": f"{shim.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        SCENARIO_ENV: str(write_scenario(tmp_path, scenario)),
        RECORD_ENV: str(tmp_path / "record.jsonl"),
    }


async def test_runs_stub_with_text_as_one_argument_when_followed_up(tmp_path: Path) -> None:
    output = json.dumps(
        {"ok": True, "session_id": CLOUD_ID, "url": f"https://claude.ai/code/{CLOUD_ID}"}
    )
    environ = _environ(tmp_path, Scenario(cloud_output=output))
    text = "Also $(touch pwned) the docs"

    reply = await ClaudeCloudLauncher(environ=environ).follow_up(CLOUD_ID, text, timeout_seconds=30)

    assert reply == CloudReply(cloud_id=CLOUD_ID, url=f"https://claude.ai/code/{CLOUD_ID}")
    [start] = read_records(tmp_path / "record.jsonl")
    assert start.argv0 == str(tmp_path / "bin" / "claude")
    assert start.args == ["-p", "--cloud", CLOUD_ID, "--output-format", "json", text]
    assert not (tmp_path / "pwned").exists()


async def test_fails_when_stub_exits_non_zero(tmp_path: Path) -> None:
    environ = _environ(tmp_path, Scenario(cloud_output="Error: offline\n", cloud_exit=1))

    with pytest.raises(CloudFailedError, match="exit 1"):
        await ClaudeCloudLauncher(environ=environ).follow_up(CLOUD_ID, "go on", timeout_seconds=30)
