"""``brain.leak``: no brain line is copied into a repo file (spec AC-11.28, Q-17, Q-7).

The brain is the hub's private memory, so its text must not land in a code repo.

- Brain lines: the listed regular files under the hub's ``brain/`` that are UTF-8 text (any
  other is skipped, Q-19), line by line (``config_lint.text_lines``, E29), each trimmed of the
  blanks at its ends (blanks inside are kept); frontmatter (a first line ``---`` to the next
  ``---``; one never closed is no frontmatter), fenced blocks (``` ``` ``` or ``~~~``, at any
  indent, to the closing fence or the file's end) and table rows (``|`` first) are skipped. A
  line counts from ``doctor.rules."brain.leak".min_line_length`` characters (default 60).
- Repo lines: every listed regular UTF-8 text file of each checked-out repo, trimmed the same
  way; one equal to a brain line is an error at ``../<dir>/<path>:<line>``, naming the first
  brain line (in listing order). A missing checkout is skipped (the runner reports it, Q-9).

Scale: the brain lines go into a dict once per run, and each file is split once, so a run is
linear in the total size of the brain and the repos (a lookup hashes the line once), never
brain lines × repo lines. A message names the brain path and line, never the leaked line.
"""

import re
from collections.abc import Iterator, Mapping
from typing import Final

from agent_hub.core.doctor.config_lint import FRONTMATTER_MARKER, text_lines
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles, text_of
from agent_hub.core.hub_config.doctor_rules import BRAIN_LEAK_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.versions import cut_echo

DEFAULT_MIN_LINE_LENGTH: Final = 60
BRAIN_FOLDER: Final = "brain/"
LEAK_FIX: Final = "reword or remove the line here, or reword the brain note if it quotes this file"

_TABLE_ROW: Final = "|"
_FENCE: Final = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")

# A trimmed brain line → the first brain path and line that holds it.
type BrainLines = Mapping[str, tuple[str, int]]


def _brain_leak(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    settings = snapshot.hub_config.doctor.rules.brain_leak
    length = None if settings is None else settings.min_line_length
    brain = _brain_lines(snapshot.hub, min_length=length or DEFAULT_MIN_LINE_LENGTH)
    if not brain:
        return
    for repo in snapshot.repos:
        if repo.files is not None:
            yield from _repo_findings(repo.files, brain=brain, shown_as=f"../{repo.dir}/")


def _brain_lines(hub: HubFiles, *, min_length: int) -> dict[str, tuple[str, int]]:
    lines: dict[str, tuple[str, int]] = {}
    for path in hub.listed:
        if not path.startswith(BRAIN_FOLDER):
            continue
        text = text_of(hub.entries.get(path))
        if text is None:
            continue
        for number, line in _prose_lines(text_lines(text)):
            trimmed = line.strip()
            if len(trimmed) >= min_length:
                lines.setdefault(trimmed, (path, number))
    return lines


def _prose_lines(lines: tuple[str, ...]) -> Iterator[tuple[int, str]]:
    """The lines outside frontmatter and fenced blocks, not table rows, by line number."""
    start = _frontmatter_end(lines)
    fence: tuple[str, int] | None = None
    for number, line in enumerate(lines[start:], start=start + 1):
        marker = _fence_marker(line)
        if fence is not None:
            if marker is not None and _closes(marker, fence=fence):
                fence = None
            continue
        if marker is not None and _opens(marker):
            fence = (marker[0], marker[1])
        elif not line.lstrip().startswith(_TABLE_ROW):
            yield number, line


def _frontmatter_end(lines: tuple[str, ...]) -> int:
    """How many lines the frontmatter takes: 0 when there is none, or it is never closed."""
    if not lines or lines[0].strip() != FRONTMATTER_MARKER:
        return 0
    return next(
        (index + 1 for index in range(1, len(lines)) if lines[index].strip() == FRONTMATTER_MARKER),
        0,
    )


def _fence_marker(line: str) -> tuple[str, int, str] | None:
    """The fence character, the run's length and what follows, when the line starts a run."""
    match = _FENCE.fullmatch(line)
    if match is None:
        return None
    return match[1][0], len(match[1]), match[2]


def _opens(marker: tuple[str, int, str]) -> bool:
    # A backtick fence's info string holds no backtick (else the line is a code span).
    character, _, info = marker
    return character == "~" or "`" not in info


def _closes(marker: tuple[str, int, str], *, fence: tuple[str, int]) -> bool:
    character, length, rest = marker
    return character == fence[0] and length >= fence[1] and not rest.strip(" \t")


def _repo_findings(files: HubFiles, *, brain: BrainLines, shown_as: str) -> Iterator[Finding]:
    for path in files.listed:
        text = text_of(files.entries.get(path))
        if text is None:
            continue
        for number, line in enumerate(text_lines(text), start=1):
            found = brain.get(line.strip())
            if found is not None:
                brain_path, brain_line = found
                yield BRAIN_LEAK.finding(
                    path=f"{shown_as}{path}",
                    line=number,
                    message=f"line also in the brain at {cut_echo(brain_path)}:{brain_line}",
                    fix=LEAK_FIX,
                )


BRAIN_LEAK: Final = Rule(
    id=BRAIN_LEAK_RULE,
    severity=Severity.ERROR,
    summary="no trimmed brain line of min_line_length or more characters is in a repo file",
    module=RULE_MODULES.get(BRAIN_LEAK_RULE),
    reads=frozenset({Read.HUB_LISTING, Read.REPOS}),
    check=_brain_leak,
)
