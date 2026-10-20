import json
from typing import Any

import pytest

from agent_hub.core.runner.session_settings import (
    HookCommandError,
    HubPathError,
    NoHooksError,
    hooks_settings,
)
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
    assert hooks["Notification"][0]["hooks"][0]["command"] == "echo notified"


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


@pytest.mark.parametrize("source", [[], {}, {"hooks": []}, {"hooks": "x"}])
def test_refuses_source_when_hooks_not_an_object(source: Any) -> None:
    with pytest.raises(NoHooksError, match="hooks"):
        hooks_settings(source, effort="low", hub=HUB)


@pytest.mark.parametrize("character", ['"', "$", "`", "\\"])
def test_refuses_hub_path_when_it_holds_a_shell_character(character: str) -> None:
    hub = f"/w/h{character}ub"

    with pytest.raises(HubPathError, match="holds"):
        hooks_settings(a_hub_settings_document(), effort="low", hub=hub)


def test_refuses_hub_path_when_it_is_not_utf8() -> None:
    # How Python reads the byte 0xff in a file name (surrogateescape).
    hub = "/w/h\udcffub"

    with pytest.raises(HubPathError, match="not UTF-8"):
        hooks_settings(a_hub_settings_document(), effort="low", hub=hub)


def with_guard_command(command: str) -> dict[str, Any]:
    source = a_hub_settings_document()
    source["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = command
    return source


@pytest.mark.parametrize(
    "command",
    [
        'python3 "${CLAUDE_PROJECT_DIR}/x.py"',
        "cd $CLAUDE_PROJECT_DIR && make",
        'python3 "$CLAUDE_PROJECT_DIR"/x.py',
        'python3 "$CLAUDE_PROJECT_DIR/x.py" "$CLAUDE_PROJECT_DIR"',
    ],
    ids=["braces", "bare", "quoted-bare", "bare-after-rewritten"],
)
def test_refuses_command_when_variable_left_after_rewrite(command: str) -> None:
    with pytest.raises(HookCommandError, match="CLAUDE_PROJECT_DIR") as raised:
        hooks_settings(with_guard_command(command), effort="low", hub=HUB)

    assert '"PreToolUse"' in str(raised.value)


ONLY_PLAIN_WORDS = 'must use only "$CLAUDE_PROJECT_DIR/<path>" and plain words'
# Every form a shell could read as an expansion of the variable outside one plain
# double-quoted word, or that hides one from a simple reader (spec AM-1).
REFUSED_COMMANDS = {
    "unquoted": "python3 $CLAUDE_PROJECT_DIR/plugin/x.py",
    "single-quoted": "python3 '$CLAUDE_PROJECT_DIR/plugin/x.py'",
    "after-closing-quote": 'python3 "x"$CLAUDE_PROJECT_DIR/plugin/x.py',
    "escaped": 'python3 "\\$CLAUDE_PROJECT_DIR/plugin/x.py"',
    "nested-quotes": 'python3 "$(echo "$CLAUDE_PROJECT_DIR/plugin/x.py")"',
    "ansi-c": "echo $'\\'\"' $CLAUDE_PROJECT_DIR/x '\"'",
    "command-substitution": 'python3 "$(echo $CLAUDE_PROJECT_DIR/x)"',
    "backticks": 'python3 "`echo $CLAUDE_PROJECT_DIR/x`"',
    "default-expansion": 'python3 "${x:-$CLAUDE_PROJECT_DIR/y}"',
    "pid-prefix": 'python3 "$$CLAUDE_PROJECT_DIR/x"',
    "comment": 'python3 "$CLAUDE_PROJECT_DIR/x.py" # say "hi"',
    "heredoc": 'python3 "$CLAUDE_PROJECT_DIR/x.py" <<EOF\nsay "hi"\nEOF',
    "odd-quotes": 'python3 "$CLAUDE_PROJECT_DIR/x.py" "',
    "glued-word": 'python3 a"$CLAUDE_PROJECT_DIR/x.py"',
    "other-variable": 'python3 "$CLAUDE_PROJECT_DIR/x.py" $HOME',
}


@pytest.mark.parametrize("command", REFUSED_COMMANDS.values(), ids=REFUSED_COMMANDS.keys())
def test_refuses_command_when_not_only_plain_words(command: str) -> None:
    with pytest.raises(HookCommandError) as raised:
        hooks_settings(with_guard_command(command), effort="low", hub=HUB)

    message = str(raised.value)
    assert ONLY_PLAIN_WORDS in message
    assert '"PreToolUse"' in message
    assert "\n" not in message


# The shape of every command a synced hub's settings hold today.
HUB_HOOK_SCRIPTS = (
    "event_sensor.py",
    "post_edit.py",
    "pre_compact.py",
    "guard.py",
    "session_end.py",
    "session_start.py",
    "stop_gate.py",
    "readonly_gate.py",
)


@pytest.mark.parametrize("script", HUB_HOOK_SCRIPTS)
def test_rewrites_command_when_hub_hook_shape(script: str) -> None:
    command = f'python3 "$CLAUDE_PROJECT_DIR/plugin/hub-workflow/hooks/{script}"'

    content, scripts = hooks_settings(with_guard_command(command), effort="low", hub=HUB)

    hooks = json.loads(content)["hooks"]
    built = hooks["PreToolUse"][0]["hooks"][0]["command"]
    assert built == f'python3 "{HUB}/plugin/hub-workflow/hooks/{script}"'
    assert f"plugin/hub-workflow/hooks/{script}" in scripts


def test_caps_event_name_when_command_refused() -> None:
    event = "E" * 300
    source = a_hub_settings_document()
    source["hooks"] = {event: [{"hooks": [{"type": "command", "command": "echo $X"}]}]}

    with pytest.raises(HookCommandError) as raised:
        hooks_settings(source, effort="low", hub=HUB)

    assert "E" * 120 in str(raised.value)
    assert "E" * 121 not in str(raised.value)


@pytest.mark.parametrize("hub", ["/w/c;touch PWNED;", "/w/c\nid", "/w/c'x"])
def test_refuses_command_when_hub_path_would_run_as_shell(hub: str) -> None:
    source = with_guard_command("python3 $CLAUDE_PROJECT_DIR/plugin/x.py")

    with pytest.raises(HookCommandError, match="plain words"):
        hooks_settings(source, effort="low", hub=hub)


@pytest.mark.parametrize("hub", ["/w/c;touch PWNED;", "/w/c\nid", "/w/c'x"])
def test_keeps_hub_path_literal_when_command_double_quotes_it(hub: str) -> None:
    content, _ = hooks_settings(a_hub_settings_document(), effort="low", hub=hub)

    hooks = json.loads(content)["hooks"]
    command = hooks["PreToolUse"][0]["hooks"][0]["command"]
    assert command == f'python3 "{hub}/plugin/hub-workflow/hooks/guard.py"'


def test_refuses_command_when_it_is_not_utf8() -> None:
    source = with_guard_command('python3 "$CLAUDE_PROJECT_DIR/x\ud800.py"')

    with pytest.raises(HookCommandError, match="not UTF-8"):
        hooks_settings(source, effort="low", hub=HUB)
