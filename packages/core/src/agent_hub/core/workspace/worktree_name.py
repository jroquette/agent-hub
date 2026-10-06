"""The task worktree name: the tracker issue, optionally with a short description."""

import re
from collections.abc import Sequence

from agent_hub.core.hub_config.team_keys import teams_text


def worktree_name_problem(name: str, *, teams: Sequence[str]) -> str | None:
    """Why ``name`` is not ``<team>-<n>[-<desc>]`` for a key of ``teams`` (lowercased), or None."""
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


def worktree_branch(name: str, *, prefix: str) -> str:
    """Return the task branch: the project's branch prefix followed by the worktree name."""
    return f"{prefix}{name}"
