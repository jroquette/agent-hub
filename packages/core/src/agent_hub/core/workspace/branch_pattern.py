"""A task branch rendered from a branch pattern, and the pattern's shape and example for texts.

``{prefix}`` is the developer's branch prefix, ``{ISSUE}`` the issue id uppercased,
``{issue_lower}`` the same lowercased and ``{slug}`` the worktree's description. Pure: the
generator and the doctor show the same shapes the CLI renders.
"""

from agent_hub.core.hub_config.conventions import fill_pattern, pattern_parts

# The issue number and description of the example branch shown in rendered texts.
_EXAMPLE_NUMBER = 7
_EXAMPLE_SLUG = "collector"


def render_branch(pattern: str, *, prefix: str, issue_id: str, slug: str) -> str:
    """Return the branch ``pattern`` gives for ``issue_id`` and ``slug`` under ``prefix``.

    An empty ``slug`` also drops one separator right before ``{slug}``.
    """
    values = {
        "prefix": prefix,
        "ISSUE": issue_id.upper(),
        "issue_lower": issue_id.lower(),
        "slug": slug,
    }
    return fill_pattern(pattern_parts(pattern), values)


def branch_shape_text(pattern: str, *, shown_prefix: str) -> str:
    """Return ``pattern`` with ``{prefix}`` shown as ``shown_prefix`` and the rest as written."""
    return "".join(
        shown_prefix if part.placeholder == "prefix" else part.text
        for part in pattern_parts(pattern)
    )


def branch_example(pattern: str, *, shown_prefix: str, team: str) -> str:
    """Return the example branch for ``team``'s issue 7 with the description ``collector``."""
    return render_branch(
        pattern,
        prefix=shown_prefix,
        issue_id=f"{team}-{_EXAMPLE_NUMBER}",
        slug=_EXAMPLE_SLUG,
    )
