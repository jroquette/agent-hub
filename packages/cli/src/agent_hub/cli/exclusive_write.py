"""Publish a new file once, never over another: how ``hub setup`` writes ``hub.local.json``.

The bytes go to a temp file in the same folder, created for this call only, and a hard link
then gives them the final name. A link never replaces an entry, so a file that is already
there, or that appears meanwhile, is kept exactly as it is, and the name never holds a
partial write.
"""

import contextlib
import os
import secrets
from pathlib import Path

TEMP_INFIX = ".hub-tmp-"
# O_EXCL: the temp is this call's own; O_NOFOLLOW: never through a planted link.
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def write_exclusive(folder: Path, name: str, content: bytes, *, mode: int = 0o644) -> bool:
    """Write ``content`` as ``folder/name`` with ``mode`` (whatever the umask); True when written.

    False when the name is taken, before the call or while it runs: that entry is left as it
    is. Any other ``OSError`` (a file system without hard links, a read-only folder) is
    raised; its message names paths, so a caller shows only its ``strerror``. The temp file
    never stays.
    """
    temp = folder / f".{name}{TEMP_INFIX}{secrets.token_hex(4)}"
    descriptor = os.open(temp, _TEMP_FLAGS, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), mode)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temp, folder / name)
        except FileExistsError:
            return False
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
