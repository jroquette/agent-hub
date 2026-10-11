"""The texts ``hub ship`` writes for others: the PR body, its Related PRs section, the comment.

A PR body holds the issue id (and its url, when it is one printable ``https://`` url), then one
section between ``RELATED_START`` and ``RELATED_END`` that lists the other PRs of the issue.
``with_related`` replaces that section in a body read back from GitHub, so a re-run never adds a
second one. The text outside the markers is untrusted and the user's: it is kept byte for byte,
except that every attribution or robot line is dropped and the workspace's path is named as
``sanitized_summary`` names it (spec E6), and NUL and lone surrogates go, so an argv can hold it.
"""

import re
from collections.abc import Sequence
from typing import Final

from agent_hub.core.runner.run_texts import (
    is_attribution,
    sanitized_summary,
    well_formed,
    without_workspace,
)

RELATED_START: Final = "<!-- hub-ship:related-prs:start -->"
RELATED_END: Final = "<!-- hub-ship:related-prs:end -->"
MAX_ISSUE_URL_CHARS: Final = 2_048
_URL_SCHEME: Final = "https://"
_RELATED_HEADING: Final = "## Related PRs"
# A later section: from its start marker to its end marker, or to the end of the body.
_LATER_SECTION: Final = re.compile(
    f"{re.escape(RELATED_START)}.*?(?:{re.escape(RELATED_END)}|\\Z)", re.DOTALL
)


def ship_body(*, issue_id: str, issue_url: str | None) -> str:
    """A new PR's body: the issue id, its url when it is one printable ``https://`` url of at
    most ``MAX_ISSUE_URL_CHARS``, then an empty Related PRs section."""
    shown = f" {issue_url}" if issue_url is not None and _is_shown_url(issue_url) else ""
    return f"{issue_id}{shown}\n\n{_section(())}"


def with_related(body: str, *, urls: Sequence[str], workspace: str) -> str:
    """``body`` with its first Related PRs section listing ``urls`` (a start marker without an
    end runs to the end of the body), later sections dropped, and one section appended when it
    has none; the text outside the markers cleaned as the module says."""
    text = well_formed(body)
    section = _section(urls)
    start = text.find(RELATED_START)
    if start < 0:
        outside = _cleaned(text, workspace=workspace)
        return f"{outside}\n\n{section}" if outside else section
    end = text.find(RELATED_END, start + len(RELATED_START))
    after = "" if end < 0 else _LATER_SECTION.sub("", text[end + len(RELATED_END) :])
    before = _cleaned(text[:start], workspace=workspace)
    return f"{before}{section}{_cleaned(after, workspace=workspace)}"


def ship_comment(*, urls: Sequence[str], workspace: str) -> str:
    """The tracker comment of a shipped issue: one line per PR url, in the given order, cleaned
    as ``sanitized_summary`` cleans (no agent named)."""
    listed = "".join(f"\n- {url}" for url in urls)
    return sanitized_summary(f"Pull requests:{listed}", workspace=workspace)


def _section(urls: Sequence[str]) -> str:
    listed = "".join(f"- {url}\n" for url in urls)
    return f"{RELATED_START}\n{_RELATED_HEADING}\n{listed}{RELATED_END}"


def _cleaned(text: str, *, workspace: str) -> str:
    named = without_workspace(text, workspace=workspace)
    return "\n".join(line for line in named.split("\n") if not is_attribution(line))


def _is_shown_url(url: str) -> bool:
    return (
        url.startswith(_URL_SCHEME)
        and url.isprintable()
        and " " not in url
        and len(url) <= MAX_ISSUE_URL_CHARS
    )
