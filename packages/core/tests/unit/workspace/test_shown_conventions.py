from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.title_pattern import TitleParts, render_title
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document
from agent_hub.core.workspace.shown_conventions import (
    ShownPattern,
    ShownRepo,
    shown_conventions,
    shown_prefix,
)

MIXED_TITLE = "{ISSUE}: {type}({scope}): {summary}"
MIXED_TITLE_EXAMPLE = "DEM-7: feat(core): add the collector"


def test_shows_project_and_repo_patterns_when_hub_sets_conventions() -> None:
    shown = shown_conventions(HubConfig.model_validate(a_conventions_document()))

    assert shown is not None
    assert shown.branch == ShownPattern("jdoe/{ISSUE}-{slug}", "jdoe/DEM-7-collector")
    assert shown.commit_title == ShownPattern(MIXED_TITLE, MIXED_TITLE_EXAMPLE)
    assert shown.pr_title == ShownPattern(MIXED_TITLE, MIXED_TITLE_EXAMPLE)
    # Each repo's effective branch, in hub.json order: demo-web inherits the project's.
    assert shown.repos == {
        "demo-api": ShownRepo(
            ShownPattern("feature/{issue_lower}/{slug}", "feature/dem-7/collector"),
            {"branch": "feature/{issue_lower}/{slug}"},
        ),
        "demo-web": ShownRepo(ShownPattern("jdoe/{ISSUE}-{slug}", "jdoe/DEM-7-collector"), {}),
    }
    assert list(shown.repos) == ["demo-api", "demo-web"]
    assert shown.texts() == {
        "jdoe/{ISSUE}-{slug}",
        "jdoe/DEM-7-collector",
        MIXED_TITLE,
        MIXED_TITLE_EXAMPLE,
        "feature/{issue_lower}/{slug}",
        "feature/dem-7/collector",
    }


def test_shows_repo_titles_when_repo_overrides_them() -> None:
    # E32: a repo's own titles are shown as written, keys in branch, commit, PR order.
    document = a_conventions_document()
    document["project"]["conventions"]["commit_title"] = "wip/{summary}"
    document["project"]["conventions"]["pr_title"] = "{ISSUE}: {summary}"
    document["repos"][0]["conventions"] = {
        "pr_title": "x/{ISSUE}-{summary}",
        "branch": "{prefix}rel/{ISSUE}",
    }

    shown = shown_conventions(HubConfig.model_validate(document))

    assert shown is not None
    assert shown.commit_title == ShownPattern("wip/{summary}", "wip/add the collector")
    assert list(shown.repos["demo-api"].overrides.items()) == [
        ("branch", "jdoe/rel/{ISSUE}"),
        ("pr_title", "x/{ISSUE}-{summary}"),
    ]
    assert {"wip/{summary}", "wip/add the collector", "x/{ISSUE}-{summary}"} <= shown.texts()


@pytest.mark.parametrize(
    "pattern",
    ["{ISSUE}: {summary}", "wip/{summary}", "{type}/{summary}/x", "x/{ISSUE}-{summary}.md"],
)
def test_shows_runtime_render_when_title_example_rendered(pattern: str) -> None:
    # The example is what ``hub run`` would render for the same parts.
    document = a_conventions_document()
    document["project"]["conventions"] = {"commit_title": pattern}

    shown = shown_conventions(HubConfig.model_validate(document))

    parts = TitleParts(issue="DEM-7", type="feat", scope="core", summary="add the collector")
    assert shown is not None
    assert shown.commit_title.example == render_title(pattern, parts)


def test_shows_default_patterns_when_repo_conventions_empty() -> None:
    # An empty object still sets conventions: the texts show the default shapes, and no override.
    document: dict[str, Any] = a_hub_document()
    document["repos"][0]["conventions"] = {}

    shown = shown_conventions(HubConfig.model_validate(document))

    assert shown is not None
    assert shown.branch == ShownPattern("jdoe/{issue_lower}-{slug}", "jdoe/dem-7-collector")
    assert shown.repos["demo-api"].overrides == {}


def test_shows_nothing_when_hub_sets_no_conventions() -> None:
    assert shown_conventions(HubConfig.model_validate(a_hub_document())) is None


@pytest.mark.parametrize(("prefix", "shown"), [("jdoe/", "jdoe/"), (None, "<prefix>")])
def test_shows_prefix_or_placeholder_when_prefix_set_or_unset(
    prefix: str | None, shown: str
) -> None:
    document = a_hub_document()
    if prefix is None:
        del document["project"]["branch_prefix"]
    else:
        document["project"]["branch_prefix"] = prefix

    assert shown_prefix(HubConfig.model_validate(document)) == shown
