"""A plan's version from its amendments (two-level-flows AC-1.4): pure, no I/O.

An approved ``plan.md`` is never rewritten; each change is appended under its ``## Amendments``
section (a level-2 heading whose text starts with ``Amendments``, up to the next level-1 or
level-2 heading) as one entry line ``A<n> (<YYYY-MM-DD>, <who>): <title>``, optionally a list
item (``-``, ``*``, ``+``, ``1.``) or bold (``**A1 (…):**``). The plan's version is the number of
distinct entries plus one: ``v1`` without any. Lines inside fenced code blocks are neither entries
nor headings; an id written again counts once (its first entry). The work is bounded by the input,
which the reader caps (``MAX_PLAN_BYTES``).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from agent_hub.core.hub_config.problems import one_line

SECTION: Final = "amendments"
_TITLE_CHARS: Final = 200
_HEADING: Final = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*")
_FENCE: Final = re.compile(r" {0,3}(`{3,}|~{3,})")
_ENTRY: Final = re.compile(
    r"[ \t]*(?:[-*+][ \t]+|\d{1,9}[.)][ \t]+)?(?:\*\*|__)?"
    r"(A[1-9]\d{0,5})(?:\*\*|__)?[ \t]+\((\d{4}-\d{2}-\d{2}),[ \t]*([^()\n]+?)[ \t]*\)[ \t]*:"
    r"(?:\*\*|__)?[ \t]*(.*)"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class Amendment:
    """One entry of ``## Amendments``: its ``id`` (``A1``), ``date``, ``who`` and ``title`` (the
    rest of the line), and ``anchor``, the text of the heading it is under (the Plan record view
    links there)."""

    id: str
    date: str
    who: str
    title: str
    anchor: str


@dataclass(frozen=True, kw_only=True, slots=True)
class PlanVersion:
    """The plan's ``version`` (``len(amendments) + 1``) and its amendments in file order."""

    version: int
    amendments: tuple[Amendment, ...]


def plan_version(text: bytes) -> PlanVersion:
    """The version of the plan whose bytes are ``text`` (undecodable bytes are replaced)."""
    found: dict[str, Amendment] = {}
    section: str | None = None
    for line in _prose(text.decode("utf-8", "replace")):
        heading = _HEADING.fullmatch(line)
        if heading is not None:
            level, title = len(heading.group(1)), (heading.group(2) or "").strip()
            if level <= 2:
                section = title if level == 2 and title.casefold().startswith(SECTION) else None
            continue
        entry = None if section is None else _ENTRY.fullmatch(line)
        if entry is not None and section is not None and entry.group(1) not in found:
            found[entry.group(1)] = _amendment(entry, section)
    amendments = tuple(found.values())
    return PlanVersion(version=len(amendments) + 1, amendments=amendments)


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


def _amendment(entry: re.Match[str], anchor: str) -> Amendment:
    ident, date, who, title = entry.groups()
    return Amendment(
        id=ident,
        date=date,
        who=one_line(who.strip("*_ "))[:_TITLE_CHARS],
        title=one_line(title.strip().removesuffix("**").strip())[:_TITLE_CHARS],
        anchor=anchor,
    )
