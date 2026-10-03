"""What ``hub sync --adopt`` prints beside the change lines: what it lists, and why it refuses.

Each listed path gets one line (spec Q-2): a text file ``P: +a -b lines``, its line counts as
sync's diff counts them, then ``, executable bit differs (on disk +x, render -x)`` when the bit
differs too; a binary file ``P: binary content differs``, with the same bit clause; a link
``P: link target differs (on disk -> X, render -> Y)``; a migration
``P: migration: directory link -> T, rendered as N links``. The conflicts follow, as sync prints
them, then one way out: the listed paths' when nothing conflicts, else one that also names
fixing the conflicts and re-running, which lists a migration a conflict held back. A refused
``--accept`` names each refused path with why. Lines go through ``shown_path`` and ``shown_text``
as sync's do.
"""

import difflib
from typing import Final

from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.cli.sync_report import is_text, problem_lines, split_lines
from agent_hub.core.hub_files.plan_adopt import (
    AdoptPlan,
    AdoptRefusal,
    ContentDifference,
    LinkDifference,
    Listed,
)

ADOPT_LISTED_WAY_OUT: Final = (
    "take the template with --accept <path>, or move the change to an extension file, then re-run"
)
ADOPT_CONFLICT_WAY_OUT: Final = (
    "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
    " restore or delete the conflicting file, or take the template of a listed path with"
    " --accept <path>, then re-run hub sync --adopt"
)


def listing_lines(plan: AdoptPlan) -> list[str]:
    """Each listed path, then each conflict, then the way out; nothing when ``plan`` is settled."""
    if plan.settled:
        return []
    lines = [_listed_line(each) for each in plan.listed]
    lines.extend(problem_lines(plan.conflicts))
    lines.append(ADOPT_CONFLICT_WAY_OUT if plan.conflicts else ADOPT_LISTED_WAY_OUT)
    return lines


def refusal_lines(refusal: AdoptRefusal) -> list[str]:
    """Each refused ``--accept`` path, in order, with why it is refused."""
    return [shown_text(f"{shown_path(each.path)}: {each.message}") for each in refusal.refused]


def _listed_line(listed: Listed) -> str:
    if isinstance(listed, ContentDifference):
        what = _content(listed)
    elif isinstance(listed, LinkDifference):
        what = (
            f"link target differs (on disk -> {listed.on_disk_target},"
            f" render -> {listed.render_target})"
        )
    else:
        what = (
            f"migration: directory link -> {listed.on_disk_target},"
            f" rendered as {listed.link_count} links"
        )
    return shown_text(f"{shown_path(listed.path)}: {what}")


def _content(difference: ContentDifference) -> str:
    what = _lines_changed(difference.on_disk, difference.render)
    if difference.on_disk_executable != difference.render_executable:
        on_disk_bit = _bit(executable=difference.on_disk_executable)
        render_bit = _bit(executable=difference.render_executable)
        what += f", executable bit differs (on disk {on_disk_bit}, render {render_bit})"
    return what


def _lines_changed(on_disk: bytes, render: bytes) -> str:
    """``+a -b lines`` as sync's diff of the two would count them, or the binary wording."""
    if on_disk == render:
        return "+0 -0 lines"
    disk_text, render_text = is_text(on_disk), is_text(render)
    if disk_text is None or render_text is None:
        return "binary content differs"
    matcher = difflib.SequenceMatcher(a=split_lines(disk_text), b=split_lines(render_text))
    added = removed = 0
    for tag, start, end, render_start, render_end in matcher.get_opcodes():
        if tag != "equal":
            removed += end - start
            added += render_end - render_start
    return f"+{added} -{removed} lines"


def _bit(*, executable: bool) -> str:
    return "+x" if executable else "-x"
