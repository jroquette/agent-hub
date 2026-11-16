"""The task's port slot and offset, computed from the worktree name alone.

The slot is stateless and deterministic: SHA-256 of the name's UTF-8 bytes, read as one big-endian
integer, modulo ``SLOT_COUNT``. It never uses Python's ``hash()``, which is salted per process, so
the same name gives the same slot in every process, machine and repo. The slot is not unique: two
names share one with probability 1/50, and nothing allocates or locks it.
"""

import hashlib
from typing import Final

SLOT_COUNT: Final = 50
PORT_STEP: Final = 100


def worktree_slot(name: str) -> int:
    """Return the slot of the worktree ``name``, in ``range(SLOT_COUNT)``."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % SLOT_COUNT


def port_offset(slot: int) -> int:
    """Return the port offset of ``slot``: ``slot`` times ``PORT_STEP``."""
    return slot * PORT_STEP
