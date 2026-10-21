"""A plan's version from its amendments (two-level-flows AC-1.4): pure, no I/O.

An approved ``plan.md`` is never rewritten; each change is appended under its ``## Amendments``
section (a level-2 heading whose text starts with ``Amendments``, up to the next level-1 or
level-2 heading) as one entry line ``A<n> (<YYYY-MM-DD>, <who>): <title>``, bare or as a ``- ``
list item, its head optionally bold (``**A1 (…):**``). The plan's version is the number of
distinct entries plus one: ``v1`` without any. Each entry's anchor is the text of that
``## Amendments…`` heading. Lines inside fenced code blocks are neither entries nor headings; an
id written again counts once (its first entry). Every line is read in linear time, and the input
is capped by the reader (``MAX_PLAN_BYTES``).
"""

import re
from collections.abc import Iterator
from typing import Final

from agent_hub.core.features.feature_view import AmendmentView, PlanView
from agent_hub.core.hub_config.problems import one_line

_TITLE_CHARS: Final = 200
# An ATX heading's opening run: its text is taken with string methods, never backtracked over.
_HEADING: Final = re.compile(r" {0,3}(#{1,6})(?=[ \t]|$)")
_FENCE: Final = re.compile(r" {0,3}(`{3,}|~{3,})")
# ``<who>`` is everything up to the first ``)``; no lazy group sits before optional blanks.
_ENTRY: Final = re.compile(
    r"[ \t]*(?:-[ \t]+)?(?:\*\*)?(A[1-9]\d{0,5})(?:\*\*)?[ \t]+"
    r"\((\d{4}-\d{2}-\d{2}),([^()\n]+)\)[ \t]*:(?:\*\*)?(.*)"
)


def plan_version(text: bytes) -> PlanView:
    """The version of the plan whose bytes are ``text`` (undecodable bytes are replaced)."""
    found: dict[str, AmendmentView] = {}
    section: str | None = None
    for line in _prose(text.decode("utf-8", "replace")):
        heading = _heading(line)
        if heading is not None:
            level, title = heading
            if level <= 2:
                opens = level == 2 and opens_amendments(title)
                section = title if opens else None
            continue
        entry = None if section is None else _ENTRY.fullmatch(line)
        if entry is not None and section is not None and entry.group(1) not in found:
            found[entry.group(1)] = _amendment(entry, section)
    amendments = tuple(found.values())
    return PlanView(version=len(amendments) + 1, amendments=amendments)


def last_section(text: bytes) -> str | None:
    """The text of the plan's last level-1 or level-2 heading (outside fenced code blocks); None
    without one. An amendment appended at the end belongs to that section."""
    last = None
    for line in _prose(text.decode("utf-8", "replace")):
        heading = _heading(line)
        if heading is not None and heading[0] <= 2:
            last = heading[1]
    return last


def opens_amendments(title: str) -> bool:
    """Whether a level-2 heading's ``title`` opens an ``## Amendments…`` section."""
    return title.casefold().startswith("amendments")


def _heading(line: str) -> tuple[int, str] | None:
    """The level and text of an ATX heading line, None for another line. The blanks around the
    text are left out."""
    opened = _HEADING.match(line)
    if opened is None:
        return None
    return len(opened.group(1)), line[opened.end() :].strip(" \t")


def _prose(text: str) -> Iterator[str]:
    """The lines of ``text`` outside fenced code blocks (the fence lines left out too)."""
    fence: str | None = None
    for line in text.splitlines():
        opened = _FENCE.match(line)
        if fence is None and opened is not None:
            fence = opened.group(1)
        elif fence is None:
            yield line
        elif opened is not None and _closes(opened, fence, line):
            fence = None


def _closes(opened: re.Match[str], fence: str, line: str) -> bool:
    run = opened.group(1)
    return run[0] == fence[0] and len(run) >= len(fence) and not line[opened.end() :].strip()


def _amendment(entry: re.Match[str], anchor: str) -> AmendmentView:
    ident, date, who, title = entry.groups()
    return AmendmentView(
        id=ident,
        date=date,
        who=one_line(who.strip("* \t"))[:_TITLE_CHARS],
        title=one_line(title.strip().removesuffix("**").strip())[:_TITLE_CHARS],
        anchor=anchor,
    )
