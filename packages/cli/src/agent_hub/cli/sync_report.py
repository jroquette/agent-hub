"""What ``hub sync`` prints: one line per change, or each conflict with its diff or cause.

A plan gives one line per changed path, sorted by path, then the leftover count, then
``updated hub.lock`` last (spec Q-1); ``--check`` puts ``would`` before each verb (Q-2); nothing
to do is exactly ``up to date``. A conflict is a unified diff of the file on disk against its
render, capped per path, or a binary line with both digests, or ``<path>: <cause>``; the report
ends with ADR 0009's way out (Q-4, plan erratum E13). Paths go through ``shown_path``, and a
line holding an unprintable character (a tab aside, in diff lines) is shown as a JSON string.
"""

import difflib
import hashlib
import json
from collections.abc import Iterable, Iterator
from typing import Final

from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.core.hub_files.plan_adopt import AdoptPlan
from agent_hub.core.hub_files.plan_sync import (
    ContentConflict,
    SyncConflicts,
    SyncPlan,
    SyncProblem,
    Verb,
)

UP_TO_DATE: Final = "up to date"
CONFLICT_WAY_OUT: Final = (
    "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
    " restore or delete the file, then re-run hub sync"
)
# The diff lines shown per path, its labels and hunk headers included.
MAX_DIFF_LINES: Final = 200
DIGEST_SHOWN: Final = 12
_CONTEXT_LINES: Final = 3
_LABEL_LINES: Final = 2
_NO_NEWLINE: Final = "\\ No newline at end of file"
_WOULD: Final = {
    Verb.CREATED: "would create",
    Verb.RESTORED: "would restore",
    Verb.UPDATED: "would update",
    Verb.DELETED: "would delete",
    Verb.RECORDED: "would record",
    Verb.MIGRATED: "would migrate",
}


def change_lines(plan: SyncPlan | AdoptPlan, *, check: bool) -> list[str]:
    """What a sync that applies ``plan`` prints, or would print with ``check``."""
    if not plan.pending:
        return [UP_TO_DATE]
    lines = [
        f"{_WOULD[change.verb] if check else change.verb} {shown_path(change.path)}"
        for change in sorted(plan.changes, key=lambda change: change.path)
    ]
    if plan.leftovers:
        removed = "would remove" if check else "removed"
        lines.append(f"{removed} {len(plan.leftovers)} leftover temporary files")
    if plan.lock_written:
        lines.append(f"{'would update' if check else 'updated'} {HUB_LOCK_PATH}")
    return lines


def conflict_lines(conflicts: SyncConflicts) -> list[str]:
    """Each conflicted path in order, with its diff, binary line or cause; then the way out."""
    return [*problem_lines(conflicts.problems), CONFLICT_WAY_OUT]


def problem_lines(problems: Iterable[SyncProblem]) -> list[str]:
    """Each of ``problems`` in the given order, with its diff, binary line or cause."""
    lines: list[str] = []
    for problem in problems:
        if isinstance(problem, ContentConflict):
            lines.extend(_content_lines(problem))
        else:
            lines.append(shown_text(f"{shown_path(problem.path)}: {problem.message}"))
    return lines


def is_text(content: bytes) -> str | None:
    """``content`` as text, or ``None`` when it is not UTF-8 or holds a NUL (binary)."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\0" in text else text


def _content_lines(conflict: ContentConflict) -> list[str]:
    path = shown_path(conflict.path)
    on_disk, render = is_text(conflict.on_disk), is_text(conflict.render)
    if on_disk is None or render is None:
        disk_digest = hashlib.sha256(conflict.on_disk).hexdigest()[:DIGEST_SHOWN]
        render_digest = hashlib.sha256(conflict.render).hexdigest()[:DIGEST_SHOWN]
        digests = f"on disk sha256 {disk_digest}, render {render_digest}"
        return [f"{path}: binary content differs ({digests})"]
    lines = list(_diff(on_disk, render, path=path))
    if len(lines) <= MAX_DIFF_LINES:
        return lines
    return [*lines[:MAX_DIFF_LINES], f"… {len(lines) - MAX_DIFF_LINES} more lines"]


def split_lines(text: str) -> list[str]:
    r"""``text`` split on ``"\n"`` only, each line with its end: a ``"\r"`` stays visible, and so
    does a missing last newline."""
    parts = text.split("\n")
    return [f"{part}\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _diff(on_disk: str, render: str, *, path: str) -> Iterator[str]:
    diff = difflib.unified_diff(
        split_lines(on_disk),
        split_lines(render),
        fromfile=f"{path} (on disk)",
        tofile=f"{path} (render)",
        n=_CONTEXT_LINES,
        lineterm="",
    )
    for number, line in enumerate(diff):
        # The two labels and each "@@" header come without a line end; a content line has one
        # unless it is the last line of a file that lacks it.
        if number < _LABEL_LINES or line.startswith("@@"):
            yield line
        elif line.endswith("\n"):
            yield _shown_diff_line(line.removesuffix("\n"))
        else:
            yield _shown_diff_line(line)
            yield _NO_NEWLINE


def _shown_diff_line(line: str) -> str:
    # Tabs are common in templates (Makefile recipes) and cannot fake a line: shown as is.
    return line if line.replace("\t", " ").isprintable() else json.dumps(line)
