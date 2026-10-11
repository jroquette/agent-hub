"""The task worktree name: the tracker issue, optionally with a short description."""

import re
from collections.abc import Iterable, Sequence

from agent_hub.core.hub_config.team_keys import team_of, teams_text
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN
from agent_hub.core.workspace.branch_pattern import render_branch

# A validated name: the issue (``<team>-<n>``, lowercase) and, after a dash, the description.
# Team keys are ``[A-Za-z0-9]+`` (``TeamKey`` in ``model.py``), so the first dash ends the team.
_NAME_PARTS = re.compile(r"([a-z0-9]+-[0-9]+)(?:-(.*))?")


def worktree_name_problem(name: str, *, teams: Sequence[str]) -> str | None:
    """Why ``name`` is not ``<team>-<n>[-<desc>]`` for a key of ``teams`` (lowercased), or None.

    ``teams`` must be non-empty (a validated config's ``Tracker.team_keys`` always is).
    """
    keys = "|".join(re.escape(team.lower()) for team in teams)
    if re.fullmatch(rf"(?:{keys})-[0-9]+(-[a-z0-9._-]+)?", name):
        return None
    example = worktree_name_example(teams[0])
    if len(teams) == 1:
        return f"name must be the issue, {teams[0].lower()}-<n>[-<desc>] (e.g. {example})"
    return (
        f"name must be the issue, <team>-<n>[-<desc>] in lowercase (e.g. {example});"
        f" use one of: {teams_text(teams)}"
    )


def task_worktree_names(
    names: Iterable[str], *, issue_id: str, teams: Sequence[str]
) -> tuple[str, ...]:
    """The valid worktree names of ``names`` whose issue is ``issue_id``, sorted.

    The whole issue part is compared, so ``dem-70`` is never a task worktree of ``DEM-7``.
    """
    wanted = issue_id.lower()
    return tuple(
        sorted(
            name
            for name in names
            if worktree_name_problem(name, teams=teams) is None and _issue_part(name) == wanted
        )
    )


def issue_of_worktree(name: str, *, teams: Sequence[str]) -> str | None:
    """The issue id a task worktree name stands for (``<TEAM>-<n>``, uppercase), or None.

    None when ``name`` is not ``<team>-<n>[-<desc>]`` for a key of ``teams``, or when its
    issue is no valid id (``ISSUE_ID_PATTERN``: no ``0`` or leading zero), so a command never
    refuses the id it derived.
    """
    issue = _issue_part(name) if worktree_name_problem(name, teams=teams) is None else None
    if issue is None or team_of(issue, teams) is None:
        return None
    upper = issue.upper()
    return upper if ISSUE_ID_PATTERN.fullmatch(upper) else None


def worktree_name_example(team: str) -> str:
    """An example of a valid worktree name for ``team``."""
    return f"{team.lower()}-7-collector"


def worktree_branch(name: str, *, prefix: str, pattern: str) -> str:
    """Return the task branch ``pattern`` gives for a validated worktree name.

    The name's issue fills ``{ISSUE}``/``{issue_lower}`` and its description ``{slug}``
    (empty without one). The default pattern gives ``prefix`` followed by the name.
    """
    parts = _NAME_PARTS.fullmatch(name)
    if parts is None:
        msg = f"not a worktree name: {name!r}"
        raise ValueError(msg)
    issue_id, slug = parts.group(1), parts.group(2) or ""
    return render_branch(pattern, prefix=prefix, issue_id=issue_id, slug=slug)


def _issue_part(name: str) -> str | None:
    parts = _NAME_PARTS.fullmatch(name)
    return None if parts is None else parts.group(1)
