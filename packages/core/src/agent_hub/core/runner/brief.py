"""The input brief: the sections a tracker issue's description states before work starts (ADR 0026).

One definition, read by ``hub run`` (which refuses an incomplete brief) and by the generator
(which renders ``/feature``'s step 0 from these constants). Stdlib only, pure.

The rules ``check_brief`` applies to the description, one line at a time:

- Lines are split with ``str.splitlines``, so besides ``\n``, ``\r\n`` and ``\r``, the
  characters ``\x0b``, ``\x0c``, ``\x1c`` to ``\x1e``, ``\x85``, U+2028 and U+2029 also end a
  line (deliberate).
- A fence is a line of up to 3 spaces then 3 or more backticks or tildes; a backtick run opens
  one only when no backtick follows it on the line (CommonMark 4.5: a backtick fence's info
  string holds no backtick), so a line that starts with an inline code span is not a fence.
  It closes on a line of up to 3 spaces, the same character at least as many times, then only
  whitespace; an unclosed fence runs to the end. Lines in a fence (the fence lines included)
  are body text, never headings, as is a line indented 4 or more spaces.
- A heading is an ATX heading: up to 3 spaces, 1 to 6 ``#``, then the end of the line or a
  space or tab and its text. Its key is the text stripped, one trailing ``:`` removed, stripped
  again and casefolded; it names a section when it equals a ``BRIEF_SECTIONS`` name casefolded
  (no aliases; a closing ``#`` sequence is part of the text).
- A heading closes every open section of its level or deeper; every other open section reads
  the heading line as body text, so a section's subheadings belong to it.
- A section is present when the body of any of its occurrences holds more than blanks and one
  bare placeholder (``PLACEHOLDERS``, compared stripped and casefolded).

Each line updates at most six open sections, so the time is linear in the input.
"""

import re
from collections.abc import Sequence
from enum import Enum
from typing import Final

BRIEF_SECTIONS: Final = (
    "Problem",
    "Why",
    "Why now",
    "Outcome",
    "Invariants",
    "Acceptance criteria",
)
PLACEHOLDERS: Final = ("TBD", "N/A", "-", "TODO")

_HEADING: Final = re.compile(r" {0,3}(#{1,6}+)(?:[ \t](.*))?")
_FENCE: Final = re.compile(r" {0,3}(`{3,}+|~{3,}+)")
_FENCE_CLOSE: Final = re.compile(r" {0,3}(`{3,}+|~{3,}+)[ \t]*")
_SECTION_OF_KEY: Final = {name.casefold(): name for name in BRIEF_SECTIONS}
_PLACEHOLDER_KEYS: Final = frozenset(placeholder.casefold() for placeholder in PLACEHOLDERS)


class _Body(Enum):
    """How much an open section's body holds so far; it only moves up."""

    EMPTY = 0
    PLACEHOLDER = 1
    CONTENT = 2


class _OpenSection:
    """A canonical section whose body is still being read."""

    def __init__(self, level: int, name: str) -> None:
        self.level = level
        self.name = name
        self.body = _Body.EMPTY

    def read(self, line: str) -> None:
        """Update the body state with one body line."""
        if self.body is _Body.CONTENT:
            return
        text = line.strip().casefold()
        if not text:
            return
        if self.body is _Body.EMPTY and text in _PLACEHOLDER_KEYS:
            self.body = _Body.PLACEHOLDER
        else:
            self.body = _Body.CONTENT


class _Scan:
    """One pass over a description: the open sections (levels strictly rising) and those found."""

    def __init__(self) -> None:
        self.open: list[_OpenSection] = []
        self.present: set[str] = set()
        self.fence = ""

    def read(self, line: str) -> None:
        if self._read_fence(line):
            self._read_body(line)
            return
        heading = _HEADING.fullmatch(line)
        if heading is None:
            self._read_body(line)
            return
        level = len(heading.group(1))
        self._close_from(level)
        self._read_body(line)
        name = _SECTION_OF_KEY.get(_key(heading.group(2) or ""))
        if name is not None:
            self.open.append(_OpenSection(level, name))

    def finish(self) -> tuple[str, ...]:
        self._close_from(1)
        return tuple(name for name in BRIEF_SECTIONS if name not in self.present)

    def _read_fence(self, line: str) -> bool:
        """Track the fence state; True when ``line`` is a fence line or inside a fence."""
        if self.fence:
            closing = _FENCE_CLOSE.fullmatch(line)
            if closing is not None and _closes(closing.group(1), self.fence):
                self.fence = ""
            return True
        opening = _FENCE.match(line)
        if opening is None:
            return False
        run = opening.group(1)
        if run[0] == "`" and "`" in line[opening.end() :]:
            return False
        self.fence = run
        return True

    def _read_body(self, line: str) -> None:
        for section in self.open:
            section.read(line)

    def _close_from(self, level: int) -> None:
        while self.open and self.open[-1].level >= level:
            closed = self.open.pop()
            if closed.body is _Body.CONTENT:
                self.present.add(closed.name)


def _closes(run: str, fence: str) -> bool:
    return run[0] == fence[0] and len(run) >= len(fence)


def _key(text: str) -> str:
    return text.strip().removesuffix(":").strip().casefold()


def check_brief(markdown: str) -> tuple[str, ...]:
    """Return the names of the sections ``markdown`` lacks, in canonical order; ``()`` if none."""
    scan = _Scan()
    for line in markdown.splitlines():
        scan.read(line)
    return scan.finish()


def missing_brief_reason(issue_id: str, missing: Sequence[str]) -> str:
    """The one-line refusal ``hub run`` prints and records: the issue id and the missing names."""
    names = ", ".join(missing)
    return f"{issue_id} brief is missing: {names} (add these headings to the issue description)"
