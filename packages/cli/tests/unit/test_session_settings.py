import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.cli.session_settings import (
    HubHooksError,
    hub_hooks_settings,
    session_settings_path,
    write_session_settings,
)
from agent_hub.core.runner.session_settings import hooks_settings
from agent_hub.core.testing.builders import a_hub_settings_document

PREFIX = "cannot wire the hub's hooks: "


def hub_hooks(hub: Path) -> None:
    """Give ``hub`` the synthetic settings and an empty file for each script they name."""
    document = a_hub_settings_document()
    (hub / ".claude").mkdir(parents=True)
    (hub / ".claude" / "settings.json").write_text(json.dumps(document), encoding="utf-8")
    _, scripts = hooks_settings(document, effort="medium", hub="/h")
    for script in scripts:
        (hub / script).parent.mkdir(parents=True, exist_ok=True)
        (hub / script).write_bytes(b"")


def settings_file(hub: Path) -> Path:
    path = hub / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def with_guard_command(hub: Path, command: str) -> None:
    hub_hooks(hub)
    document = a_hub_settings_document()
    document["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = command
    settings_file(hub).write_text(json.dumps(document), encoding="utf-8")


def no_settings(hub: Path) -> str:
    hub.mkdir()
    return str(hub / ".claude" / "settings.json")


def too_large(hub: Path) -> str:
    path = settings_file(hub)
    path.write_bytes(b" " * 1_048_577)
    return str(path)


def not_json(hub: Path) -> str:
    path = settings_file(hub)
    path.write_bytes(b"{")
    return str(path)


def no_hooks(hub: Path) -> str:
    path = settings_file(hub)
    path.write_bytes(b'{"env": {}}')
    return str(path)


def lone_surrogate(hub: Path) -> str:
    path = settings_file(hub)
    path.write_bytes(b'{"hooks": {"Stop": [{"hooks": [{"command": "echo \\ud800"}]}]}}')
    return str(path)


def guard_absent(hub: Path) -> str:
    hub_hooks(hub)
    (hub / "plugin" / "hub-workflow" / "hooks" / "guard.py").unlink()
    return "plugin/hub-workflow/hooks/guard.py"


def script_above_hub(hub: Path) -> str:
    with_guard_command(hub, 'python3 "$CLAUDE_PROJECT_DIR/../outside.py"')
    (hub.parent / "outside.py").write_bytes(b"")
    return "../outside.py"


def script_at_root(hub: Path) -> str:
    with_guard_command(hub, 'cat "$CLAUDE_PROJECT_DIR//etc/hostname"')
    return "/etc/hostname"


def leftover_variable(hub: Path) -> str:
    with_guard_command(hub, 'python3 "${CLAUDE_PROJECT_DIR}/x.py"')
    return str(settings_file(hub))


def unquoted_variable(hub: Path) -> str:
    with_guard_command(hub, "python3 $CLAUDE_PROJECT_DIR/plugin/hub-workflow/hooks/guard.py")
    return str(settings_file(hub))


def valid_hooks(hub: Path) -> str:
    hub_hooks(hub)
    return str(hub)


def named(text: str, message: str) -> bool:
    return text in message or json.dumps(text) in message


@pytest.mark.parametrize(
    ("folder", "broken", "words"),
    [
        ("hub", no_settings, "is missing"),
        ("hub", too_large, "larger than"),
        ("hub", not_json, "not valid JSON"),
        ("hub", no_hooks, 'no "hooks" object'),
        ("hub", lone_surrogate, "lone surrogate"),
        ("hub", guard_absent, "is missing"),
        ("hub", script_above_hub, "is outside the hub"),
        ("hub", script_at_root, "is outside the hub"),
        ("hub", leftover_variable, "CLAUDE_PROJECT_DIR"),
        ("hub", unquoted_variable, "plain words"),
        ('h"ub', valid_hooks, "holds"),
        ("h\udcffub", valid_hooks, "not UTF-8"),
    ],
    ids=[
        "no-settings",
        "too-large",
        "not-json",
        "no-hooks",
        "lone-surrogate",
        "script-missing",
        "script-above-hub",
        "script-at-root",
        "leftover-variable",
        "unquoted-variable",
        "hub-path",
        "hub-path-not-utf8",
    ],
)
def test_names_the_problem_when_hub_hooks_cannot_be_wired(
    tmp_path: Path, *, folder: str, broken: Callable[[Path], str], words: str
) -> None:
    hub = tmp_path / folder
    text = broken(hub)

    with pytest.raises(HubHooksError) as raised:
        hub_hooks_settings(hub, "medium")

    message = str(raised.value)
    assert message.startswith(PREFIX)
    assert named(text, message)
    assert words in message
    assert "\n" not in message
    assert not (hub / ".agent-runs").exists()


def test_names_only_capped_script_path_when_script_missing(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    script = "a" * 300 + ".py"
    with_guard_command(hub, f'python3 "$CLAUDE_PROJECT_DIR/{script}"')

    with pytest.raises(HubHooksError) as raised:
        hub_hooks_settings(hub, "medium")

    message = str(raised.value)
    assert "a" * 120 in message
    assert "a" * 121 not in message
    assert str(tmp_path) not in message


@pytest.mark.parametrize(
    "call",
    [session_settings_path, hub_hooks_settings, write_session_settings],
    ids=["path", "read", "write"],
)
def test_refuses_effort_when_not_a_level(
    tmp_path: Path, call: Callable[[Path, str], object]
) -> None:
    hub = tmp_path / "hub"
    hub_hooks(hub)
    effort = "../" + "x" * 300

    with pytest.raises(HubHooksError, match="effort") as raised:
        call(hub, effort)

    message = str(raised.value)
    assert message.startswith(PREFIX)
    assert "x" * 120 in message
    assert "x" * 121 not in message
    assert not (hub / ".agent-runs").exists()


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_writes_owner_only_settings_when_hub_hooks_wired(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub_hooks(hub)
    folder = hub / ".agent-runs" / "session-settings"
    expected = folder / "medium.json"

    written = write_session_settings(hub, "medium")

    assert written == expected
    assert written.read_bytes() == hub_hooks_settings(hub, "medium")
    assert mode_of(written) == 0o600
    assert mode_of(folder) == 0o700
    assert mode_of(hub / ".agent-runs") == 0o700
    written.write_bytes(b"{}")

    rewritten = write_session_settings(hub, "medium")

    assert rewritten.read_bytes() == hub_hooks_settings(hub, "medium")
    assert mode_of(rewritten) == 0o600
    assert os.listdir(folder) == ["medium.json"]


def test_refuses_link_when_settings_folder_is_a_link(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub_hooks(hub)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (hub / ".agent-runs").mkdir()
    (hub / ".agent-runs" / "session-settings").symlink_to(elsewhere)

    with pytest.raises(HubHooksError, match="cannot write ") as raised:
        write_session_settings(hub, "medium")

    assert str(raised.value).startswith(PREFIX)
    assert os.listdir(elsewhere) == []


def test_replaces_link_when_settings_file_is_a_link(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub_hooks(hub)
    target = tmp_path / "target.json"
    target.write_bytes(b"kept\n")
    folder = hub / ".agent-runs" / "session-settings"
    folder.mkdir(parents=True)
    (folder / "medium.json").symlink_to(target)

    written = write_session_settings(hub, "medium")

    assert not written.is_symlink()
    assert stat.S_ISREG(os.lstat(written).st_mode)
    assert written.read_bytes() == hub_hooks_settings(hub, "medium")
    assert target.read_bytes() == b"kept\n"


def test_tightens_folder_mode_when_settings_folder_is_loose(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub_hooks(hub)
    folder = hub / ".agent-runs" / "session-settings"
    folder.mkdir(parents=True)
    folder.chmod(0o777)

    write_session_settings(hub, "medium")

    assert mode_of(folder) == 0o700
