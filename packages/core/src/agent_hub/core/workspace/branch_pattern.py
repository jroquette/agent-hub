"""A task branch rendered from a branch pattern, and the pattern's shape and example for texts.

``{prefix}`` is the developer's branch prefix, ``{ISSUE}`` the issue id uppercased,
``{issue_lower}`` the same lowercased and ``{slug}`` the worktree's description. Pure: the
generator and the doctor show the same shapes the CLI renders. ``shown_branches`` is the one
source of the shapes and examples a configured hub's texts show: the generator renders them and
doctor ``instructions.refs`` skips them as code spans (AGH-57, plan O1 a), so the two cannot drift.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from agent_hub.core.hub_config.conventions import fill_pattern, pattern_parts
from agent_hub.core.hub_config.model import PREFIX_PLACEHOLDER, HubConfig

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


class ShownBranch(NamedTuple):
    """A branch pattern as rendered texts show it: its shape and its example."""

    shape: str
    example: str


@dataclass(frozen=True, kw_only=True, slots=True)
class ShownBranches:
    """The branch shapes and examples of a hub that sets conventions."""

    # The rendered prefix: ``project.branch_prefix``, else ``<prefix>``.
    shown_prefix: str
    project: ShownBranch
    # Each repo's effective branch, by dir in ``hub.json`` order.
    repos: Mapping[str, ShownBranch]

    def texts(self) -> frozenset[str]:
        """Every shape and example, the project's and each repo's."""
        return frozenset(text for shown in (self.project, *self.repos.values()) for text in shown)


def shown_branches(config: HubConfig) -> ShownBranches | None:
    """The shapes and examples ``config``'s texts show; ``None`` when it sets no conventions.

    Examples use the default tracker team, issue 7 and the description ``collector``.
    """
    if not config.sets_conventions:
        return None
    shown_prefix = config.project.branch_prefix or PREFIX_PLACEHOLDER
    team = config.tracker.default_team

    def shown(pattern: str) -> ShownBranch:
        return ShownBranch(
            shape=branch_shape_text(pattern, shown_prefix=shown_prefix),
            example=branch_example(pattern, shown_prefix=shown_prefix, team=team),
        )

    return ShownBranches(
        shown_prefix=shown_prefix,
        project=shown(config.project_conventions.branch),
        repos={repo.dir: shown(config.conventions_for(repo.dir).branch) for repo in config.repos},
    )
