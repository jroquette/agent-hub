"""Unified diffs of the file tools' calls (AC-165.31): what an ``Edit`` or ``Write`` changes.

Pure, over the tool's input only (never the file on disk): ``edit_diff`` compares
``old_string`` with ``new_string``, ``write_diff`` shows the written content as all added.
Headers are git's (``a/<path>``, ``b/<path>``, ``/dev/null`` for a new file), every line ends in
a newline, and a diff over ``limit`` UTF-8 bytes keeps its first whole lines and ends with a
line saying how big it was.
"""

import difflib
from collections.abc import Iterable
from typing import Final

from agent_hub.core.agent_sessions.limits import KIB

DIFF_MAX_BYTES: Final = 64 * KIB


def edit_diff(path: str, old: str, new: str, *, limit: int = DIFF_MAX_BYTES) -> str:
    """The diff of an edit that replaces ``old`` with ``new`` in ``path``; empty when equal."""
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return _capped(lines, limit)


def write_diff(path: str, content: str, *, limit: int = DIFF_MAX_BYTES) -> str:
    """The diff of writing ``content`` to ``path``: every line added."""
    lines = difflib.unified_diff(
        [], content.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{path}"
    )
    return _capped(lines, limit)


def _capped(lines: Iterable[str], limit: int) -> str:
    whole = [line if line.endswith("\n") else line + "\n" for line in lines]
    size = sum(len(line.encode()) for line in whole)
    if size <= limit:
        return "".join(whole)
    note = f"... diff truncated ({size} bytes)\n"
    budget = limit - len(note.encode())
    kept: list[str] = []
    for line in whole:
        budget -= len(line.encode())
        if budget < 0:
            break
        kept.append(line)
    return "".join(kept) + note
