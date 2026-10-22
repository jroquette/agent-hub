"""The options the adapter hands the SDK (AC-165.3, E15)."""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from agent_hub.claude_sessions.environment import WEB_URL_VARIABLE
from agent_hub.claude_sessions.options import MAX_BUFFER_BYTES, claude_path, sdk_options
from agent_hub.core.agent_sessions.driver import PermissionMode, StartSpec
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.scenarios.investigation import ToolPolicy

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


def test_loads_no_plugin_when_spec_names_none() -> None:
    options = sdk_options(_spec(), can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert options.plugins == []


def test_loads_hub_plugins_when_spec_names_them() -> None:
    spec = _spec(plugin_dirs=("/hubs/demo-hub/plugin/hub-workflow",))

    options = sdk_options(spec, can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert options.plugins == [{"type": "local", "path": "/hubs/demo-hub/plugin/hub-workflow"}]


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


def _investigation_policy(tmp_path: Path) -> ToolPolicy:
    hub = tmp_path / "work" / "demo-hub"
    (hub / "actions" / "orders").mkdir(parents=True)
    env_file = tmp_path / "work" / "demo-api" / "environment" / ".env.staging"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("DEMO_DB_URL=placeholder\n", encoding="utf-8")
    return ToolPolicy.of(
        hub=str(hub),
        repos=("demo-api",),
        env_files=("demo-api/environment/.env.staging",),
        run_id="a1b2c3d4",
    )


async def _decide(options: Any, tool: str, tool_input: dict[str, Any]) -> Any:
    (matcher,) = options.hooks["PreToolUse"]
    (hook,) = matcher.hooks
    hook_input = {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "/tmp/t",  # noqa: S108 -- never opened
        "cwd": "/hubs/demo-hub",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }
    return await hook(hook_input, "toolu_1", {"signal": None})


@pytest.mark.anyio
async def test_sets_tools_and_hook_when_investigation_read_only_policy(tmp_path: Path) -> None:
    policy = _investigation_policy(tmp_path)
    spec = _spec(cwd=policy.workdir, tool_policy=policy, system_prompt="You investigate.")

    options = sdk_options(spec, can_use_tool=_can_use_tool, cli_path=CLI, environ={})
    denied = await _decide(options, "Read", {"file_path": policy.env_files[0]})
    shell = await _decide(options, "Bash", {"command": "curl http://localhost"})
    allowed = await _decide(options, "Read", {"file_path": "README.md"})

    assert options.tools == ["Read", "Glob", "Grep", "Write", "Bash"]
    assert list(options.hooks) == ["PreToolUse"]
    assert options.hooks["PreToolUse"][0].matcher is None
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "env file" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert shell["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert allowed == {}
    assert options.system_prompt == {
        "type": "preset",
        "preset": "claude_code",
        "append": "You investigate.",
    }
    assert options.permission_mode == "default"


def test_sets_no_tools_or_prompt_when_investigation_policy_absent() -> None:
    options = sdk_options(_spec(), can_use_tool=_can_use_tool, cli_path=CLI, environ={})

    assert (options.tools, options.hooks, options.system_prompt) == (None, None, None)


def test_blanks_inherited_names_when_credential_injection_hidden() -> None:
    # The SDK starts the child from this process's environment and only adds ``env`` on top,
    # so a hidden name present there is overridden with an empty value.
    secret = "x-sec" + "ret-y"
    hidden = CredentialNames(
        env=frozenset({"DEMO_DB_URL"}), aws_profiles=frozenset({"demo-staging"})
    )
    environ = {"HOME": "/home/demo", "DEMO_DB_URL": secret, "AWS_PROFILE": "demo-staging"}

    options = sdk_options(
        _spec(hidden_environment=hidden), can_use_tool=_can_use_tool, cli_path=CLI, environ=environ
    )

    assert options.env == {"HOME": "/home/demo", "DEMO_DB_URL": "", "AWS_PROFILE": ""}
    assert secret not in options.env.values()
