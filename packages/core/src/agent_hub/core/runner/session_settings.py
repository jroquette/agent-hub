"""The hooks-only ``--settings`` file of a ``claude -p`` session whose cwd is a repo (AGH-278).

A session in the hub loads the hub's ``.claude/settings.json`` itself; one in a repo does not,
so it gets a file built from it: ``effortLevel`` and the hub's ``hooks`` block, nothing else
(no ``permissions``, ``sandbox``, ``env`` or ``enabledPlugins``). Events, groups and entries
keep their order. In every string under a ``command`` key, ``$CLAUDE_PROJECT_DIR/`` becomes
the hub's path and ``/``, since Claude Code sets that variable to the session's cwd (the repo).
The same source, effort and hub path always give the same bytes.

A command is accepted only when it is plain words plus whole words of exactly the form
``"$CLAUDE_PROJECT_DIR/<path>"`` (``<path>`` of letters, digits and ``._/@+-``), as every hub
hook command is (spec AM-1). Once those words are set aside, any quote, backtick, ``\\``,
``$``, ``#``, ``<<`` or ``CLAUDE_PROJECT_DIR`` left refuses the command: an allow-list, so no
shell form (``${CLAUDE_PROJECT_DIR}``, ANSI-C quotes, substitutions, comments, heredocs) can
reach the repo or run the hub's path as syntax. Each rewritten word stays one plain
double-quoted word, where only ``"``, ``$``, a backtick and ``\\`` are not literal: a hub path
holding one of them is refused, as is a hub path or a command that is not UTF-8 text.
"""

import json
import re
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue

PROJECT_DIR: Final = "$CLAUDE_PROJECT_DIR/"
_VARIABLE_NAME: Final = "CLAUDE_PROJECT_DIR"
# The one word a command may use the variable in, whole: its group is the hub-relative path.
_PROJECT_WORD: Final = re.compile(r'(?<!\S)"\$CLAUDE_PROJECT_DIR/([A-Za-z0-9._/@+-]*)"(?!\S)')
# What, outside those words, could quote, expand, comment or redirect.
_REFUSED_CHARACTERS: Final = frozenset("'\"`\\$#")
_REFUSED_TEXTS: Final = ("<<", _VARIABLE_NAME)
_SHOWN_CHARS: Final = 120
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
        event: _rewritten(groups, event=event, hub_dir=f"{hub}/", scripts=scripts, is_command=False)
        for event, groups in hooks.items()
    }
    text = json.dumps({"effortLevel": effort, "hooks": built}, indent=2, ensure_ascii=False)
    if not _is_utf8(text):
        raise SessionSettingsError("the hooks hold text that is not UTF-8")
    return (text + "\n").encode("utf-8"), tuple(dict.fromkeys(scripts))


def _rewritten(
    value: JsonValue, *, event: str, hub_dir: str, scripts: list[str], is_command: bool
) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _rewritten(
                item, event=event, hub_dir=hub_dir, scripts=scripts, is_command=key == "command"
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewritten(item, event=event, hub_dir=hub_dir, scripts=scripts, is_command=False)
            for item in value
        ]
    if is_command and isinstance(value, str):
        _check_command(value, event=event)
        scripts.extend(path for path in _PROJECT_WORD.findall(value) if path)
        return _PROJECT_WORD.sub(lambda word: f'"{hub_dir}{word.group(1)}"', value)
    return value


def _check_command(command: str, *, event: str) -> None:
    where = f"a {_shown_event(event)} hook command"
    if not _is_utf8(command):
        raise HookCommandError(f"{where} is not UTF-8 text")
    rest = _PROJECT_WORD.sub(" ", command)
    if _REFUSED_CHARACTERS.intersection(rest) or any(text in rest for text in _REFUSED_TEXTS):
        raise HookCommandError(f'{where} must use only "{PROJECT_DIR}<path>" and plain words')


def _shown_event(event: str) -> str:
    # The event name comes from a file a session can write: shown quoted and cut at its cap.
    cut = event[:_SHOWN_CHARS]
    return json.dumps(cut if cut == event else f"{cut}...")


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
