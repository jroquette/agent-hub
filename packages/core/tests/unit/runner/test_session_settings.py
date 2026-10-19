import json
from typing import Any

from agent_hub.core.runner.session_settings import hooks_settings
from agent_hub.core.testing.builders import a_hub_settings_document

HUB = "/w/hub"
VARIABLE = "$CLAUDE_PROJECT_DIR/"


def rewritten(hooks: dict[str, Any]) -> dict[str, Any]:
    # The expected hooks: the same structure, with each command's prefix replaced.
    expected: dict[str, Any] = json.loads(json.dumps(hooks))
    for groups in expected.values():
        for group in groups:
            for entry in group["hooks"]:
                entry["command"] = entry["command"].replace(VARIABLE, f"{HUB}/")
    return expected


def test_keeps_only_hooks_rewritten_when_settings_built() -> None:
    source = a_hub_settings_document()

    content, _ = hooks_settings(source, effort="low", hub=HUB)

    built = json.loads(content.decode("utf-8"))
    assert list(built) == ["effortLevel", "hooks"]
    assert built["effortLevel"] == "low"
    hooks = built["hooks"]
    assert list(hooks) == ["SessionStart", "PreToolUse", "Stop", "Notification"]
    assert hooks == rewritten(source["hooks"])
    commands = [
        entry["command"]
        for groups in hooks.values()
        for group in groups
        for entry in group["hooks"]
    ]
    assert not any(VARIABLE in command for command in commands)
    assert 'python3 "/w/hub/plugin/hub-workflow/hooks/guard.py"' in commands
    assert hooks["Stop"][0]["hooks"][1]["command"] == "echo done"
    assert hooks["Notification"][0]["hooks"][0]["command"] == 'python3 "${CLAUDE_PROJECT_DIR}/x.py"'


def test_gives_same_bytes_when_built_twice() -> None:
    first, _ = hooks_settings(a_hub_settings_document(), effort="medium", hub=HUB)
    second, _ = hooks_settings(a_hub_settings_document(), effort="medium", hub=HUB)

    assert first == second
    assert first.endswith(b"\n")


def test_lists_each_rewritten_script_once_when_hooks_name_them() -> None:
    source = a_hub_settings_document()
    source["hooks"]["PreToolUse"].append(
        {"matcher": "Write", "hooks": [source["hooks"]["PreToolUse"][0]["hooks"][0]]}
    )

    _, scripts = hooks_settings(source, effort="low", hub=HUB)

    folder = "plugin/hub-workflow/hooks"
    assert scripts == (
        f"{folder}/session_start.py",
        f"{folder}/event_sensor.py",
        f"{folder}/guard.py",
        f"{folder}/stop_gate.py",
    )
