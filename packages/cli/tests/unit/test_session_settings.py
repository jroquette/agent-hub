import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.cli.session_settings import (
    HubHooksError,
    hub_hooks_settings,
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


def no_settings(hub: Path) -> Path:
    hub.mkdir()
    return hub / ".claude" / "settings.json"


def too_large(hub: Path) -> Path:
    path = settings_file(hub)
    path.write_bytes(b" " * 1_048_577)
    return path


def not_json(hub: Path) -> Path:
    path = settings_file(hub)
    path.write_bytes(b"{")
    return path


def no_hooks(hub: Path) -> Path:
    path = settings_file(hub)
    path.write_bytes(b'{"env": {}}')
    return path


def guard_absent(hub: Path) -> Path:
    hub_hooks(hub)
    path = hub / "plugin" / "hub-workflow" / "hooks" / "guard.py"
    path.unlink()
    return path


def shell_character_in_hub(hub: Path) -> Path:
    hub_hooks(hub)
    return hub


def named(path: Path, message: str) -> bool:
    return str(path) in message or json.dumps(str(path)) in message


@pytest.mark.parametrize(
    ("folder", "broken"),
    [
        ("hub", no_settings),
        ("hub", too_large),
        ("hub", not_json),
        ("hub", no_hooks),
        ("hub", guard_absent),
        ('h"ub', shell_character_in_hub),
    ],
    ids=["no-settings", "too-large", "not-json", "no-hooks", "script-missing", "hub-path"],
)
def test_names_the_problem_when_hub_hooks_cannot_be_wired(
    tmp_path: Path, folder: str, broken: Callable[[Path], Path]
) -> None:
    hub = tmp_path / folder
    path = broken(hub)

    with pytest.raises(HubHooksError) as raised:
        hub_hooks_settings(hub, "medium")

    message = str(raised.value)
    assert message.startswith(PREFIX)
    assert named(path, message)
    assert "\n" not in message
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
