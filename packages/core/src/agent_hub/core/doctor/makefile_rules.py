"""``makefile.override``: ``Makefile.project`` redefines no target of the managed ``Makefile``.

``hub sync`` owns ``Makefile``, which includes the project's ``Makefile.project`` last; a rule
there for a target the managed file defines replaces its recipe (docs/design/hub-generator.md).
The managed targets are read from ``Makefile``'s own text, never a fixed list. A rule line is a
logical line (``\\``-continued physical lines joined) outside a ``define`` block that does not
start with a tab (a recipe line) and names its targets before ``:`` or ``::``; an assignment
(``:=``, ``::=``, ``:::=``, ``=``, ``?=``, ``+=``) or a comment is none. Special targets such as
``.PHONY`` are not managed targets. A grouped rule (GNU make 4.3+, ``&:`` or ``&::``) names its
targets the same way, and a target named twice on one line is reported once. Targets written
through variables (``$(T):``) are not expanded, and files pulled in by ``-include`` are not
followed. Either file absent or not text: nothing to check.
"""

import re
from collections.abc import Iterable, Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, lines_of, text_of
from agent_hub.core.hub_config.doctor_rules import MAKEFILE_OVERRIDE_RULE, RULE_MODULES, Severity

MANAGED_MAKEFILE: Final = "Makefile"
PROJECT_MAKEFILE: Final = "Makefile.project"
FIX: Final = "rename the project target"

# Targets, separated by blanks, then ``:`` or ``::`` (``&`` first for a grouped rule) not starting
# an assignment operator. Only spaces may lead: a line led by a tab is a recipe line. No name
# character is a blank, so each name ends where the next part starts: matching stays linear.
_RULE_LINE: Final = re.compile(r" *([^\s:#=&]+(?:\s+[^\s:#=&]+)*)\s*&?::?(?![:=])")
_DEFINE: Final = re.compile(r" *(?:(?:override|export|private)\s+)*define(?:\s|$)")
_ENDEF: Final = re.compile(r" *endef(?:\s|$)")
# ``.PHONY``, ``.DEFAULT``, ``.SUFFIXES`` and the other names make gives a meaning.
_SPECIAL_TARGET: Final = re.compile(r"\.[A-Z_]+")


def _makefile_override(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    entries = snapshot.hub.entries
    project = text_of(entries.get(PROJECT_MAKEFILE))
    managed = text_of(entries.get(MANAGED_MAKEFILE))
    if project is None or managed is None:
        return ()
    targets = _managed_targets(managed)
    return tuple(
        MAKEFILE_OVERRIDE.finding(
            path=PROJECT_MAKEFILE, line=number, message=f"redefines target '{name}'", fix=FIX
        )
        for number, names in _rule_lines(project)
        for name in names
        if name in targets
    )


def _managed_targets(text: str) -> frozenset[str]:
    return frozenset(
        name
        for _, names in _rule_lines(text)
        for name in names
        if not _SPECIAL_TARGET.fullmatch(name)
    )


def _rule_lines(text: str) -> Iterator[tuple[int, tuple[str, ...]]]:
    """Each rule line's 1-based first physical line and the targets it names."""
    depth = 0
    for number, line in _logical_lines(text):
        if _DEFINE.match(line):
            depth += 1
        elif depth:
            if _ENDEF.match(line):
                depth -= 1
        elif match := _RULE_LINE.match(line):
            yield number, tuple(dict.fromkeys(match.group(1).split()))


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Physical lines (a trailing ``\\r`` dropped) joined at an unescaped final ``\\``."""
    start, parts = 0, list[str]()
    for number, physical in enumerate(lines_of(text), start=1):
        line = physical.removesuffix("\r")
        start = start or number
        trailing = len(line) - len(line.rstrip("\\"))
        if trailing % 2:
            parts.append(line[:-1])
            continue
        yield start, " ".join([*parts, line])
        start, parts = 0, []
    if parts:
        yield start, " ".join(parts)


MAKEFILE_OVERRIDE: Final = Rule(
    id=MAKEFILE_OVERRIDE_RULE,
    severity=Severity.WARNING,
    summary="Makefile.project does not redefine a target of the managed Makefile",
    module=RULE_MODULES.get(MAKEFILE_OVERRIDE_RULE),
    reads=frozenset(),
    check=_makefile_override,
)
