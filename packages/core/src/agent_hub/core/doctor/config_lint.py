"""The files the config-lint rules read, and their text and frontmatter (spec D4, Q-5, Q-6).

The shared machinery of the hub's old config lint script, over the snapshot's listing:
only listed regular files count, so a link, to a file or a folder, is never followed and never
an instruction file (spec D3, plan E1: a hub links each plugin agent into ``.claude/agents/``).

- Instruction files: the root ``AGENTS.md``, ``CLAUDE.md``, ``CLAUDE.local.md``, ``GEMINI.md``,
  ``.github/copilot-instructions.md``, and every ``.md`` at any depth under ``.claude/rules``,
  ``.claude/agents``, ``.claude/skills``, ``.claude/commands`` and ``.github/instructions``.
- Plugin files: every ``.md`` under ``plugin/`` with an ``agents`` or ``skills`` folder in its
  path (a whole segment: ``agentsx`` is another folder).
- Agent and skill files: the instruction files under ``.claude/agents`` or ``.claude/skills``
  and the plugin files.
- Fences: ``unfenced_lines`` drops fenced blocks (``` ``` ``` or ``~~~``, at any indent, to the
  closing fence or the text's end), the lines the Markdown rules read (``links.dead``,
  ``brain.leak``).
- Paths: ``path_tree`` holds a tree's paths and their folders as segments (``PathTrie``), so
  a reference resolves in time linear in its length (``instructions.refs``, ``links.dead``).

Each set is sorted by path string, the order in which a later file is "later" (duplicates).
"""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.doctor.snapshot import HubFiles, hub_paths, lines_of
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry

INSTRUCTION_ROOT_FILES: Final = (
    "AGENTS.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
)
INSTRUCTION_FOLDERS: Final = (
    ".claude/rules/",
    ".claude/agents/",
    ".claude/skills/",
    ".claude/commands/",
    ".github/instructions/",
)
AGENT_SKILL_FOLDERS: Final = (".claude/agents/", ".claude/skills/")
PLUGIN_FOLDER: Final = "plugin"
PLUGIN_SEGMENTS: Final = frozenset({"agents", "skills"})
MARKDOWN: Final = ".md"
FRONTMATTER_MARKER: Final = "---"

TEXT_FIX: Final = "save it as UTF-8 text"
NUL: Final = b"\x00"

# The old lint's field and list-item lines, each matched from the line's start.
_FIELD: Final = re.compile(r"([A-Za-z_-]+):\s*(.*)")
_ITEM: Final = re.compile(r"\s+-\s+(.*)")
# A run of three or more backticks or tildes that starts a line (after blanks), and the rest.
_FENCE: Final = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")


@dataclass(frozen=True, kw_only=True, slots=True)
class TextProblem:
    """Why a file's text could not be had: a finding's message and fix, before its rule."""

    message: str
    fix: str


@dataclass(frozen=True, kw_only=True, slots=True)
class Frontmatter:
    """The ``key: value`` fields between the ``---`` lines, and the closing line's number.

    A field with no value holds the ``  - item`` lines that follow it (quotes stripped); a field
    with a value keeps it as one stripped string.
    """

    fields: Mapping[str, str | tuple[str, ...]]
    end: int


@dataclass(frozen=True, slots=True)
class Unterminated:
    """The first line is ``---`` and no later line closes it."""


def instruction_files(hub: HubFiles) -> tuple[str, ...]:
    """The listed regular instruction files, sorted."""
    return _regular(hub, _is_instruction)


def plugin_files(hub: HubFiles) -> tuple[str, ...]:
    """The listed regular ``.md`` files of the plugins' agents and skills, sorted."""
    return _regular(hub, _is_plugin_file)


def agent_skill_files(hub: HubFiles) -> tuple[str, ...]:
    """The listed regular agent and skill files, of the hub and of its plugins, sorted."""
    return _regular(
        hub,
        lambda path: (
            _is_plugin_file(path)
            or (path.startswith(AGENT_SKILL_FOLDERS) and path.endswith(MARKDOWN))
        ),
    )


def known_paths(hub: HubFiles, *, config: HubConfig) -> Iterator[str]:
    """The tree's files a rule resolves against (plan E31): the listed paths and the fixed paths
    present, never lock paths or leftover names. A fixed path that is also listed comes twice.
    """
    yield from hub.listed
    yield from (path for path in hub_paths(config) if path in hub.entries)


class PathTrie:
    """A tree of path segments: a tree's paths (a node per file or folder), or references.

    Each folder is one node however many paths it holds, so the tree is linear in the paths'
    total length, at any depth (a string per ancestor folder would be quadratic). ``reached``
    marks a node a search found (``instructions.refs``).
    """

    __slots__ = ("children", "reached")

    def __init__(self) -> None:
        self.children: dict[str, PathTrie] = {}
        self.reached = False

    def add(self, segments: Iterable[str]) -> PathTrie:
        """The node of the segments, added with any node missing on the way."""
        node = self
        for segment in segments:
            child = node.children.get(segment)
            if child is None:
                child = node.children[segment] = PathTrie()
            node = child
        return node

    def holds(self, segments: Iterable[str]) -> bool:
        """Whether the segments, from this node, are a path or folder of the tree."""
        node = self
        for segment in segments:
            child = node.children.get(segment)
            if child is None:
                return False
            node = child
        return True


def path_tree(paths: Iterable[str]) -> PathTrie:
    """The paths as a segments tree, so each one and each of its folders is held."""
    tree = PathTrie()
    for path in paths:
        tree.add(path.split("/"))
    return tree


def file_text(entry: TreeEntry | None) -> str | TextProblem | None:
    """A regular file's UTF-8 text, else why it is not text (Q-19: a NUL is not text either).

    ``None`` when the entry is no regular file with content: the reader asked for every listed
    file, so a read that failed is already the hub's problem (E24) and the caller skips it.
    """
    if not isinstance(entry, FileEntry) or entry.content is None:
        return None
    try:
        text = entry.content.decode("utf-8")
    except UnicodeDecodeError as error:
        return TextProblem(
            message=f"not UTF-8 text: byte {error.start} cannot be decoded", fix=TEXT_FIX
        )
    if NUL in entry.content:
        return TextProblem(
            message=f"not UTF-8 text: NUL at byte {entry.content.index(NUL)}", fix=TEXT_FIX
        )
    return text


def text_lines(text: str) -> tuple[str, ...]:
    """The lines every config-lint rule reads (E29): split on ``\\n``, a trailing ``\\r`` dropped.

    So ``\\n`` and ``\\r\\n`` end a line and a lone ``\\r`` does not (the old lint's text mode
    also split there).
    """
    return tuple(line.removesuffix("\r") for line in lines_of(text))


def unfenced_lines(lines: Sequence[str], *, start: int = 0) -> Iterator[tuple[int, str]]:
    """The lines from index ``start`` outside fenced blocks, each with its 1-based number.

    A fence opens on a run of three or more backticks or tildes (a backtick run's info string
    holds no backtick, else the line is a code span) and closes on a run of the same character,
    at least as long, with only blanks after it; one never closed runs to the text's end. The
    fence lines are dropped too; an indented code block is not a fence (CommonMark's 3-space
    bound is not kept, so a fence nested in a list item is one too).
    """
    fence: tuple[str, int] | None = None
    for number in range(start + 1, len(lines) + 1):
        line = lines[number - 1]
        marker = _fence_marker(line)
        if fence is not None:
            if marker is not None and _closes(marker, fence=fence):
                fence = None
        elif marker is not None and _opens(marker):
            fence = (marker[0], marker[1])
        else:
            yield number, line


def _fence_marker(line: str) -> tuple[str, int, str] | None:
    """The fence character, the run's length and what follows, when the line starts a run."""
    match = _FENCE.fullmatch(line)
    if match is None:
        return None
    return match[1][0], len(match[1]), match[2]


def _opens(marker: tuple[str, int, str]) -> bool:
    character, _, info = marker
    return character == "~" or "`" not in info


def _closes(marker: tuple[str, int, str], *, fence: tuple[str, int]) -> bool:
    character, length, rest = marker
    return character == fence[0] and length >= fence[1] and not rest.strip(" \t")


def line_count(text: str) -> int:
    """``len(text_lines(text))`` without building the lines (E30: the size rule's count)."""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def parse_frontmatter(text: str) -> Frontmatter | Unterminated | None:
    """The frontmatter of a text; ``None`` when its first line is not ``---``.

    Lines are ``text_lines`` (a BOM or a lone ``\r`` is text); the marker is ``---`` once
    stripped, a field is ``name: value`` from the line's start, a list item is an indented
    ``- item``, as the old lint read them.
    """
    lines = text_lines(text)
    if not lines or lines[0].strip() != FRONTMATTER_MARKER:
        return None
    fields: dict[str, str | list[str]] = {}
    key: str | None = None
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == FRONTMATTER_MARKER:
            return Frontmatter(fields=_frozen(fields), end=number)
        key = _read_line(line, fields=fields, key=key)
    return Unterminated()


def _read_line(line: str, *, fields: dict[str, str | list[str]], key: str | None) -> str | None:
    # Returns the field that list items now belong to.
    field = _FIELD.fullmatch(line)
    if field is not None:
        fields[field[1]] = field[2].strip() or []
        return field[1]
    item = _ITEM.fullmatch(line)
    if key is not None and item is not None:
        items = fields[key]
        if isinstance(items, list):
            items.append(item[1].strip().strip("'\""))
    return key


def _frozen(fields: dict[str, str | list[str]]) -> dict[str, str | tuple[str, ...]]:
    return {
        name: value if isinstance(value, str) else tuple(value) for name, value in fields.items()
    }


def _regular(hub: HubFiles, wanted: Callable[[str], bool]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in hub.listed
            if wanted(path) and isinstance(hub.entries.get(path), FileEntry)
        )
    )


def _is_instruction(path: str) -> bool:
    return path in INSTRUCTION_ROOT_FILES or (
        path.startswith(INSTRUCTION_FOLDERS) and path.endswith(MARKDOWN)
    )


def _is_plugin_file(path: str) -> bool:
    parts = path.split("/")
    return (
        parts[0] == PLUGIN_FOLDER
        and path.endswith(MARKDOWN)
        and any(part in PLUGIN_SEGMENTS for part in parts[1:-1])
    )
