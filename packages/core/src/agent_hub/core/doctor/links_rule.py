"""``links.dead``: relative Markdown links resolve to a file or folder (spec AC-11.27, Q-18, E19).

The rule reads every listed regular ``.md`` file that is UTF-8 text (any other is skipped,
Q-19), of the hub and of each checked-out repo, line by line (``config_lint.text_lines``, E29):

- Links: inline links and images, ``[text](destination "title")`` (the ``]`` closing a ``[``
  and the ``(`` closed by a ``)``), and reference definitions, ``[label]: destination`` (at most
  three spaces in; the first definition of a label wins, as in CommonMark). A destination may be
  wrapped in ``<…>``; a bare one ends at a blank or at the link's ``)``, and keeps balanced
  parentheses. A definition is a line only when nothing or a title (``"``, ``'`` or ``(`` after a
  blank) follows its destination; else it is prose. Fenced blocks (``config_lint.unfenced_lines``),
  HTML comments (``<!--`` to ``-->``, on one line or several; ``<!-->`` is a whole one) and
  code spans (a run of backticks to the next run of the same length, on its line) are skipped;
  an indented code block is read (E37). Backslash escapes are not read.
- Not checked: a destination with a URI scheme (a letter, then 1 to 31 letters, digits, ``+``,
  ``.`` or ``-``, then ``:``; so ``http:``, ``mailto:``, but not ``C:``), a fragment
  only, an absolute one, or an empty one. Else the ``#fragment`` and ``?query`` are cut, the
  rest is percent-decoded and resolved from the file's folder.
- Exists: a listed path or a folder with a listed path under it; for the hub, also the fixed
  paths present (``config_lint.known_paths``, E31), and every fixed path when not all were read.
  A link is never followed (D3). A hub link into ``../<dir>/`` for a ``repos[].dir`` is checked
  against that checkout's listing, and skipped when the checkout is missing (the runner reports
  it, Q-9) or could not be listed (E36), whose own files are not read either; any other link
  that leaves the hub, or a repo, is not checked (E37).

A repo's findings are at ``../<dir>/<path>``. Every scan is linear in its line (each search
resumes where the last one stopped, and the destinations never overlap) and every path is
resolved through a segments tree, so a hostile line, a deep path or many files never cost more
than their size.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote

from agent_hub.core.doctor.config_lint import (
    MARKDOWN,
    PathTrie,
    file_text,
    known_paths,
    path_tree,
    text_lines,
    unfenced_lines,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles, hub_paths
from agent_hub.core.hub_config.doctor_rules import LINKS_DEAD_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.versions import cut_echo

DEAD_FIX: Final = "point the link at an existing file or folder, or remove it"
# CommonMark's bounds: a label of at most 999 characters, a definition at most 3 spaces in.
MAX_LABEL: Final = 999
MAX_DEFINITION_INDENT: Final = 3

_OPENER: Final = re.compile(r"\]\(")
_NOT_BLANK: Final = re.compile(r"[^ \t]")
_DESTINATION_END: Final = re.compile(r"[\x00-\x20\x7f]")
_POINTY_END: Final = re.compile(r"[<>]")
_BRACKETS: Final = re.compile(r"[\[\]()]")
_BACKTICKS: Final = re.compile(r"`+")
# A scheme of 2 to 32 characters, so neither a path nor a Windows drive reads as one.
_SCHEME: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{1,31}:")
_PATH_END: Final = re.compile(r"[#?]")
_TITLE_OPENERS: Final = ('"', "'", "(")
_COMMENT_OPEN: Final = re.compile(r"<!--")
_COMMENT_CLOSE: Final = re.compile(r"-->")
_COMMENT_CLOSE_LENGTH: Final = 3
_HERE: Final = frozenset({"", "."})
_UP: Final = ".."


class _Scan:
    """A pattern's next match at or after a position, asked at positions that never go back.

    A search that found ``found`` from ``asked`` answers every position up to ``found``, so the
    line is passed over once however many openers ask (the length of the line when none). Only
    the bare destination's end needs it: many destinations can end at one far blank, while each
    other search starts at its own ``](``, ``(`` or ``<`` and stops before the next one.
    """

    __slots__ = ("_asked", "_found", "_line", "_pattern")

    def __init__(self, pattern: re.Pattern[str], line: str) -> None:
        self._pattern = pattern
        self._line = line
        self._asked = 1
        self._found = 0

    def at_or_after(self, start: int) -> int:
        if not self._asked <= start <= self._found:
            match = self._pattern.search(self._line, start)
            self._asked = start
            self._found = len(self._line) if match is None else match.start()
        return self._found


@dataclass(frozen=True, kw_only=True, slots=True)
class _Tree:
    """A tree whose Markdown is read: its files and paths, how its paths are shown, and the
    checkouts its links into ``../<dir>/`` are checked against (``None`` for a repo's).
    """

    files: HubFiles
    paths: PathTrie
    shown_as: str
    checkouts: Mapping[str, PathTrie | None] | None


def _links_dead(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    # A checkout that could not be listed is treated as a missing one (E36).
    checkouts = {
        repo.dir: None
        if repo.files is None or repo.files.problem is not None
        else path_tree(repo.files.listed)
        for repo in snapshot.repos
    }
    hub = _Tree(
        files=snapshot.hub,
        paths=path_tree(_hub_paths(snapshot)),
        shown_as="",
        checkouts=checkouts,
    )
    yield from _tree_findings(hub)
    for repo in snapshot.repos:
        checkout = checkouts[repo.dir]
        if repo.files is not None and checkout is not None:
            tree = _Tree(
                files=repo.files, paths=checkout, shown_as=f"../{repo.dir}/", checkouts=None
            )
            yield from _tree_findings(tree)


def _hub_paths(snapshot: DoctorSnapshot) -> Iterator[str]:
    """The hub's known paths (E31); a fixed path not reached may exist, so it counts too."""
    config = snapshot.hub_config
    yield from known_paths(snapshot.hub, config=config)
    if not snapshot.hub.paths_read:
        yield from hub_paths(config)


def _tree_findings(tree: _Tree) -> Iterator[Finding]:
    for path in tree.files.listed:
        if not path.endswith(MARKDOWN):
            continue
        text = file_text(tree.files.entries.get(path))
        if not isinstance(text, str):
            continue
        folder = _folder_nodes(path, paths=tree.paths)
        for number, destination in _destinations(text):
            target = _link_path(destination)
            if target is not None and _is_dead(target, folder=folder, tree=tree):
                yield LINKS_DEAD.finding(
                    path=f"{tree.shown_as}{path}",
                    line=number,
                    message=f"dead link `{cut_echo(destination)}` (no such file or folder)",
                    fix=DEAD_FIX,
                )


def _folder_nodes(path: str, *, paths: PathTrie) -> list[PathTrie | None]:
    """The tree's nodes from the root to the file's folder, once per file."""
    node: PathTrie | None = paths
    nodes = [node]
    for segment in path.split("/")[:-1]:
        node = None if node is None else node.children.get(segment)
        nodes.append(node)
    return nodes


def _is_dead(target: str, *, folder: Sequence[PathTrie | None], tree: _Tree) -> bool:
    """Whether the target, from the file's folder, is no path or folder of the tree or of the
    checkout it climbs into; a target that leaves the workspace, or a repo, is never dead.
    """
    up, rest = _climbs_and_segments(target)
    depth = len(folder) - 1
    if up <= depth:
        node = folder[depth - up]
        return node is None or not node.holds(rest)
    if up > depth + 1 or not rest or tree.checkouts is None:
        return False
    checkout = tree.checkouts.get(rest[0])
    return checkout is not None and not checkout.holds(rest[1:])


def _climbs_and_segments(target: str) -> tuple[int, list[str]]:
    """How many folders the target climbs above its start, then its segments from there."""
    up = 0
    rest: list[str] = []
    for segment in target.split("/"):
        if segment == _UP:
            if rest:
                rest.pop()
            else:
                up += 1
        elif segment not in _HERE:
            rest.append(segment)
    return up, rest


def _link_path(destination: str) -> str | None:
    """The decoded relative path a destination names; ``None`` when it is not checked."""
    if destination.startswith(("#", "/")) or _SCHEME.match(destination) is not None:
        return None
    cut = _PATH_END.search(destination)
    path = destination if cut is None else destination[: cut.start()]
    return unquote(path) if path else None


def _destinations(text: str) -> Iterator[tuple[int, str]]:
    """Each line's link destinations, outside fences, comments and code spans, by line number."""
    labels: set[str] = set()
    in_comment = False
    for number, line in unfenced_lines(text_lines(text)):
        visible, in_comment = _visible(line, in_comment=in_comment)
        if visible is None:
            continue
        definition = _definition(visible)
        if definition is None:
            yield from ((number, target) for target in _inline_targets(visible))
        elif definition[0] not in labels:
            labels.add(definition[0])
            if definition[1]:
                yield number, definition[1]


def _visible(line: str, *, in_comment: bool) -> tuple[str | None, bool]:
    """The line with its code spans and HTML comments blanked (``None`` when a comment open
    before it takes it whole), and whether a comment is still open at its end.
    """
    if in_comment:
        close = _position(_COMMENT_CLOSE, line, start=0)
        if close == len(line):
            return None, True
        line = line[close + _COMMENT_CLOSE_LENGTH :]
    return _without_comments(_without_code_spans(line))


def _without_comments(line: str) -> tuple[str, bool]:
    """The line with each ``<!-- … -->`` blanked to one space, and whether the last one stays
    open; each search starts where the last one stopped.
    """
    pieces: list[str] = []
    kept = 0
    opening = _position(_COMMENT_OPEN, line, start=0)
    while opening < len(line):
        pieces.extend((line[kept:opening], " "))
        # From the opener's dashes, so "<!-->" and "<!--->" close themselves (CommonMark 0.31).
        close = _position(_COMMENT_CLOSE, line, start=opening + 2)
        if close == len(line):
            return "".join(pieces), True
        kept = close + _COMMENT_CLOSE_LENGTH
        opening = _position(_COMMENT_OPEN, line, start=kept)
    pieces.append(line[kept:])
    return "".join(pieces), False


def _without_code_spans(line: str) -> str:
    """The line with each code span blanked to one space, in one pass over its backtick runs.

    A run opens a span closed by the next run of the same length; with none, it is literal.
    Each length keeps a cursor into its own runs, which only moves forward.
    """
    if "`" not in line:
        return line
    runs = [match.span() for match in _BACKTICKS.finditer(line)]
    by_length: dict[int, list[int]] = {}
    for index, (start, end) in enumerate(runs):
        by_length.setdefault(end - start, []).append(index)
    cursors = dict.fromkeys(by_length, 0)
    pieces: list[str] = []
    kept = index = 0
    while index < len(runs):
        start, end = runs[index]
        same, cursor = by_length[end - start], cursors[end - start]
        while cursor < len(same) and same[cursor] <= index:
            cursor += 1
        cursors[end - start] = cursor
        if cursor == len(same):
            index += 1
            continue
        pieces.extend((line[kept:start], " "))
        kept = runs[same[cursor]][1]
        index = same[cursor] + 1
    pieces.append(line[kept:])
    return "".join(pieces)


def _definition(line: str) -> tuple[str, str] | None:
    """A reference definition's normalized label and destination; ``None`` when the line is
    none (a label over ``MAX_LABEL`` characters, or no destination on the line).
    """
    body = line.lstrip(" ")
    if len(line) - len(body) > MAX_DEFINITION_INDENT or not body.startswith("["):
        return None
    close = body.find("]", 1, MAX_LABEL + 2)
    if close == -1 or body.find("[", 1, close) != -1 or body[close + 1 : close + 2] != ":":
        return None
    label = " ".join(body[1:close].split()).casefold()
    destination = _definition_destination(body[close + 2 :].lstrip(" \t"))
    if not label or destination is None:
        return None
    return label, destination


def _definition_destination(rest: str) -> str | None:
    """The destination when only blanks or a title follow it; ``None`` when the line is prose."""
    if rest.startswith("<"):
        end = rest.find(">")
        if end == -1 or rest.find("<", 1, end) != -1:
            return None
        destination, after = rest[1:end], rest[end + 1 :]
    else:
        end_match = _DESTINATION_END.search(rest)
        end = len(rest) if end_match is None else end_match.start()
        destination, after = rest[:end], rest[end:]
        if not destination:
            return None
    title = after.lstrip(" \t")
    if title and (title == after or not title.startswith(_TITLE_OPENERS)):
        return None
    return destination


def _inline_targets(line: str) -> Iterator[str]:
    """The destinations of a line's inline links and images, in one pass.

    A ``](`` opens one when its ``]`` closes a ``[`` and its ``(`` is closed; the next ``](`` is
    looked for after the destination, so destinations never overlap.
    """
    if "](" not in line:
        return
    linked, closes = _pairs(line)
    ends = _Scan(_DESTINATION_END, line)
    at = _position(_OPENER, line, start=0)
    while at < len(line):
        close = closes.get(at + 1) if at in linked else None
        span = None if close is None else _destination_span(line, at=at, close=close, ends=ends)
        if span is None:
            at = _position(_OPENER, line, start=at + 1)
            continue
        begin, end, resume = span
        if end > begin:
            yield line[begin:end]
        at = _position(_OPENER, line, start=resume)


def _position(pattern: re.Pattern[str], line: str, *, start: int) -> int:
    """Where the pattern next matches at or after ``start``; the line's length when nowhere."""
    match = pattern.search(line, start)
    return len(line) if match is None else match.start()


def _destination_span(
    line: str, *, at: int, close: int, ends: _Scan
) -> tuple[int, int, int] | None:
    """Where the destination of the ``](`` at ``at`` begins and ends, and where to look next;
    ``None`` when a ``<`` opens a destination that no ``>`` closes before the link's ``)``.
    """
    begin = _position(_NOT_BLANK, line, start=at + 2)
    if begin >= close:
        return begin, begin, close
    if line[begin] == "<":
        end = _position(_POINTY_END, line, start=begin + 1)
        if end >= close or line[end] != ">":
            return None
        return begin + 1, end, end + 1
    end = min(ends.at_or_after(begin), close)
    return begin, end, end


def _pairs(line: str) -> tuple[frozenset[int], dict[int, int]]:
    """Each ``]`` that closes a ``[``, and each ``(`` with the ``)`` that closes it."""
    linked: set[int] = set()
    closes: dict[int, int] = {}
    brackets: list[int] = []
    parens: list[int] = []
    for match in _BRACKETS.finditer(line):
        at, character = match.start(), match[0]
        if character == "[":
            brackets.append(at)
        elif character == "(":
            parens.append(at)
        elif character == "]" and brackets:
            brackets.pop()
            linked.add(at)
        elif character == ")" and parens:
            closes[parens.pop()] = at
    return frozenset(linked), closes


LINKS_DEAD: Final = Rule(
    id=LINKS_DEAD_RULE,
    severity=Severity.ERROR,
    summary="relative Markdown links in the hub and its repos resolve to a file or folder",
    module=RULE_MODULES.get(LINKS_DEAD_RULE),
    reads=frozenset({Read.HUB_LISTING, Read.REPOS}),
    check=_links_dead,
)
