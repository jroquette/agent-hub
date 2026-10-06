"""The task worktree name: the tracker issue, optionally with a short description."""

import re
from collections.abc import Sequence

from agent_hub.core.hub_config.team_keys import teams_text
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
