"""Publish a new file once, never over another: how ``hub setup`` writes ``hub.local.json``.

The bytes go to a temp file in the same folder, created for this call only, and a hard link
then gives them the final name. A link never replaces an entry, so a file that is already
there, or that appears meanwhile, is kept exactly as it is, and the name never holds a
partial write. After the link the folder is synced, so the name survives a crash.
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

    False only when the name existed at the moment of the link (before the call or appearing
    while it runs): that entry is left as it is. Any other ``OSError`` (the folder is not
    writable, a file system without hard links, a clash on the temp name) is raised, even when
    the name also exists; its message names paths, so a caller shows only its ``strerror``.
    Once the link is made, nothing turns the True into an error: syncing the folder and
    removing the temp are best effort.
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
        _sync_folder(folder)
        return True
    finally:
        # Cleanup never decides the outcome: after the link the file is published; before it,
        # the error being raised (or the False) is what the caller must see, not the unlink's.
        with contextlib.suppress(OSError):
            os.unlink(temp)


def _sync_folder(folder: Path) -> None:
    """Make the new name durable, best effort: some file systems cannot sync a folder."""
    with contextlib.suppress(OSError):
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
