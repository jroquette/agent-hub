"""The one env-file loader: an environment's ``credentials.env_file`` read when an action starts
(docs/design/scenarios.md § Credentials, ADR 0041).

``hub action run`` and the engine's action executor both call ``load_env_file``; nothing else
reads the file, and plan mode never does. The path is relative to the workspace (the folder
holding the hub and its repos); its real path must stay inside the workspace, so a link may
point within it but never out. The file is opened without following a last link, never
blocking (a FIFO is refused, not waited on), must be a regular file of at most
``MAX_ENV_FILE_BYTES``, is read once into memory and parsed by core's dotenv grammar. Any
problem refuses the action before its process starts with ``environment <env>: env file
<path> is <reason>``: the path as configured and a reason, never a value.
"""

import errno
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.scenarios.env_file import MAX_ENV_FILE_BYTES, EnvFileError, parse_env_file

_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class EnvFileLoadError(AgentHubError):
    """An env file the action cannot use, as one plain line without a value."""


def load_env_file(workspace: Path, relative: str, *, environment: str) -> dict[str, str]:
    """The variables of ``environment``'s env file ``relative`` (to ``workspace``); raises
    ``EnvFileLoadError`` when it is missing, unreadable, too large, not a regular file,
    outside the workspace or not a dotenv file."""

    def refused(reason: str) -> EnvFileLoadError:
        return EnvFileLoadError(f"environment {environment}: env file {relative} is {reason}")

    root = os.path.realpath(workspace)
    real = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([root, real]) != root:
        raise refused("outside the workspace")
    content = _read(real, refused)
    try:
        return parse_env_file(content)
    except EnvFileError as error:
        raise refused(error.reason) from None


def _read(path: str, refused: Callable[[str], EnvFileLoadError]) -> bytes:
    try:
        descriptor = os.open(path, _FLAGS)
    except FileNotFoundError, NotADirectoryError:
        raise refused("missing") from None
    except OSError as error:
        # ELOOP: a link swapped in after the real path was taken.
        reason = "not a regular file" if error.errno == errno.ELOOP else "unreadable"
        raise refused(reason) from None
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
