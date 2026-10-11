"""``brain/now.md`` split into its Focus, Next and Watch items (Project overview › Now).

A section starts at a heading (``## Focus``) or at a top-level bullet with a bold label
(``- **Focus:** text``, whose text is an item too) and ends at the next heading or labelled
bullet. Its items are the bullets (``-``, ``*``, ``+`` or ``1.``) at the indent of its first
bullet; deeper bullets and indented lines continue the item before them. Every item carries the
note's frontmatter ``last_verified`` and ``provenance``. The text stays as written (Markdown).
"""

import re
from typing import Final

from agent_hub.core.projects.project_views import NowItem

SECTIONS: Final = ("focus", "next", "watch")
_HEADING: Final = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_LABELLED: Final = re.compile(r"^[-*+]\s+\*\*([^*]+?)\*\*:?\s*(.*)$")
_BULLET: Final = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")

type Sections = tuple[tuple[NowItem, ...], tuple[NowItem, ...], tuple[NowItem, ...]]


class _Reader:
    """The section being read, its items' indent and the items so far."""

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {name: [] for name in SECTIONS}
        self.section: str | None = None
        self.indent: int | None = None

    def start(self, label: str, rest: str = "") -> None:
        words = label.strip().rstrip(":").split()
        name = words[0].lower() if words else ""
        self.section = name if name in SECTIONS else None
        self.indent = None
        if self.section is not None and rest.strip():
            self.items[self.section].append(rest.strip())

    def line(self, line: str) -> None:
        if self.section is None or not line.strip():
            return
        items = self.items[self.section]
        bullet = _BULLET.match(line)
        if bullet is not None:
            indent = len(bullet.group(1))
            if self.indent is None:
                self.indent = indent
            if indent <= self.indent or not items:
                items.append(bullet.group(2).strip())
                return
        if items and line[0].isspace():
            items[-1] = f"{items[-1]} {line.strip()}"


def now_sections(content: bytes) -> Sections:
    """The note's Focus, Next and Watch items."""
    lines = content.decode("utf-8", "replace").splitlines()
    front, body = _split_frontmatter(lines)
    reader = _Reader()
    for line in body:
        heading = _HEADING.match(line)
        labelled = _LABELLED.match(line)
        if heading is not None:
            reader.start(heading.group(1))
        elif labelled is not None:
            reader.start(labelled.group(1), labelled.group(2))
        else:
            reader.line(line)
    focus, next_items, watch = (
        tuple(
            NowItem(
                text=text,
                last_verified=front.get("last_verified"),
                provenance=front.get("provenance"),
            )
            for text in reader.items[name]
        )
        for name in SECTIONS
    )
    return focus, next_items, watch


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return {}, lines
    front: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return front, lines[index + 1 :]
        key, colon, value = line.partition(":")
        if colon:
            front[key.strip()] = value.strip()
    return {}, lines
