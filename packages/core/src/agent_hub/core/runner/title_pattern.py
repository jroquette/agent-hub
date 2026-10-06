"""Commit and PR titles rendered from a title pattern, and commit subjects parsed with one.

A title pattern holds ``{ISSUE}``, ``{type}``, ``{scope}`` and ``{summary}`` (see
``hub_config.conventions``). Parsing turns the pattern into an anchored regex: each literal
escaped, ``{summary}`` the only free group, and every other placeholder a fixed character class
that never gives characters back, so a hostile subject costs at most quadratic time. Pure: the
CLI, ``hub start`` and ``hub ship`` render and parse the same way.
"""

import re
from functools import lru_cache
from typing import Final, NamedTuple

from agent_hub.core.hub_config.conventions import PatternPart, fill_pattern, pattern_parts

MAX_PARSED_SUBJECT_CHARS: Final = 1_000
# Each fixed placeholder: a head matched once, then one character class repeated. A class stops
# before the next literal's first character, so it never needs to give one back.
_FIXED_GROUPS: Final = {
    "ISSUE": (r"[A-Za-z][A-Za-z0-9]*+-", r"[0-9]"),
    "type": ("", r"[A-Za-z]"),
    "scope": ("", r"[^()\s]"),
}
_FREE_GROUP: Final = "summary"


class TitleParts(NamedTuple):
    """The values of a title's placeholders; a placeholder the pattern lacks is ``""``."""

    issue: str = ""
    type: str = ""
    scope: str = ""
    summary: str = ""


def render_title(pattern: str, parts: TitleParts) -> str:
    """Return ``pattern`` with each placeholder replaced by its part."""
    values = {
        "ISSUE": parts.issue,
        "type": parts.type,
        "scope": parts.scope,
        "summary": parts.summary,
    }
    return fill_pattern(pattern_parts(pattern), values)


def parse_title(pattern: str, subject: str) -> TitleParts | None:
    """Return the parts of ``subject`` read with ``pattern``, or None when it does not match.

    The whole subject must match. A subject longer than 1 000 characters counts as no match.
    """
    if len(subject) > MAX_PARSED_SUBJECT_CHARS:
        return None
    match = title_regex(pattern).fullmatch(subject)
    if match is None:
        return None
    found = match.groupdict(default="")
    return TitleParts(
        issue=found.get("ISSUE", ""),
        type=found.get("type", ""),
        scope=found.get("scope", ""),
        summary=found.get(_FREE_GROUP, ""),
    )


@lru_cache(maxsize=32)
def title_regex(pattern: str) -> re.Pattern[str]:
    """The regex that parses subjects with a valid title ``pattern``."""
    parts = pattern_parts(pattern)
    pieces = [
        _part_regex(part, following=parts[index + 1] if index + 1 < len(parts) else None)
        for index, part in enumerate(parts)
    ]
    return re.compile("".join(pieces))


def _part_regex(part: PatternPart, *, following: PatternPart | None) -> str:
    name = part.placeholder
    if name is None:
        return re.escape(part.text)
    if name == _FREE_GROUP:
        return f"(?P<{name}>.+)"
    head, repeated = _FIXED_GROUPS[name]
    stop = following.text[0] if following is not None and following.placeholder is None else ""
    if stop and re.fullmatch(repeated, stop):
        repeated = f"(?:(?!{re.escape(stop)}){repeated})"
    return f"(?P<{name}>{head}{repeated}++)"
