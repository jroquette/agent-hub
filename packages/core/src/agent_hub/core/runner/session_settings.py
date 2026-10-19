"""The hooks-only ``--settings`` file of a ``claude -p`` session whose cwd is a repo (AGH-278).

A session in the hub loads the hub's ``.claude/settings.json`` itself; one in a repo does not,
so it gets a file built from it: ``effortLevel`` and the hub's ``hooks`` block, nothing else
(no ``permissions``, ``sandbox``, ``env`` or ``enabledPlugins``). Events, groups and entries
keep their order. In every string under a ``command`` key, ``$CLAUDE_PROJECT_DIR/`` becomes
the hub's path and ``/``, since Claude Code sets that variable to the session's cwd (the repo).
The same source, effort and hub path always give the same bytes.

A command that would still reach the repo, or run the hub's path as shell syntax, is refused
(spec AM-1): one that names ``CLAUDE_PROJECT_DIR`` in any other spelling
(``${CLAUDE_PROJECT_DIR}``, a bare ``$CLAUDE_PROJECT_DIR``), and one where
``$CLAUDE_PROJECT_DIR/`` is not inside a double-quoted word. Inside double quotes only ``"``,
``$``, a backtick and ``\\`` are not literal, so a hub path holding one of them is refused, as
is a hub path or a command that is not UTF-8 text.
"""

import json
import re
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue

PROJECT_DIR: Final = "$CLAUDE_PROJECT_DIR/"
_VARIABLE_NAME: Final = "CLAUDE_PROJECT_DIR"
# The hub-relative path a command names after the variable, up to a quote or a space.
_SCRIPT: Final = re.compile(r"\$CLAUDE_PROJECT_DIR/([^\"'\s]+)")
# What a double-quoted shell word would read as other than itself.
_SHELL_CHARACTERS: Final = frozenset('"$`\\')


class SessionSettingsError(AgentHubError, ValueError):
    """Why the settings file cannot be built; ``reason`` is one line and names no path."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class NoHooksError(SessionSettingsError):
    """The source holds no ``hooks`` object."""


class HubPathError(SessionSettingsError):
    """The hub's path cannot be written into a command; the caller shows the path."""


class HookCommandError(SessionSettingsError):
    """A hook command cannot be given to a repo-cwd session as written."""


def hooks_settings(source: JsonValue, *, effort: str, hub: str) -> tuple[bytes, tuple[str, ...]]:
    """The settings file's bytes for ``effort``, and the hub-relative scripts its commands name.

    ``source`` is the hub's parsed ``.claude/settings.json`` and ``hub`` the hub's path. The
    scripts are listed in the order first seen, each once. Raises ``NoHooksError`` when
    ``source`` holds no ``hooks`` object, ``HubPathError`` when ``hub`` is not UTF-8 or holds a
    shell character, and ``HookCommandError`` for a command refused above.
    """
    hooks = source.get("hooks") if isinstance(source, dict) else None
    if not isinstance(hooks, dict):
        raise NoHooksError('no "hooks" object')
    if not _is_utf8(hub):
        raise HubPathError("the hub's path is not UTF-8 text")
    if _SHELL_CHARACTERS.intersection(hub):
        raise HubPathError("the hub's path holds \" $ ` or \\")
    scripts: list[str] = []
    built = {
        event: _rewritten(groups, event=event, prefix=f"{hub}/", scripts=scripts, is_command=False)
        for event, groups in hooks.items()
    }
    text = json.dumps({"effortLevel": effort, "hooks": built}, indent=2, ensure_ascii=False)
    if not _is_utf8(text):
        raise SessionSettingsError("the hooks hold text that is not UTF-8")
    return (text + "\n").encode("utf-8"), tuple(dict.fromkeys(scripts))


def _rewritten(
    value: JsonValue, *, event: str, prefix: str, scripts: list[str], is_command: bool
) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _rewritten(
                item, event=event, prefix=prefix, scripts=scripts, is_command=key == "command"
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewritten(item, event=event, prefix=prefix, scripts=scripts, is_command=False)
            for item in value
        ]
    if is_command and isinstance(value, str):
        _check_command(value, event=event)
        scripts.extend(_SCRIPT.findall(value))
        return value.replace(PROJECT_DIR, prefix)
    return value


def _check_command(command: str, *, event: str) -> None:
    where = f"a {json.dumps(event)} hook command"
    if not _is_utf8(command):
        raise HookCommandError(f"{where} is not UTF-8 text")
    uses = {found.start() for found in re.finditer(re.escape(PROJECT_DIR), command)}
    if not uses <= _double_quoted_uses(command):
        raise HookCommandError(f"{where} uses {PROJECT_DIR} outside double quotes")
    if _VARIABLE_NAME in command.replace(PROJECT_DIR, ""):
        raise HookCommandError(f"{where} names {_VARIABLE_NAME} other than as {PROJECT_DIR}")


def _double_quoted_uses(command: str) -> set[int]:
    # Where ``$CLAUDE_PROJECT_DIR/`` starts as an expansion inside double quotes, read the way
    # a POSIX shell reads quotes and backslashes. Anything nested (``"$(echo "…")"``) is read
    # as closing the quote, so it counts as unquoted: refused, never trusted.
    found: set[int] = set()
    quoted = False
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\":
            index += 2  # the next character is taken literally
            continue
        if character == "'" and not quoted:
            # A single-quoted span ends at the next quote, with nothing expanded in it.
            end = command.find("'", index + 1)
            index = len(command) if end < 0 else end + 1
            continue
        if character == '"':
            quoted = not quoted
        elif quoted and command.startswith(PROJECT_DIR, index):
            found.add(index)
        index += 1
    return found


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
