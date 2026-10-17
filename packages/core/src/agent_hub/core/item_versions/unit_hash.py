"""A unit's content hash (AGH-295, S2), ``sha256:<hex>``.

A file unit hashes its bytes. A folder unit hashes the sorted lines
``<relative path> NUL <x or -> NUL <sha256 hex of the file>``, each ending in a newline, so the
same bytes and executable bits give the same hash whatever the order they were read in, and a
modification time alone never changes it.
"""

import hashlib
from collections.abc import Iterable
from typing import Final

from agent_hub.core.item_versions.unit_content import UnitFile

PREFIX: Final = "sha256:"


def file_hash(content: bytes) -> str:
    """The hash of a file unit's bytes."""
    return PREFIX + hashlib.sha256(content).hexdigest()


def folder_hash(files: Iterable[UnitFile]) -> str:
    """The hash of a folder unit's files, by path, bit and bytes."""
    lines = sorted(
        "\0".join(
            (
                file.path,
                "x" if file.executable else "-",
                hashlib.sha256(file.content).hexdigest(),
            )
        )
        + "\n"
        for file in files
    )
    return PREFIX + hashlib.sha256("".join(lines).encode()).hexdigest()
