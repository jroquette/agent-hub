import json
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.cli.session_settings import HubHooksError, hub_hooks_settings
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

