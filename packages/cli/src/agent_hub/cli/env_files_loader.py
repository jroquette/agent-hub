"""The one env-file loader: an environment's ``credentials.env_file`` read when an action starts
(docs/design/scenarios.md § Credentials, ADR 0041).

``hub action run`` and the engine's action executor both call ``load_env_file``; nothing else
reads the file, and plan mode never does. The path is relative to the workspace (the folder
holding the hub and its repos) and must lie, by its real path, inside the hub or one of the
repos ``hub.json`` declares (``roots``, workspace-relative), never elsewhere in the workspace.
It is then opened from the root's folder one component at a time, each with ``O_NOFOLLOW``
and ``dir_fd``, so no link on the way is followed, even one swapped in after the real path was
checked; the last open never blocks (a FIFO is refused, not waited on). The file must be a
regular file of at most ``MAX_ENV_FILE_BYTES``; it is read once into memory and parsed by
core's dotenv grammar. Any problem refuses the action before its process starts with
``environment <env>: env file <path> is <reason>``: the path as configured and a reason,
never a value.
"""

import errno
import os
import stat
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.scenarios.env_file import MAX_ENV_FILE_BYTES, EnvFileError, parse_env_file

_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
LINK_REASON: Final = "reached through a link"


class EnvFileLoadError(AgentHubError):
    """An env file the action cannot use, as one plain line without a value."""


def load_env_file(
    workspace: Path, relative: str, *, roots: Sequence[str], environment: str
) -> dict[str, str]:
    """The variables of ``environment``'s env file ``relative`` (to ``workspace``), which must
    be inside one of ``roots`` (the hub's and the repos' folders); raises ``EnvFileLoadError``
    when it is missing, unreadable, too large, not a regular file, outside the workspace,
    outside the hub and its repos or not a dotenv file."""

    def refused(reason: str) -> EnvFileLoadError:
        return EnvFileLoadError(f"environment {environment}: env file {relative} is {reason}")

    root = os.path.realpath(workspace)
    real = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([root, real]) != root:
        raise refused("outside the workspace")
    found = _root_of(root, relative, real, roots=roots)
    if found is None:
        raise refused("outside the hub and its repos")
    content = _read(_open_file(root, found, relative, refused=refused), refused)
    try:
        return parse_env_file(content)
    except EnvFileError as error:
        raise refused(error.reason) from None


def _root_of(workspace: str, relative: str, real: str, *, roots: Sequence[str]) -> str | None:
    """The root ``relative`` names as its leading folders and whose real path holds ``real``,
    the deepest when roots nest; ``None`` when there is none."""
    parts = PurePosixPath(relative).parts
    found = None
    for candidate in roots:
        prefix = PurePosixPath(candidate).parts
        if not prefix or parts[: len(prefix)] != prefix or len(parts) <= len(prefix):
            continue
        folder = os.path.realpath(os.path.join(workspace, *prefix))
        if os.path.commonpath([folder, real]) == folder and (
            found is None or len(prefix) > len(PurePosixPath(found).parts)
        ):
            found = candidate
    return found


def _open_file(
    workspace: str, root: str, relative: str, *, refused: Callable[[str], EnvFileLoadError]
) -> int:
    """A descriptor of the file, opened from ``root``'s folder component by component."""
    parts = PurePosixPath(relative).parts[len(PurePosixPath(root).parts) :]
    try:
        folder = os.open(os.path.join(workspace, root), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as error:
        raise refused(_reason(error)) from None
    try:
        for part in parts[:-1]:
            try:
                inner = os.open(part, _FOLDER_FLAGS, dir_fd=folder)
            except OSError as error:
                raise refused(_reason(error, part=part, folder=folder)) from None
            os.close(folder)
            folder = inner
        try:
            return os.open(parts[-1], _FLAGS, dir_fd=folder)
        except OSError as error:
            raise refused(_reason(error, part=parts[-1], folder=folder)) from None
    finally:
        os.close(folder)


def _reason(error: OSError, *, part: str | None = None, folder: int | None = None) -> str:
    """Why ``part`` (in ``folder``) could not be opened, in plain words."""
    if error.errno == errno.ELOOP or (
        error.errno == errno.ENOTDIR and part is not None and _is_link(part, folder)
    ):
        return LINK_REASON
    if isinstance(error, FileNotFoundError | NotADirectoryError):
        return "missing"
    return "unreadable"


def _is_link(part: str, folder: int | None) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(part, dir_fd=folder).st_mode)
    except OSError:
        return False


def _read(descriptor: int, refused: Callable[[str], EnvFileLoadError]) -> bytes:
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise refused("not a regular file")
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_ENV_FILE_BYTES and (chunk := os.read(descriptor, 65536)):
            chunks.append(chunk)
            size += len(chunk)
    except OSError:
        raise refused("unreadable") from None
    finally:
        os.close(descriptor)
    if size > MAX_ENV_FILE_BYTES:
        raise refused("too large")
    return b"".join(chunks)
