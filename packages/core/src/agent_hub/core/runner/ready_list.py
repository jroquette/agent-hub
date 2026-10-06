"""The lines of ``hub next``: the tracker's ready issues, oldest first, each with its repo."""

from collections.abc import Collection, Iterable, Sequence

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.team_keys import teams_text
from agent_hub.core.tracker.tracker_client import Issue

# Shown when no label, or more than one, names a repo of the hub.
UNKNOWN_REPO = "?"


class ReadyRow(BaseModel):
    """One ready issue as ``hub next`` shows it: id, repo (or ``?``), title and url."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    repo: str
    title: str
    url: str


def issue_number(issue_id: str) -> int:
    """The number of an issue id such as ``DEM-12`` (12); the id matches ``ISSUE_ID_PATTERN``."""
    return int(issue_id.rpartition("-")[2])


def repo_of(labels: Iterable[str], *, repos: Collection[str]) -> str:
    """The one repo ``dir`` among ``labels``; ``?`` when none or several match."""
    matched = {label for label in labels if label in repos}
    if len(matched) != 1:
        return UNKNOWN_REPO
    return matched.pop()


def ready_rows(issues: Iterable[Issue], *, repos: Collection[str]) -> list[ReadyRow]:
    """The rows of ``issues``, in issue-number order (``DEM-3`` before ``DEM-12``)."""
    ordered = sorted(issues, key=lambda issue: (issue_number(issue.id), issue.id))
    return [
        ReadyRow(
            id=issue.id,
            repo=repo_of(issue.labels, repos=repos),
            title=issue.title,
            url=issue.url,
        )
        for issue in ordered
    ]


def no_ready_line(*, teams: Sequence[str], label: str) -> str:
    """The line ``hub next`` prints when nothing is ready in ``teams`` (``team`` for one)."""
    noun = "team" if len(teams) == 1 else "teams"
    return f"no ready issues ({noun} {teams_text(teams)}, label {label})"


def team_failure_line(*, team: str, reason: str, team_count: int) -> str:
    """The line for a team whose ``list_ready`` failed: the reason alone on a one-team hub."""
    if team_count == 1:
        return reason
    return f"team {team}: {reason}"
