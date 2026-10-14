"""Read one regular file by name from an open folder: bounded, never through a link.

The file is opened relative to the folder's descriptor with ``O_NOFOLLOW`` (and ``O_NONBLOCK``,
so a FIFO cannot block the read), then checked with ``fstat``: a link, a folder or any other
non-regular file is ``NOT_REGULAR`` and never read. The feature folder reader and the agent
output reader share it.
"""

import errno
import os
import stat
from typing import Final

NOT_REGULAR: Final = "not a regular file"
_FILE_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def read_regular(folder: int, name: str, *, limit: int) -> bytes | str | None:
    """The file's first ``limit`` bytes, its problem, or None when absent."""
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=folder)
    except FileNotFoundError:
        return None
    except OSError as error:
        # ELOOP: the name is a link, never followed.
        return (
            NOT_REGULAR if error.errno == errno.ELOOP else (error.strerror or type(error).__name__)
        )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return NOT_REGULAR
        return _read_at_most(descriptor, limit)
    except OSError as error:
        return error.strerror or type(error).__name__
    finally:
        os.close(descriptor)


def _read_at_most(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    left = limit
    while left > 0:
        chunk = os.read(descriptor, left)
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)
