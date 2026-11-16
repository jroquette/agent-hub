"""The hub's cache folder, ``.hub-cache``: how ``hub brief --write-cache`` and ``hub digest`` write
a file there, and how a reader reads one back.

``write_hub_cache`` makes the folder when missing (owner-only), with its own ``.gitignore``
(``*``) first (rewritten whole when it holds anything else), and refuses it when it is a link or
not a folder; the file is replaced atomically with the mode given, so a reader never sees a
partial write. ``read_hub_cache`` reads a regular file there, never through a link, of at most
``limit`` bytes; anything else is no file.
"""

import os
import stat
from pathlib import Path
from typing import Final

from agent_hub.cli.command_exits import fail
from agent_hub.cli.exclusive_write import write_replacing
from agent_hub.core.workspace.brief_cache import CACHE_FOLDER, GITIGNORE_FILE, GITIGNORE_TEXT

CACHE_FOLDER_MODE: Final = 0o700


def write_hub_cache(root: Path, name: str, document: bytes, *, mode: int) -> None:
    """Write ``document`` as ``.hub-cache/<name>`` in ``root``, or exit 1 with one stderr line."""
    folder = root / CACHE_FOLDER
    problem = _cache_folder_problem(folder)
    if problem is not None:
        fail(f"{CACHE_FOLDER}: {problem}; cache not written")
    try:
        _write_ignore_rule(folder)
        write_replacing(folder, name, document, mode=mode)
    except OSError as error:
        fail(f"{CACHE_FOLDER}: cannot write: {error.strerror or type(error).__name__}")


def read_hub_cache(root: Path, name: str, limit: int) -> bytes | None:
    """``.hub-cache/<name>`` in ``root``; None when the folder or the file is a link, the file is
    not a regular one, is larger than ``limit`` bytes or cannot be read."""
    folder = root / CACHE_FOLDER
    try:
        if not stat.S_ISDIR(os.lstat(folder).st_mode):
            return None
    except OSError:
        return None
    data = _small_file(folder / name, limit + 1)
    if data is None or len(data) > limit:
        return None
    return data


def _write_ignore_rule(folder: Path) -> None:
    """The folder's ``.gitignore``, written first so its rule covers the cache.

    Published whole with ``os.replace`` unless it already holds ``GITIGNORE_TEXT``, so it is
    never seen partial and an empty or changed one (a killed hook's) is repaired. Only a run
    killed before the rule's first publish can leave its temp in git status; the next run
    publishes the rule, which then hides that temp too. Raises ``OSError``.
    """
    rule = GITIGNORE_TEXT.encode()
    if _small_file(folder / GITIGNORE_FILE, len(rule) + 1) != rule:
        write_replacing(folder, GITIGNORE_FILE, rule, mode=0o644)


def _small_file(path: Path, limit: int) -> bytes | None:
    """At most ``limit`` bytes of a regular file, never through a link or from a FIFO."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        return os.read(descriptor, limit)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _cache_folder_problem(folder: Path) -> str | None:
    """Make ``folder`` when missing; why it cannot hold the cache (a link, not a folder)."""
    try:
        os.mkdir(folder, CACHE_FOLDER_MODE)
    except FileExistsError:
        pass
    except OSError as error:
        return f"cannot create: {error.strerror or type(error).__name__}"
    try:
        mode = os.lstat(folder).st_mode
    except OSError as error:
        return f"cannot read: {error.strerror or type(error).__name__}"
    if stat.S_ISLNK(mode):
        return "is a symlink"
    if not stat.S_ISDIR(mode):
        return "is not a folder"
    return None
