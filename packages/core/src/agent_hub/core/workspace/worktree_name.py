"""The task worktree name: the tracker issue, optionally with a short description."""

import re


def worktree_name_problem(name: str, *, team: str) -> str | None:
    """Return why ``name`` is not ``<team>-<n>[-<desc>]`` (team lowercased), or None when it is."""
    prefix = team.lower()
    if re.fullmatch(rf"{re.escape(prefix)}-[0-9]+(-[a-z0-9._-]+)?", name):
        return None
    return f"name must be the issue, {prefix}-<n>[-<desc>] (e.g. {prefix}-7-collector)"


def worktree_branch(name: str, *, prefix: str) -> str:
    """Return the task branch: the project's branch prefix followed by the worktree name."""
    return f"{prefix}{name}"
