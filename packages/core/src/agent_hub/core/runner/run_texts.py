"""The texts ``hub run`` writes for others: the PR body, the tracker comments, the inbox line.

The PR body and the comments are the user's (spec D14, D-comment): the implementing session's
summary loses the workspace's absolute path (paths become repo-relative) and every line that
``hub doctor``'s ``attribution.ai`` rule would flag; no text names an agent. Each summary is cut
at its cap, so a PR body fits one argument and a comment stays short (E21).
"""

import re
from typing import Final

from agent_hub.core.doctor.text_rules import ATTRIBUTIONS

MAX_COMMIT_SUMMARY_CHARS: Final = 1_200
MAX_PR_SUMMARY_CHARS: Final = 20_000
MAX_SUCCESS_SUMMARY_CHARS: Final = 600
MAX_DIAGNOSIS_CHARS: Final = 900
WORKSPACE_WORDS: Final = "the workspace"
# A path character: the workspace's path followed or preceded by one is another path.
_PATH_CHARACTER = r"[\w./-]"


def sanitized_summary(text: str, *, workspace: str) -> str:
    """``text`` with ``<workspace>/`` removed, the workspace itself named in words, and every
    attribution line dropped."""
    root = re.escape(workspace.rstrip("/"))
    relative = re.sub(rf"(?<!{_PATH_CHARACTER}){root}/", "", text)
    named = re.sub(rf"(?<!{_PATH_CHARACTER}){root}(?![\w-])", WORKSPACE_WORDS, relative)
    kept = (
        line for line in named.split("\n") if not any(shape.matches(line) for shape in ATTRIBUTIONS)
    )
    return "\n".join(kept)


def commit_summary(text: str) -> str:
    """The commits' messages as a summary, when the session gave none: at most 1 200 characters."""
    return text.strip()[:MAX_COMMIT_SUMMARY_CHARS]


def pr_body(*, issue_id: str, summary: str, gate: str) -> str:
    """The PR body: the issue id, the summary (cut at its cap) and the gate that passed."""
    return (
        f"{issue_id}\n\n{summary[:MAX_PR_SUMMARY_CHARS]}\n\n## Verification\nGates green: `{gate}`."
    )


def success_comment(*, run_id: str, pr_url: str, summary: str) -> str:
    """The tracker comment of a run that opened its PR."""
    return f"Run {run_id} opened {pr_url}. {summary[:MAX_SUCCESS_SUMMARY_CHARS]}"


def failure_comment(*, run_id: str, stage: str, reason: str) -> str:
    """The tracker comment of a run that failed at ``stage``."""
    return f"Run {run_id} failed at {stage}. Diagnosis: {reason[:MAX_DIAGNOSIS_CHARS]}"


def inbox_line(*, issue_id: str, repo: str, run_id: str, outcome: str, cost_usd: float) -> str:
    """The run's line in ``brain/_inbox/runs/<date>.md`` (``outcome``: ``PR <url>`` or
    ``FAILED at <STAGE>``)."""
    return f"- {issue_id} ({repo}) run {run_id}: {outcome}; ${cost_usd:.2f}"
