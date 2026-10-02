"""The texts ``hub run`` writes for others: the PR body, the tracker comments, the inbox line.

The PR body and the comments are the user's (spec D14, D-comment). Every builder that takes
text from the implementing session, a commit or a gate cleans it first (``sanitized_summary``):
paths under the workspace become workspace-relative, control and bidi characters go, and every
line ``hub doctor``'s ``attribution.ai`` rule would flag, or that holds the robot emoji, is
dropped; no text names an agent. Each text is cut at its cap, so a PR body fits one argument and
a comment stays short (E21).
"""

import re
from typing import Final

from agent_hub.core.doctor.text_rules import ATTRIBUTIONS

MAX_COMMIT_SUMMARY_CHARS: Final = 1_200
MAX_PR_SUMMARY_CHARS: Final = 20_000
MAX_SUCCESS_SUMMARY_CHARS: Final = 600
MAX_DIAGNOSIS_CHARS: Final = 900
MAX_PR_TITLE_CHARS: Final = 256
WORKSPACE_WORDS: Final = "the workspace"
ROBOT: Final = "\N{ROBOT FACE}"
# A path character: the workspace's path followed or preceded by one is another path.
_PATH_CHARACTER = r"[\w./-]"
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
# A whole 7-bit terminal escape sequence (CSI and OSC; ESC alone would leave "[2J" behind), then
# any control left: C0 but tab and line feed, DEL, C1, the bidi embeddings, overrides, isolates
# and marks, and the zero-width characters (which could split an attribution line in two).
_ESCAPE_SEQUENCE = re.compile("\x1b\\[[0-?]*[ -/]*[@-~]|\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)?")
_UNSAFE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)


def well_formed(text: str) -> str:
    """``text`` that any argv or file can hold: NUL dropped, lone surrogates replaced."""
    return _LONE_SURROGATE.sub("\ufffd", text.replace("\x00", ""))


def plain_text(text: str) -> str:
    """``text`` well formed, without terminal escapes, controls (but tab and line feed) or bidi
    formatting characters."""
    return _UNSAFE.sub("", _ESCAPE_SEQUENCE.sub("", well_formed(text)))


def sanitized_summary(text: str, *, workspace: str) -> str:
    """``text`` made plain, ``[file://]<workspace>/`` removed (paths become workspace-relative),
    the workspace itself named in words, and every attribution or robot line dropped."""
    root = rf"(?<!{_PATH_CHARACTER})(?:file://)?{re.escape(workspace.rstrip('/'))}"
    relative = re.sub(rf"{root}/", "", plain_text(text))
    named = re.sub(rf"{root}(?![\w-])", WORKSPACE_WORDS, relative)
    return "\n".join(line for line in named.split("\n") if not _is_attribution(line))


def _is_attribution(line: str) -> bool:
    return ROBOT in line or any(shape.matches(line) for shape in ATTRIBUTIONS)


def commit_summary(text: str, *, workspace: str) -> str:
    """The commits' messages as a summary, when the session gave none: cleaned, at most 1 200
    characters."""
    return sanitized_summary(text, workspace=workspace).strip()[:MAX_COMMIT_SUMMARY_CHARS]


def pr_title(subject: str, *, workspace: str, fallback: str) -> str:
    """The PR title: the commit subject cleaned, its first line, at most 256 characters;
    ``fallback`` when nothing is left."""
    lines = (line.strip() for line in sanitized_summary(subject, workspace=workspace).split("\n"))
    first = next((line for line in lines if line), "")
    return first[:MAX_PR_TITLE_CHARS] or fallback


def pr_body(*, issue_id: str, summary: str, gate: str, workspace: str) -> str:
    """The PR body: the issue id, the summary (cleaned, cut at its cap) and the gate that passed."""
    shown = sanitized_summary(summary, workspace=workspace)[:MAX_PR_SUMMARY_CHARS]
    return f"{issue_id}\n\n{shown}\n\n## Verification\nGates green: `{gate}`."


def success_comment(*, run_id: str, pr_url: str, summary: str, workspace: str) -> str:
    """The tracker comment of a run that opened its PR; the summary cleaned and cut."""
    shown = sanitized_summary(summary, workspace=workspace)[:MAX_SUCCESS_SUMMARY_CHARS]
    return f"Run {run_id} opened {pr_url}. {shown}"


def failure_comment(*, run_id: str, stage: str, reason: str, workspace: str) -> str:
    """The tracker comment of a run that failed at ``stage``; the reason cleaned and cut."""
    shown = sanitized_summary(reason, workspace=workspace)[:MAX_DIAGNOSIS_CHARS]
    return f"Run {run_id} failed at {stage}. Diagnosis: {shown}"


def inbox_line(*, issue_id: str, repo: str, run_id: str, outcome: str, cost_usd: float) -> str:
    """The run's line in ``brain/_inbox/runs/<date>.md`` (``outcome``: ``PR <url>`` or
    ``FAILED at <STAGE>``)."""
    return f"- {issue_id} ({repo}) run {run_id}: {outcome}; ${cost_usd:.2f}"
