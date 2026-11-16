"""Unified diffs of the file tools' calls (AC-165.31): what an ``Edit`` or ``Write`` changes.

``patch_diff`` renders the hunks the engine reports once a file tool ran (its
``structuredPatch``): the same format, with the file's real line numbers.

Pure, over the tool's input only (never the file on disk): ``edit_diff`` compares
``old_string`` with ``new_string``, ``write_diff`` shows the written content as all added.
Headers are git's (``a/<path>``, ``b/<path>``, ``/dev/null`` for a new file), every line ends in
a newline, and a diff over ``limit`` UTF-8 bytes keeps its first whole lines and ends with a
line saying how big it was.

``difflib`` is quadratic at worst, so an input over ``INPUT_MAX_BYTES`` UTF-8 bytes (old and new
together) or ``INPUT_MAX_LINES`` lines is never compared: the diff is its headers and one
``OMITTED_LINE``. The use case runs a diff whose input passes ``OFF_LOOP_BYTES`` off the event
loop.
"""

import difflib
from collections.abc import Iterable
from typing import Final

from agent_hub.core.agent_sessions.limits import KIB

DIFF_MAX_BYTES: Final = 64 * KIB
INPUT_MAX_BYTES: Final = 256 * KIB
INPUT_MAX_LINES: Final = 5_000
OFF_LOOP_BYTES: Final = 16 * KIB
OMITTED_LINE: Final = "... diff omitted ({size} bytes)\n"


def edit_diff(path: str, old: str, new: str, *, limit: int = DIFF_MAX_BYTES) -> str:
    """The diff of an edit that replaces ``old`` with ``new`` in ``path``; empty when equal."""
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    fromfile, tofile = f"a/{path}", f"b/{path}"
    size = len(old.encode()) + len(new.encode())
    if _over_bound(size, len(old_lines) + len(new_lines)):
        return _omitted(fromfile, tofile, size)
    lines = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile)
    return _capped(lines, limit)


def write_diff(path: str, content: str, *, limit: int = DIFF_MAX_BYTES) -> str:
    """The diff of writing ``content`` to ``path``: every line added."""
    new_lines = content.splitlines(keepends=True)
    size = len(content.encode())
    if _over_bound(size, len(new_lines)):
        return _omitted("/dev/null", f"b/{path}", size)
    lines = difflib.unified_diff([], new_lines, fromfile="/dev/null", tofile=f"b/{path}")
    return _capped(lines, limit)


def patch_diff(path: str, hunks: object, *, limit: int = DIFF_MAX_BYTES) -> str | None:
    """The diff of ``hunks`` (``[{oldStart, oldLines, newStart, newLines, lines}]``) in
    ``path``, with the file's line numbers; None when they are not that shape or empty."""
    if not isinstance(hunks, list) or not hunks:
        return None
    out = [f"--- a/{path}", f"+++ b/{path}"]
    for hunk in hunks:
        if not isinstance(hunk, dict):
            return None
        numbers = [hunk.get(key) for key in ("oldStart", "oldLines", "newStart", "newLines")]
        lines = hunk.get("lines")
        if not all(type(n) is int and n >= 0 for n in numbers) or not isinstance(lines, list):
            return None
        if not all(isinstance(line, str) for line in lines):
            return None
        old_start, old_lines, new_start, new_lines = numbers
        out.append(f"@@ -{old_start},{old_lines} +{new_start},{new_lines} @@")
        out.extend(lines)
    return _capped(out, limit)


def _over_bound(size: int, line_count: int) -> bool:
    return size > INPUT_MAX_BYTES or line_count > INPUT_MAX_LINES


def _omitted(fromfile: str, tofile: str, size: int) -> str:
    return f"--- {fromfile}\n+++ {tofile}\n" + OMITTED_LINE.format(size=size)


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
