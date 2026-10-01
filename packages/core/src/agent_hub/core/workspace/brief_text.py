"""The session brief's text: ``now.md``, the last journal days and each repo's state.

Pure: the CLI reads the files, git, ``gh`` and the clock, and hands the results over; this module
only shapes text. The text is the hub's old brief script byte for byte, its quirks kept (spec
Q-5): the first line of ``now.md``'s body is dropped as its heading even when it is not one, and
failing CI runs read "failing on main" whatever the default branch is.
"""

import calendar
import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict

# About 1.4k tokens; a longer brief is cut and marked.
MAX_CHARS: Final = 5500
# now.md older than this gets a warning.
STALE_DAYS: Final = 3
# Older journal days are not shown: they read as current state.
JOURNAL_MAX_AGE: Final = 7
JOURNAL_COUNT: Final = 2
TITLES_CAP: Final = 300
PR_LINES: Final = 4
PR_CAP: Final = 70

_TRUNCATED: Final = "\n…(truncated)"
_TRUNCATED_ROOM: Final = 20
_MONTHS: Final = 12
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_VERIFIED = re.compile(r"^last_verified:\s*(\d{4}-\d{2}-\d{2})", re.M)
_JOURNAL_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2})\.md$")
_TITLE = re.compile(r"^## (.+)$", re.M)
_FOOTER: Final = (
    "",
    "Linear: n/a (connector not configured for scripts).",
    "More: brain/index.md (pull only what the task needs).",
)


class RepoState(BaseModel):
    """What the brief shows of one checkout; ``prs`` and ``ci`` are ``gh``'s output, or empty."""

    model_config = ConfigDict(frozen=True)

    name: str
    checkout: bool
    branch: str = ""
    dirty: int = 0
    behind: str = ""
    base: str = ""
    prs: str = ""
    ci: str = ""


class BriefInputs(BaseModel):
    """Everything the brief shows: ``now.md``'s text and age, the journal days read, the repos."""

    model_config = ConfigDict(frozen=True)

    now_text: str | None
    now_age_days: int | None
    journal: tuple[tuple[str, str], ...]
    repos: tuple[RepoState, ...]
    network: bool


def now_verified(text: str) -> str | None:
    """The ``last_verified: YYYY-MM-DD`` date of ``now.md``, as written, or None."""
    found = _VERIFIED.search(text)
    return found.group(1) if found else None


def select_journal(paths: Sequence[str], *, cutoff: str) -> tuple[str, ...]:
    """The newest ``JOURNAL_COUNT`` journal paths dated ``cutoff`` (ISO) or later.

    A path without a calendar date in it (``2026/02/30.md`` included) counts as undated and is
    kept, as the old script kept a path with no date.
    """
    kept = [path for path in sorted(paths, reverse=True) if _day_or(path, cutoff) >= cutoff]
    return tuple(kept[:JOURNAL_COUNT])


def journal_day(path: str) -> str:
    """``2026-01-14`` for ``brain/journal/2026/01/14.md``: the last three path segments."""
    return "-".join(path.split("/")[-3:]).removesuffix(".md")


def repo_line(state: RepoState, *, network: bool) -> str:
    """One repo's line, with its open PRs and failing runs under it when the network is on."""
    if not state.checkout:
        return f"- {state.name}: not found"
    behind = state.behind or "?"
    line = (
        f"- {state.name}: {state.branch}, {state.dirty} changed file(s),"
        f" {behind} behind {state.base}"
    )
    if not network:
        return line
    if state.prs:
        prs = " | ".join(pr[:PR_CAP] for pr in state.prs.splitlines()[:PR_LINES])
        line += f"\n  open PRs: {prs}"
    if state.ci:
        line += "\n  ⚠ failing on main: " + ", ".join(sorted(set(state.ci.splitlines())))
    return line


def brief_text(inputs: BriefInputs) -> str:
    """The whole brief, cut to ``MAX_CHARS`` (with a mark) when longer; no final line break."""
    parts = ["# Brief", "", "## Now", *_now_lines(inputs)]
    journal = [_journal_line(path, text) for path, text in inputs.journal]
    parts += ["", f"## Journal (last {JOURNAL_MAX_AGE} days)"]
    parts += journal or ["- (no entry in the last week)"]
    parts += ["", "## Repos", *(repo_line(repo, network=inputs.network) for repo in inputs.repos)]
    parts += _FOOTER
    text = "\n".join(parts)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - _TRUNCATED_ROOM] + _TRUNCATED
    return text


def _now_lines(inputs: BriefInputs) -> list[str]:
    if inputs.now_text is None:
        return ["(brain/now.md missing)"]
    lines = []
    age = inputs.now_age_days
    if age is None or age > STALE_DAYS:
        how_old = "undated" if age is None else f"{age} days old"
        lines.append(
            f"> ⚠ now.md is {how_old}: treat it as possibly stale and check git log / Linear"
            " before trusting it; update it with /handoff."
        )
    lines.append(_without_front_matter(inputs.now_text).split("\n", 1)[-1].strip())
    return lines


def _journal_line(path: str, text: str) -> str:
    titles = _TITLE.findall(_without_front_matter(text))
    return f"- {journal_day(path)}: " + "; ".join(titles)[:TITLES_CAP]


def _without_front_matter(text: str) -> str:
    return _FRONT_MATTER.sub("", text).strip()


def _day_or(path: str, default: str) -> str:
    found = _JOURNAL_DATE.search(path)
    if found is None:
        return default
    year, month, day = (int(part) for part in found.groups())
    if not (1 <= month <= _MONTHS and 1 <= day <= calendar.monthrange(year, month)[1]):
        return default
    return f"{year:04d}-{month:02d}-{day:02d}"
