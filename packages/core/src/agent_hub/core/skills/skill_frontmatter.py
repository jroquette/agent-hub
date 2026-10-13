"""A skill's or agent's frontmatter, read by the skills subset of YAML (AGH-164, L1, A4).

The brain subset (``key: value`` lines, quoted strings, ``[a, b]`` lists, block lists, ``#``
comment lines) plus what real skills write: block scalars ``|`` and ``>`` with ``-`` / ``+``
chomping, a plain scalar continued on indented lines, a block list at column 0, and one level of
``metadata:`` holding string values. Anything else (a nested mapping, an anchor, an alias, a
tag, a flow mapping, an indentation indicator, a tab indent, a repeated key) is a problem
reported in one line, never guessed; the document is then the whole text with no pairs.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.brain.frontmatter import FENCE, FIELD_LINE, field_value, unquote
from agent_hub.core.skills.skill_view import FrontmatterPair, SkillDocument, SkillFrontmatterValue

MAX_SKILL_FRONTMATTER_LINES: Final = 128
MAX_SKILL_FRONTMATTER_BYTES: Final = 16 * 1024
# The one key whose value may be a one-level map of strings (A4).
METADATA_KEY: Final = "metadata"

# What cannot start a value of the subset: anchor, alias, tag, flow mapping, reserved marks.
_UNSUPPORTED_START: Final = {
    "&": "an anchor",
    "*": "an alias",
    "!": "a tag",
    "{": "a flow mapping",
    "@": "a reserved character",
    "`": "a reserved character",
    "%": "a directive",
}
_BLOCK_HEADER: Final = re.compile(r"^([|>])([+-]?)$")
_INDENT_INDICATOR: Final = re.compile(r"^[|>][+-]?[0-9]|^[|>][0-9]")
_HEADER_COMMENT: Final = re.compile(r"[ \t]+#.*$")
_MAP_IN_ITEM: Final = re.compile(r"^[^\s\"'\[{][^:]*:(?:[ \t]|$)")
_LIST_ITEM: Final = re.compile(r"^-(?:[ \t]|$)")
_FOLDED: Final = ">"
_STRIP: Final = "-"
_KEEP: Final = "+"


class _Unparseable(Exception):  # noqa: N818 - internal control flow, never leaves this module
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class _Line:
    number: int
    text: str

    @property
    def blank(self) -> bool:
        return not self.text.strip()

    @property
    def comment(self) -> bool:
        return self.text.lstrip().startswith("#")

    def indent(self) -> int:
        """The leading spaces; a tab among the leading whitespace is refused."""
        spaces = len(self.text) - len(self.text.lstrip(" "))
        if self.text[spaces : spaces + 1] == "\t":
            raise _Unparseable(f"Line {self.number} of the frontmatter indents with a tab")
        return spaces


def _closing_fence(lines: Sequence[str]) -> int | None:
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == FENCE:
            return index
    return None


def _block(lines: Sequence[str]) -> list[str]:
    end = _closing_fence(lines)
    if end is None:
        raise _Unparseable("The frontmatter is not closed")
    block = list(lines[1:end])
    if len(block) > MAX_SKILL_FRONTMATTER_LINES:
        raise _Unparseable(f"The frontmatter is longer than {MAX_SKILL_FRONTMATTER_LINES} lines")
    if len("".join(block).encode()) > MAX_SKILL_FRONTMATTER_BYTES:
        raise _Unparseable(f"The frontmatter is larger than {MAX_SKILL_FRONTMATTER_BYTES} bytes")
    return block


def _refuse_start(value: str, number: int) -> None:
    what = _UNSUPPORTED_START.get(value[:1])
    if what is not None:
        raise _Unparseable(f"Line {number} of the frontmatter uses {what}, outside the subset")


def _quoted(value: str, number: int) -> str:
    quote = value[0]
    if len(value) < 2 or value[-1] != quote:  # noqa: PLR2004 - two quote marks
        raise _Unparseable(f"Line {number} of the frontmatter has an unclosed quote")
    return unquote(value)


def _scalar(value: str, number: int) -> str:
    _refuse_start(value, number)
    if value[:1] in {'"', "'"}:
        return _quoted(value, number)
    return value


def _fold_plain(parts: Sequence[str]) -> str:
    # YAML plain folding: lines join with a space, each empty line between them is a newline.
    text = ""
    breaks = 0
    for part in parts:
        if not part:
            breaks += 1
            continue
        if text:
            text += "\n" * breaks if breaks else " "
        text += part
        breaks = 0
    return text


def _fold_block(lines: Sequence[str]) -> str:
    # YAML folded block: a break between two text lines is a space, unless either line is
    # more indented; each empty line is a newline.
    text = ""
    breaks = 0
    previous_more = False
    for index, line in enumerate(lines):
        if not line:
            breaks += 1
            continue
        more = line[0] in " \t"
        if index == breaks:
            text += "\n" * breaks
        elif breaks:
            text += ("\n" if more or previous_more else "") + "\n" * breaks
        else:
            text += "\n" if more or previous_more else " "
        text += line
        breaks = 0
        previous_more = more
    return text


def _children(lines: Sequence[_Line], start: int, *, compact_list: bool) -> int:
    """The index after the lines that belong to the key before ``start``: blank or indented
    lines, and column-0 ``- item`` lines when the key opens a compact list."""
    end = start
    while end < len(lines):
        line = lines[end]
        nested = line.blank or line.text[0] in " \t"
        if not nested and not (compact_list and _LIST_ITEM.match(line.text)):
            break
        end += 1
    return end


def _block_header(header: str, number: int) -> tuple[str, str]:
    header = _HEADER_COMMENT.sub("", header)
    if _INDENT_INDICATOR.match(header):
        raise _Unparseable(
            f"Line {number} of the frontmatter uses an indentation indicator, outside the subset"
        )
    found = _BLOCK_HEADER.match(header)
    if found is None:
        raise _Unparseable(f"Line {number} of the frontmatter has a malformed block scalar header")
    style, chomping = found.groups()
    return style, chomping


def _block_lines(lines: Sequence[_Line], indent: int) -> list[str]:
    texts: list[str] = []
    for line in lines:
        if line.blank:
            texts.append("")
            continue
        spaces = len(line.text) - len(line.text.lstrip(" "))
        if spaces < indent:
            line.indent()
            raise _Unparseable(f"Line {line.number} of the frontmatter is less indented")
        texts.append(line.text[indent:])
    return texts


def _block_scalar(header: str, lines: Sequence[_Line], number: int) -> str:
    style, chomping = _block_header(header, number)
    content = [line for line in lines if not line.blank]
    if not content:
        return ""
    texts = _block_lines(lines, content[0].indent())
    trailing = 0
    while not texts[-1 - trailing]:
        trailing += 1
    kept = texts[: len(texts) - trailing]
    text = _fold_block(kept) if style == _FOLDED else "\n".join(kept)
    if chomping == _STRIP:
        return text
    if chomping == _KEEP:
        return text + "\n" + "\n" * trailing
    return text + "\n"


def _block_list(lines: Sequence[_Line]) -> tuple[str, ...]:
    items: list[str] = []
    for line in lines:
        if line.blank or line.comment:
            continue
        line.indent()
        stripped = line.text.strip()
        if not _LIST_ITEM.match(stripped):
            raise _Unparseable(f"Line {line.number} of the frontmatter is not a list item")
        item = stripped[1:].strip()
        if _MAP_IN_ITEM.match(item):
            raise _Unparseable(f"Line {line.number} of the frontmatter nests a map in a list")
        if item[:1] in {"[", "|", ">"}:
            raise _Unparseable(f"Line {line.number} of the frontmatter nests a value in a list")
        items.append(_scalar(item, line.number) if item else "")
    return tuple(items)


def _map_value(raw: str, number: int) -> str:
    if raw[:1] in {"[", "|", ">"}:
        raise _Unparseable(f"Line {number} of the frontmatter: metadata values must be strings")
    return _scalar(raw, number)


def _metadata(lines: Sequence[_Line]) -> dict[str, str]:
    values: dict[str, str] = {}
    indent: int | None = None
    for line in lines:
        if line.blank or line.comment:
            continue
        spaces = line.indent()
        indent = spaces if indent is None else indent
        if spaces != indent:
            raise _Unparseable(
                f"Line {line.number} of the frontmatter nests deeper than one level of metadata"
            )
        found = FIELD_LINE.match(line.text[spaces:])
        if found is None:
            raise _Unparseable(f"Line {line.number} of the frontmatter is not 'key: value'")
        key = found.group(1)
        if key in values:
            raise _Unparseable(f"Line {line.number} of the frontmatter repeats a key")
        values[key] = _map_value((found.group(2) or "").strip(), line.number)
    return values


def _nested(key: str, lines: Sequence[_Line]) -> SkillFrontmatterValue:
    """The value of ``key:`` with nothing after the colon, from the lines below it."""
    content = [line for line in lines if not line.blank and not line.comment]
    if not content:
        return ""
    first = content[0]
    first.indent()
    stripped = first.text.strip()
    if _LIST_ITEM.match(stripped):
        return _block_list(lines)
    if FIELD_LINE.match(stripped):
        if key != METADATA_KEY:
            raise _Unparseable(
                f"Line {first.number} of the frontmatter nests a map, outside the subset"
            )
        return _metadata(lines)
    return _plain(None, lines)


def _plain(raw: str | None, lines: Sequence[_Line]) -> str:
    parts = [] if raw is None else [raw]
    for line in lines:
        if line.comment:
            continue
        if not line.blank:
            line.indent()
            if not any(parts):
                _refuse_start(line.text.strip(), line.number)
        parts.append(line.text.strip())
    return _fold_plain(parts)


def _inline(raw: str, lines: Sequence[_Line], number: int) -> SkillFrontmatterValue:
    """The value written after ``key:`` on its line, maybe continued on the lines below."""
    if raw[:1] in {"|", ">"}:
        return _block_scalar(raw, lines, number)
    _refuse_start(raw, number)
    continued = any(not line.blank and not line.comment for line in lines)
    if raw[:1] in {'"', "'", "["}:
        if continued:
            raise _Unparseable(f"Line {number} of the frontmatter continues a quoted value")
        if raw[0] == "[":
            if not raw.endswith("]"):
                raise _Unparseable(f"Line {number} of the frontmatter has an unclosed list")
            listed = field_value(raw)
            return tuple(listed) if isinstance(listed, list) else listed
        return _quoted(raw, number)
    return _plain(raw, lines) if continued else raw


def _pairs(block: Sequence[str]) -> list[tuple[str, SkillFrontmatterValue]]:
    lines = [_Line(number, text.rstrip("\r\n")) for number, text in enumerate(block, start=2)]
    pairs: list[tuple[str, SkillFrontmatterValue]] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.blank or line.comment:
            index += 1
            continue
        if line.text[0] in " \t":
            line.indent()
            raise _Unparseable(f"Line {line.number} of the frontmatter is indented where a key was")
        found = FIELD_LINE.match(line.text)
        if found is None:
            raise _Unparseable(f"Line {line.number} of the frontmatter is not 'key: value'")
        key, raw = found.group(1), (found.group(2) or "").strip()
        if key in seen:
            raise _Unparseable(f"Line {line.number} of the frontmatter repeats a key")
        seen.add(key)
        compact = not raw and _opens_compact_list(lines, index + 1)
        end = _children(lines, index + 1, compact_list=compact)
        below = lines[index + 1 : end]
        value = _inline(raw, below, line.number) if raw else _nested(key, below)
        pairs.append((key, value))
        index = end
    return pairs


def _opens_compact_list(lines: Sequence[_Line], start: int) -> bool:
    for line in lines[start:]:
        if not line.blank:
            return bool(_LIST_ITEM.match(line.text))
    return False


def read_skill_document(text: str, *, known_keys: frozenset[str] = frozenset()) -> SkillDocument:
    """``text`` split into its ordered frontmatter pairs and its body (see ``SkillDocument``).

    A pair is ``known`` when its key is in ``known_keys`` (``KNOWN_SKILL_KEYS`` or
    ``KNOWN_AGENT_KEYS``). With no frontmatter, no pairs and the whole text as body; with one
    outside the subset, the same plus ``problem``. CRLF line ends are accepted.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FENCE:
        return SkillDocument(body=text)
    try:
        block = _block(lines)
        pairs = _pairs(block)
    except _Unparseable as unparseable:
        return SkillDocument(body=text, problem=unparseable.reason)
    return SkillDocument(
        pairs=tuple(
            FrontmatterPair(key=key, value=value, known=key in known_keys) for key, value in pairs
        ),
        body="".join(lines[len(block) + 2 :]),
    )
