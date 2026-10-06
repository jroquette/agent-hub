"""The branch and title shapes and examples a configured hub's texts show; pure.

``shown_conventions`` is their one source: the generator renders ``AGENTS.md``'s Conventions
block and rule 1's branch from it, and doctor ``instructions.refs`` skips exactly its texts as
code spans (AGH-57, plan O1 a, E32), so the two cannot drift. ``shown_prefix`` is the one source
of the rendered ``{prefix}``, configured hub or not.

Title examples are filled with ``fill_pattern``, the primitive ``runner.title_pattern``'s
``render_title`` wraps: importing ``runner`` here would close a package cycle (``runner`` reads
``doctor``, which reads this module).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple

from agent_hub.core.hub_config.conventions import fill_pattern, pattern_parts
from agent_hub.core.hub_config.model import PREFIX_PLACEHOLDER, Conventions, HubConfig
from agent_hub.core.workspace.branch_pattern import (
    EXAMPLE_NUMBER,
    branch_example,
    branch_shape_text,
)

# The keys a repo line names, in the order the texts show them.
OVERRIDE_KEYS: Final = ("branch", "commit_title", "pr_title")
# The example title's parts other than the issue (plan § Design 7).
_EXAMPLE_TITLE: Final = {"type": "feat", "scope": "core", "summary": "add the collector"}


class ShownPattern(NamedTuple):
    """A pattern as rendered texts show it: its shape and its example."""

    shape: str
    example: str


class ShownRepo(NamedTuple):
    """What the texts show of one repo."""

    # Its effective branch. The texts render only an overriding repo's shape; its example is
    # not rendered, yet doctor skips it too (E31 a).
    branch: ShownPattern
    # Each key its ``conventions`` sets, in ``OVERRIDE_KEYS`` order, to the shape its line
    # shows: the branch with ``{prefix}`` rendered, a title as written.
    overrides: Mapping[str, str]


@dataclass(frozen=True, kw_only=True, slots=True)
class ShownConventions:
    """The branch and title shapes and examples of a hub that sets conventions."""

    # The project's effective patterns.
    branch: ShownPattern
    commit_title: ShownPattern
    pr_title: ShownPattern
    # Each repo, by dir in ``hub.json`` order.
    repos: Mapping[str, ShownRepo]

    def texts(self) -> frozenset[str]:
        """Every shape and example: the project's, each repo's branch and its overrides."""
        project = (*self.branch, *self.commit_title, *self.pr_title)
        repos = (
            text
            for repo in self.repos.values()
            for text in (*repo.branch, *repo.overrides.values())
        )
        return frozenset((*project, *repos))


def shown_prefix(config: HubConfig) -> str:
    """The rendered ``{prefix}``: ``project.branch_prefix``, else ``<prefix>``."""
    return config.project.branch_prefix or PREFIX_PLACEHOLDER


def shown_conventions(config: HubConfig) -> ShownConventions | None:
    """The shapes and examples ``config``'s texts show; ``None`` when it sets no conventions.

    Examples use the default tracker team, issue 7, the description ``collector`` and the
    title ``feat``, ``core``, ``add the collector``.
    """
    if not config.sets_conventions:
        return None
    prefix = shown_prefix(config)
    team = config.tracker.default_team
    title_values = {"ISSUE": f"{team}-{EXAMPLE_NUMBER}", **_EXAMPLE_TITLE}

    def branch(pattern: str) -> ShownPattern:
        return ShownPattern(
            shape=branch_shape_text(pattern, shown_prefix=prefix),
            example=branch_example(pattern, shown_prefix=prefix, team=team),
        )

    def title(pattern: str) -> ShownPattern:
        return ShownPattern(
            shape=pattern, example=fill_pattern(pattern_parts(pattern), title_values)
        )

    def repo(repo_dir: str, own: Conventions | None) -> ShownRepo:
        set_keys: dict[str, str | None] = (
            {} if own is None else {key: getattr(own, key) for key in OVERRIDE_KEYS}
        )
        overrides = {
            key: branch_shape_text(value, shown_prefix=prefix) if key == "branch" else value
            for key, value in set_keys.items()
            if value is not None
        }
        return ShownRepo(
            branch=branch(config.conventions_for(repo_dir).branch), overrides=overrides
        )

    project = config.project_conventions
    return ShownConventions(
        branch=branch(project.branch),
        commit_title=title(project.commit_title),
        pr_title=title(project.pr_title),
        repos={r.dir: repo(r.dir, r.conventions) for r in config.repos},
    )
