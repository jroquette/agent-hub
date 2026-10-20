"""Where a declared env file is, whether git ignores it, and, for hub web, its variable names.

A path is relative to the workspace, the hub's parent folder. ``locate_env_file`` resolves it by
real path and names the hub's or a declared repo's dir holding it (a link that leads out of them is
outside), with whether git ignores it there; doctor's ``environments.env_file`` reads the same
facts. ``env_file_keys`` reads only a held, regular file of at most ``MAX_ENV_FILE_BYTES`` and keeps
its names: the values are dropped as it is parsed and never leave this function.
"""

import os
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from agent_hub.core.hub_config.env_file_keys import MAX_ENV_FILE_BYTES, EnvFileKeys, dotenv_keys
from agent_hub.generator.git_answers import git_answer

_READ_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC


class LocatedEnvFile(NamedTuple):
    """An env file as found: its real path, whether it exists, its holder and git's answer."""

    real: Path
    exists: bool
    holder: str | None
    ignored: bool | None


def locate_env_file(root: str, repo_dirs: Iterable[str], path: str) -> LocatedEnvFile:
    """``path`` (relative to the workspace) as found, for the hub at ``root`` and its repos."""
    workspace = Path(root).parent
    holders = {
        name: Path(os.path.realpath(workspace / name)) for name in (Path(root).name, *repo_dirs)
    }
    real = Path(os.path.realpath(workspace / path))
    held = next(
        ((name, top) for name, top in holders.items() if real != top and real.is_relative_to(top)),
        None,
    )
    return LocatedEnvFile(
        real=real,
        exists=real.exists(),
        holder=held[0] if held else None,
        ignored=_is_ignored(held[1], real.relative_to(held[1]).as_posix()) if held else None,
    )


def env_file_keys(root: str, repo_dirs: Iterable[str], path: str) -> EnvFileKeys:
    """The facts and variable names of ``path``; names only for a held regular file."""
    found = locate_env_file(root, repo_dirs, path)
    facts = EnvFileKeys(path=path, exists=found.exists, holder=found.holder, ignored=found.ignored)
    if found.holder is None:
        return facts.model_copy(update={"problem": "It is outside the hub and its repos."})
    if not found.exists:
        return facts.model_copy(update={"problem": "No file there yet."})
    content = _read(found.real)
    if isinstance(content, str):
        return facts.model_copy(update={"problem": content})
    keys, truncated = dotenv_keys(content)
    return facts.model_copy(update={"keys": keys, "truncated": truncated})


def _read(real: Path) -> bytes | str:
    """The file's bytes, or why it is not read."""
    try:
        descriptor = os.open(real, _READ_FLAGS)
    except OSError:
        return "It cannot be read."
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        return "It is not a regular file."
    if info.st_size > MAX_ENV_FILE_BYTES:
        os.close(descriptor)
        return "It is too large to list (over 64 KiB)."
    with os.fdopen(descriptor, "rb") as file:
        return file.read(MAX_ENV_FILE_BYTES + 1)


def _is_ignored(checkout: Path, path: str) -> bool | None:
    """Whether git ignores ``path`` in ``checkout`` (a tracked file never is); ``None`` when git
    cannot answer. Any failure, such as a folder that is no git checkout, is "not ignored"."""
    if not _is_folder(checkout):
        return False
    answer = git_answer(("check-ignore", "-q", "--", path), cwd=checkout)
    return None if answer is None else answer[0] == 0


def _is_folder(path: Path) -> bool:
    """Whether ``path`` is a folder (not followed); one that cannot be looked at is left to git."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError, NotADirectoryError:
        return False
    except OSError:
        return True
