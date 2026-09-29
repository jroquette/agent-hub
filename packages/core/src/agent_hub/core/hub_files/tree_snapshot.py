"""What a target folder holds before ``hub init`` writes: plain values, no I/O.

The generator's tree reader fills a ``TreeSnapshot`` and never descends into a link, so nothing
under a symlinked folder is ever listed; the init planner decides from the entries alone. The
temporary-file name is defined here once, for the planner, the file adapter and the registry test.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, kw_only=True, slots=True)
class FileEntry:
    """A regular file. ``content`` is read only for the paths the render wants, else ``None``."""

    executable: bool
    content: bytes | None


@dataclass(frozen=True, kw_only=True, slots=True)
class LinkEntry:
    """A symlink, never followed. ``outside`` says whether it resolves outside the hub root."""

    target: str
    outside: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class FolderEntry:
    """A real folder (a link to a folder is a ``LinkEntry``)."""


@dataclass(frozen=True, kw_only=True, slots=True)
class OtherEntry:
    """Anything never opened: ``"fifo"``, ``"socket"``, ``"device"`` or ``"unknown"``."""

    kind: str


type TreeEntry = FileEntry | LinkEntry | FolderEntry | OtherEntry


@dataclass(frozen=True, kw_only=True, slots=True)
class TreeSnapshot:
    """Every entry under the root by relative POSIX path, the root's ``.git`` left out."""

    entries: Mapping[str, TreeEntry]
    git_present: bool


TEMP_NAME: Final = re.compile(r"\..+\.hub-tmp-[0-9a-f]{8}")
_TOKEN: Final = re.compile(r"[0-9a-f]{8}")


def temp_name(final_name: str, token: str) -> str:
    """The temporary name for ``final_name`` in the same folder: ``.<name>.hub-tmp-<token>``."""
    if not _TOKEN.fullmatch(token):
        msg = f"token must be 8 lowercase hex digits, got {token!r}"
        raise ValueError(msg)
    return f".{final_name}.hub-tmp-{token}"


def is_leftover_name(name: str) -> bool:
    """Whether ``name`` (one path segment) has the shape of a temporary file left by a write."""
    return TEMP_NAME.fullmatch(name) is not None
