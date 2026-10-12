"""A note's frontmatter: read its fields, rewrite some of them, and the note's first paragraph.

Only the subset brain notes use is read: ``key: value`` lines, ``[a, b]`` lists, block lists
(``key:`` then indented ``- item`` lines), quoted strings and ``#`` comments. Anything else is a
problem, reported instead of guessed; the note is then shown whole.
"""

import re
from collections.abc import Mapping
from typing import Final

from agent_hub.core.brain.brain_note import FrontmatterValue
from agent_hub.core.errors import AgentHubError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.redaction.redact import clip

FENCE: Final = "---"
MAX_FRONTMATTER_LINES: Final = 64
MAX_FRONTMATTER_BYTES: Final = 8 * 1024
SUMMARY_CHARS: Final = 200

_FIELD: Final = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
_PLAIN: Final = re.compile(r"[A-Za-z0-9_./][A-Za-z0-9_./ -]*")


class Frontmatter(ViewModel):
    """A note split in two: its frontmatter ``fields`` and the ``body`` after the closing fence.

    With no frontmatter, ``fields`` is empty and ``body`` is the whole text; with a malformed one,
    the same plus ``problem``.
    """

    fields: dict[str, FrontmatterValue]
    body: str
    problem: str | None = None


class FrontmatterError(AgentHubError):
    """A note's frontmatter cannot be rewritten (it is not closed)."""


class _Malformed(Exception):  # noqa: N818 - internal control flow, never leaves this module
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _closing_fence(lines: list[str]) -> int | None:
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == FENCE:
            return index
    return None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _value(raw: str) -> FrontmatterValue:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_unquote(item.strip()) for item in inner.split(",")] if inner else []
    return _unquote(value)


def _block_fields(block: list[str]) -> dict[str, FrontmatterValue]:
    fields: dict[str, FrontmatterValue] = {}
    current: str | None = None
    for number, line in enumerate(block, start=2):
        text = line.rstrip("\r\n")
        stripped = text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if text[0] in " \t" and stripped.startswith("- ") and current is not None:
            items = fields[current]
            fields[current] = [*(items if isinstance(items, list) else []), _unquote(stripped[2:])]
            continue
        found = _FIELD.match(text)
        if found is None:
            raise _Malformed(f"Line {number} of the frontmatter is not 'key: value'")
        current = found.group(1)
        fields[current] = _value(found.group(2) or "")
    return fields


def _block(lines: list[str]) -> list[str]:
    end = _closing_fence(lines)
    if end is None:
        raise _Malformed("The frontmatter is not closed")
    block = lines[1:end]
    if len(block) > MAX_FRONTMATTER_LINES:
        raise _Malformed(f"The frontmatter is longer than {MAX_FRONTMATTER_LINES} lines")
    if len("".join(block).encode()) > MAX_FRONTMATTER_BYTES:
        raise _Malformed(f"The frontmatter is larger than {MAX_FRONTMATTER_BYTES} bytes")
    return block


def _has_frontmatter(lines: list[str]) -> bool:
    return bool(lines) and lines[0].rstrip("\r\n") == FENCE


def split_frontmatter(text: str) -> Frontmatter:
    """``text`` split into its frontmatter fields and its body (see ``Frontmatter``)."""
    lines = text.splitlines(keepends=True)
    if not _has_frontmatter(lines):
        return Frontmatter(fields={}, body=text)
    try:
        block = _block(lines)
        fields = _block_fields(block)
    except _Malformed as malformed:
        return Frontmatter(fields={}, body=text, problem=malformed.reason)
    return Frontmatter(fields=fields, body="".join(lines[len(block) + 2 :]))


def _scalar(value: str) -> str:
    text = " ".join(value.split())
    if _PLAIN.fullmatch(text) and not text.endswith(" "):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _field_name(line: str) -> str | None:
    found = _FIELD.match(line.rstrip("\r\n"))
    return None if found is None else found.group(1)


def _rewritten_block(block: list[str], updates: Mapping[str, str]) -> list[str]:
    kept: list[str] = []
    written: set[str] = set()
    replacing = False
    for line in block:
        if replacing and line[:1] in {" ", "\t"}:
            continue
        name = _field_name(line)
        replacing = name in updates
        if name is not None and name in updates:
            kept.append(f"{name}: {_scalar(updates[name])}\n")
            written.add(name)
        else:
            kept.append(line)
    added = [f"{key}: {_scalar(value)}\n" for key, value in updates.items() if key not in written]
    return kept + added


def with_frontmatter(text: str, updates: Mapping[str, str]) -> str:
    """``text`` with the frontmatter fields in ``updates`` set, every other line kept in order.

    An existing field is rewritten in place (its block-list lines dropped); a new one is added
    at the end of the block; a note with no frontmatter gets one. Values are written on one
    line, whitespace collapsed, quoted when needed. ``FrontmatterError`` when the frontmatter is
    not closed.
    """
    lines = text.splitlines(keepends=True)
    if not _has_frontmatter(lines):
        added = [f"{key}: {_scalar(value)}\n" for key, value in updates.items()]
        return "".join([f"{FENCE}\n", *added, f"{FENCE}\n"]) + text
    end = _closing_fence(lines)
    if end is None:
        raise FrontmatterError("The frontmatter is not closed")
    block = _rewritten_block(lines[1:end], updates)
    return "".join([lines[0], *block, *lines[end:]])


def first_paragraph(body: str, *, limit: int = SUMMARY_CHARS) -> str:
    """The first paragraph of a note's body that is not a heading, on one line, clipped to
    ``limit`` characters (``…`` when cut); empty when there is none."""
    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    return clip(" ".join(" ".join(paragraph).split()), limit)
