"""An issue as a fenced block of untrusted text, for the prompts of ``hub run`` and ``hub start``.

The block holds the issue's id, title, url and description. Its fence is longer than any run of
backticks in that text, so the text cannot close it. The text loses NUL and lone surrogates,
which no argument can hold. The title, url and description are cut at their caps and the id is
bounded by ``ISSUE_ID_PATTERN`` (both tracker adapters refuse any other), so the block's size is
bounded whatever the tracker holds.
"""

import re
from typing import Final

from agent_hub.core.runner.run_texts import well_formed
from agent_hub.core.tracker.tracker_client import Issue

MAX_TITLE_CHARS: Final = 1_000
MAX_DESCRIPTION_CHARS: Final = 20_000
MAX_URL_CHARS: Final = 2_048
TRUNCATED: Final = "\n[truncated]"
_MIN_FENCE = 3
_BACKTICKS = re.compile("`+")


def issue_block(issue: Issue) -> str:
    """The issue's fields in a fenced ``text`` block: the opening fence line to the closing one.

    It neither starts nor ends with a line feed.
    """
    body = well_formed(
        f"id: {issue.id}\n"
        f"title: {_cut(issue.title, MAX_TITLE_CHARS)}\n"
        f"url: {_cut(issue.url, MAX_URL_CHARS)}\n"
        f"description:\n{_cut(issue.description, MAX_DESCRIPTION_CHARS)}"
    )
    fence = "`" * _fence_length(body)
    return f"{fence}text\n{body}\n{fence}"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATED


def _fence_length(text: str) -> int:
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    return max(_MIN_FENCE, longest + 1)
