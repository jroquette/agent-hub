"""``instructions.size`` and ``instructions.duplicates``: short instruction files, no repeats.

The port of the hub's old ``agent_config_lint.py`` checks over the listed regular instruction
files (``config_lint``; spec AC-11.19, AC-11.20, Q-6). Lines are counted as the old lint read
them in text mode: ``\\n``, ``\\r\\n`` and a lone ``\\r`` each end one line.

- Size: a file over its line limit is flagged, with no line number. The defaults are
  ``AGENTS.md`` 100, ``CLAUDE.md`` 150 and ``CLAUDE.local.md`` 50 at the root and 80 for every
  nested instruction file (``*/*``); ``GEMINI.md`` has none. ``doctor.rules."instructions.size"
  .max_lines`` adds limits by key: a key with no glob character (``*``, ``?``, ``[``) is the exact
  path (so a bare name is a root file), any other key an ``fnmatch`` over the path. A project key
  wins over a default one; within each, an exact key over a glob, then the longest glob, then the
  first in sorted order.
- Duplicates: a line normalized as the old lint did (stripped, list markers and digits dropped
  from its start, blanks collapsed, lowercased) of 60 or more characters, not a table, fence or
  heading line, that an earlier file in sorted path order holds is flagged on the later file,
  naming the first ``path:line``. Repeats within one file are not.

A file that is not text is skipped: the runner reports it once (E28).
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from fnmatch import translate
from types import MappingProxyType
from typing import Final

from agent_hub.core.doctor.config_lint import file_text, instruction_files
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, lines_of
from agent_hub.core.hub_config.doctor_rules import (
    INSTRUCTIONS_DUPLICATES_RULE,
    INSTRUCTIONS_SIZE_RULE,
    RULE_MODULES,
    Severity,
)

DEFAULT_MAX_LINES: Final = MappingProxyType(
    {"AGENTS.md": 100, "CLAUDE.md": 150, "CLAUDE.local.md": 50, "*/*": 80}
)
SIZE_FIX: Final = "keep it a map, not a manual: move details to docs or the brain"
DUPLICATE_FIX: Final = "keep the instruction in one file and link to it"
DUPLICATE_MIN_LENGTH: Final = 60

_GLOB_CHARACTERS: Final = frozenset("*?[")
# What the old lint dropped from a line's start before comparing: list markers and numbers.
_LIST_MARKER: Final = "-*0123456789. "
# Table, fence and heading lines repeat by design.
_NOT_AN_INSTRUCTION: Final = ("|", "```", "#")
_BLANKS: Final = re.compile(r"\s+")


@dataclass(frozen=True, kw_only=True, slots=True)
class _Limits:
    """One source's limits: exact paths, and globs in the order they are tried."""

    exact: Mapping[str, int]
    globs: tuple[tuple[re.Pattern[str], int], ...]

    def of(self, path: str) -> int | None:
        limit = self.exact.get(path)
        if limit is not None:
            return limit
        return next((limit for glob, limit in self.globs if glob.match(path)), None)


def _limits(max_lines: Mapping[str, int]) -> _Limits:
    globs = sorted(
        (key for key in max_lines if not _GLOB_CHARACTERS.isdisjoint(key)),
        key=lambda key: (-len(key), key),
    )
    return _Limits(
        exact={key: limit for key, limit in max_lines.items() if _GLOB_CHARACTERS.isdisjoint(key)},
        globs=tuple((re.compile(translate(key)), max_lines[key]) for key in globs),
    )


_DEFAULT_LIMITS: Final = _limits(DEFAULT_MAX_LINES)


def text_mode_lines(text: str) -> tuple[str, ...]:
    """The lines of a text as text mode reads them: ``\\r\\n`` or a lone ``\\r`` ends one too."""
    return lines_of(text.replace("\r\n", "\n").replace("\r", "\n"))


def _instructions_size(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    settings = snapshot.hub_config.doctor.rules.instructions_size
    max_lines = None if settings is None else settings.max_lines
    project = _limits(max_lines or {})
    for path in instruction_files(snapshot.hub):
        limit = project.of(path)
        if limit is None:
            limit = _DEFAULT_LIMITS.of(path)
        if limit is None:
            continue
        text = file_text(snapshot.hub.entries.get(path))
        if not isinstance(text, str):
            continue
        count = len(text_mode_lines(text))
        if count > limit:
            yield INSTRUCTIONS_SIZE.finding(
                path=path, message=f"{count} lines, limit {limit}", fix=SIZE_FIX
            )


def _instructions_duplicates(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    # Keyed by the normalized line, so the check stays linear in the files' total size.
    first: dict[str, tuple[str, int]] = {}
    for path in instruction_files(snapshot.hub):
        text = file_text(snapshot.hub.entries.get(path))
        if not isinstance(text, str):
            continue
        for number, line in enumerate(text_mode_lines(text), start=1):
            key = _normalized(line)
            if key is None:
                continue
            first_path, first_line = first.setdefault(key, (path, number))
            if first_path != path:
                yield INSTRUCTIONS_DUPLICATES.finding(
                    path=path,
                    line=number,
                    message=f"duplicates {first_path}:{first_line}",
                    fix=DUPLICATE_FIX,
                )


def _normalized(line: str) -> str | None:
    """The line as the old lint compared it; ``None`` when too short or not an instruction."""
    key = _BLANKS.sub(" ", line.strip().lstrip(_LIST_MARKER)).lower()
    if len(key) < DUPLICATE_MIN_LENGTH or key.startswith(_NOT_AN_INSTRUCTION):
        return None
    return key


INSTRUCTIONS_SIZE: Final = Rule(
    id=INSTRUCTIONS_SIZE_RULE,
    severity=Severity.ERROR,
    summary="instruction files stay within their line limits",
    module=RULE_MODULES.get(INSTRUCTIONS_SIZE_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES}),
    check=_instructions_size,
)

INSTRUCTIONS_DUPLICATES: Final = Rule(
    id=INSTRUCTIONS_DUPLICATES_RULE,
    severity=Severity.ERROR,
    summary="no instruction line of 60 or more characters is repeated in another instruction file",
    module=RULE_MODULES.get(INSTRUCTIONS_DUPLICATES_RULE),
    reads=frozenset({Read.INSTRUCTION_FILES}),
    check=_instructions_duplicates,
)
