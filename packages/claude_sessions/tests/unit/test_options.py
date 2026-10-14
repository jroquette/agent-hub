"""The options the adapter hands the SDK (AC-165.3, E15)."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agent_hub.claude_sessions.environment import WEB_URL_VARIABLE
from agent_hub.claude_sessions.options import MAX_BUFFER_BYTES, claude_path, sdk_options
from agent_hub.core.agent_sessions.driver import PermissionMode, StartSpec

CLI = "/opt/claude/bin/claude"


async def _can_use_tool(_name: str, _input: dict[str, Any], _context: Any) -> Any:
    return None


def _spec(**overrides: Any) -> StartSpec:
    fields: dict[str, Any] = {"cwd": "/hubs/demo-hub", "mode": "default"}
    return StartSpec.model_validate(fields | overrides)


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_keeps_default_setting_sources_when_options_built() -> None:
    options = sdk_options(_spec(), can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert options.setting_sources is None
    assert options.include_partial_messages is True
    assert options.can_use_tool is _can_use_tool
    assert options.cwd == "/hubs/demo-hub"
    assert options.cli_path == CLI
    assert options.max_buffer_size == MAX_BUFFER_BYTES == 8 * 1024 * 1024
    assert options.hooks is None


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan"])
def test_passes_mode_always_when_options_built(mode: PermissionMode) -> None:
    options = sdk_options(_spec(mode=mode), can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert options.permission_mode == mode


def test_passes_model_resume_fork_and_session_id_when_spec_names_them() -> None:
    spec = _spec(
        model="sonnet",
        resume="22222222-2222-4222-8222-222222222222",
        fork=True,
        session_id="44444444-4444-4444-8444-444444444444",
    )

    options = sdk_options(spec, can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert (options.model, options.resume, options.fork_session, options.session_id) == (
        "sonnet",
        "22222222-2222-4222-8222-222222222222",
        True,
        "44444444-4444-4444-8444-444444444444",
    )
    assert options.extra_args == {}


def test_passes_child_environment_when_spec_adds_web_url() -> None:
    spec = _spec(environment_extra={WEB_URL_VARIABLE: "http://127.0.0.1:7420"})

    options = sdk_options(
        spec, can_use_tool=_can_use_tool, cli_path=CLI, environ={"HOME": "/home/demo"}
    )

    assert options.env == {"HOME": "/home/demo", WEB_URL_VARIABLE: "http://127.0.0.1:7420"}


def test_discards_child_stderr_when_options_built() -> None:
    options = sdk_options(_spec(), can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert options.stderr is not None
    assert options.stderr("a line the CLI wrote") is None


def test_sets_cli_path_absolute_when_claude_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _executable(tmp_path / "bin" / "claude")
    monkeypatch.chdir(tmp_path)

    found = claude_path({"PATH": f"/nonexistent{os.pathsep}bin"})

    assert found == str(tmp_path / "bin" / "claude")
    assert Path(found).is_absolute()


def test_finds_no_claude_when_path_lacks_it(tmp_path: Path) -> None:
    assert claude_path({"PATH": str(tmp_path)}) is None
    assert claude_path({}) is None
