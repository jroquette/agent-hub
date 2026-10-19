"""The hooks-only ``--settings`` file of a ``claude -p`` session whose cwd is a repo (AGH-278).

A session in the hub loads the hub's ``.claude/settings.json`` itself; one in a repo does not,
so it gets a file built from it: ``effortLevel`` and the hub's ``hooks`` block, nothing else
(no ``permissions``, ``sandbox``, ``env`` or ``enabledPlugins``). Events, groups and entries
keep their order. In every string under a ``command`` key, ``$CLAUDE_PROJECT_DIR/`` becomes
the hub's path and ``/``, since Claude Code sets that variable to the session's cwd (the repo);
``${CLAUDE_PROJECT_DIR}`` and a bare ``$CLAUDE_PROJECT_DIR`` are left as written. The same
source, effort and hub path always give the same bytes.
"""

import json
import re
from typing import Final, cast

from agent_hub.core.json_form import JsonValue

PROJECT_DIR: Final = "$CLAUDE_PROJECT_DIR/"
# The hub-relative path a command names after the variable, up to a quote or a space.
_SCRIPT: Final = re.compile(r"\$CLAUDE_PROJECT_DIR/([^\"'\s]+)")


def hooks_settings(source: JsonValue, *, effort: str, hub: str) -> tuple[bytes, tuple[str, ...]]:
    """The settings file's bytes for ``effort``, and the hub-relative scripts its commands name.

    ``source`` is the hub's parsed ``.claude/settings.json`` and ``hub`` the hub's path. The
    scripts are listed in the order first seen, each once.
    """
    hooks = cast(dict[str, JsonValue], source)["hooks"]
    scripts: list[str] = []
    built = _rewritten(hooks, prefix=f"{hub}/", scripts=scripts, is_command=False)
    text = json.dumps({"effortLevel": effort, "hooks": built}, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8"), tuple(dict.fromkeys(scripts))


def _rewritten(value: JsonValue, *, prefix: str, scripts: list[str], is_command: bool) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _rewritten(item, prefix=prefix, scripts=scripts, is_command=key == "command")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewritten(item, prefix=prefix, scripts=scripts, is_command=False) for item in value]
    if is_command and isinstance(value, str):
        scripts.extend(_SCRIPT.findall(value))
        return value.replace(PROJECT_DIR, prefix)
    return value
