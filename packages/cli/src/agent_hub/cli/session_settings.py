"""The hooks-only ``--settings`` file of a session whose cwd is a repo: read, check, write (AGH-278).

``hub_hooks_settings`` reads the hub's ``.claude/settings.json`` (at most ``MAX_SETTINGS_BYTES``:
it sits in a folder a session can write), builds the file with core's ``hooks_settings`` and
checks that each hook script it names is a regular file in the hub. ``write_session_settings``
writes the result to ``session_settings_path``, ``<hub>/.agent-runs/session-settings/<effort>.json``:
one path per hub and effort, so the dry run can name the path a live run writes. Every problem
is a ``HubHooksError`` of one line naming the file.
"""

import os
from pathlib import Path
from typing import Final

from agent_hub.cli.errors import CliError
from agent_hub.cli.init_report import shown_path
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.core.runner.session_settings import HUB_PATH_PROBLEM, NO_HOOKS, hooks_settings
from agent_hub.generator.hub_config_files import UnreadFile, read_file_bytes

SETTINGS_FOLDER: Final = (".agent-runs", "session-settings")
MAX_SETTINGS_BYTES: Final = 1 << 20
_HUB_SETTINGS: Final = (".claude", "settings.json")


class HubHooksError(CliError):
    """The hub's hooks cannot be given to a session; the text is one line naming the file."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"cannot wire the hub's hooks: {reason}")


def session_settings_path(hub: Path, effort: str) -> Path:
    """Where the settings file for ``effort`` lives in ``hub``."""
    return hub.joinpath(*SETTINGS_FOLDER, f"{effort}.json")


def hub_hooks_settings(hub: Path, effort: str) -> bytes:
    """The settings file's bytes for ``effort``, built from ``hub``'s settings; nothing is written.

    Raises ``HubHooksError`` when the hub's settings are missing, unreadable, too large, not JSON
    or hold no ``hooks`` object, when a hook script they name is not a regular file in the hub,
    or when the hub's path holds a shell character.
    """
    path = hub.joinpath(*_HUB_SETTINGS)
    shown = shown_path(str(path))
    content = read_file_bytes(path, max_bytes=MAX_SETTINGS_BYTES)
    if isinstance(content, UnreadFile):
        raise HubHooksError(
            f"{shown} is missing" if content.is_missing else content.problem.message
        )
    try:
        source = load_json_bytes(content)
    except InvalidJsonError as error:
        raise HubHooksError(f"{shown}: {error.message}") from None
    try:
        built, scripts = hooks_settings(source, effort=effort, hub=str(hub))
    except ValueError as error:
        if str(error) == NO_HOOKS:
            raise HubHooksError(f"{shown}: {NO_HOOKS}") from None
        raise HubHooksError(f"{HUB_PATH_PROBLEM}: {shown_path(str(hub))}") from None
    root = os.path.normpath(hub)
    for script in scripts:
        found = os.path.normpath(hub / script)
        if os.path.commonpath((root, found)) != root or not os.path.isfile(found):
            raise HubHooksError(f"{shown_path(found)} is missing")
    return built


def write_session_settings(hub: Path, effort: str) -> Path:
    """Write the settings file for ``effort`` in ``hub`` and return its path."""
    raise NotImplementedError
