"""The hooks-only ``--settings`` file of a session whose cwd is a repo: read, check, write (AGH-278).

``hub_hooks_settings`` reads the hub's ``.claude/settings.json`` (at most ``MAX_SETTINGS_BYTES``:
it sits in a folder a session can write), builds the file with core's ``hooks_settings`` and
checks that each hook script it names is a regular file in the hub. ``write_session_settings``
writes the result to ``session_settings_path``, ``<hub>/.agent-runs/session-settings/<effort>.json``:
one path per hub and effort, so the dry run can name the path a live run writes. Every problem
is a ``HubHooksError`` of one line naming the file.
"""

import contextlib
import os
import secrets
from pathlib import Path
from typing import Final

from agent_hub.cli.errors import CliError
from agent_hub.cli.exclusive_write import TEMP_INFIX
from agent_hub.cli.init_report import shown_path
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes
from agent_hub.core.runner.session_settings import HUB_PATH_PROBLEM, NO_HOOKS, hooks_settings
from agent_hub.generator.hub_config_files import UnreadFile, read_file_bytes

SETTINGS_FOLDER: Final = (".agent-runs", "session-settings")
MAX_SETTINGS_BYTES: Final = 1 << 20
_HUB_SETTINGS: Final = (".claude", "settings.json")
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
# O_EXCL: the temp is this call's own; O_NOFOLLOW: never through a planted link.
_TEMP_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


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
    """Write the settings file for ``effort`` in ``hub`` and return its path.

    The file is 0600 and each folder made for it 0700. The bytes go to a temp file that then
    replaces the name, so a session starting meanwhile reads the old file or the new one, never
    a partial one. A linked folder on the way is refused; a link at the file's name is replaced,
    never followed. Raises ``HubHooksError`` for what ``hub_hooks_settings`` refuses, and
    ``cannot write <path>: <reason>`` when the write fails.
    """
    content = hub_hooks_settings(hub, effort)
    path = session_settings_path(hub, effort)
    try:
        _replace_file(hub, path.name, content)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise HubHooksError(f"cannot write {shown_path(str(path))}: {reason}") from None
    return path


def _replace_file(hub: Path, name: str, content: bytes) -> None:
    folder = os.open(hub, _FOLDER_FLAGS)
    try:
        for part in SETTINGS_FOLDER:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=folder)
            # O_NOFOLLOW: a folder replaced by a link is refused, never walked through.
            child = os.open(part, _FOLDER_FLAGS | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = child
        temp = f".{name}{TEMP_INFIX}{secrets.token_hex(4)}"
        descriptor = os.open(temp, _TEMP_FLAGS, 0o600, dir_fd=folder)
        try:
            with os.fdopen(descriptor, "wb") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(content)
            # Replaces the entry itself: a planted link is dropped, its target left as it was.
            os.replace(temp, name, src_dir_fd=folder, dst_dir_fd=folder)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp, dir_fd=folder)
            raise
    finally:
        os.close(folder)
