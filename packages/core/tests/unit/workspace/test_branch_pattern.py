from typing import Any

import pytest

from agent_hub.core.hub_config.conventions import DEFAULT_BRANCH
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document
from agent_hub.core.workspace.branch_pattern import (
    ShownBranch,
    branch_example,
    branch_shape_text,
    render_branch,
    shown_branches,
)


@pytest.mark.parametrize(
    ("slug", "branch"),
    [("collector", "roquettejh/agh-7-collector"), ("", "roquettejh/agh-7")],
)
def test_renders_default_branch_when_slug_given_or_empty(slug: str, branch: str) -> None:
    rendered = render_branch(DEFAULT_BRANCH, prefix="roquettejh/", issue_id="AGH-7", slug=slug)

    assert rendered == branch


@pytest.mark.parametrize(
    ("pattern", "slug", "branch"),
    [
        ("{prefix}{ISSUE}-{slug}", "x", "me/DEM-7-x"),
        ("{prefix}{ISSUE}-{slug}", "", "me/DEM-7"),
        ("feature/{issue_lower}/{slug}", "", "feature/dem-7"),
        ("{prefix}{issue_lower}_{slug}", "", "me/dem-7"),
        ("{prefix}{issue_lower}.{slug}", "", "me/dem-7"),
        ("{prefix}{issue_lower}{slug}", "", "me/dem-7"),
    ],
)
def test_renders_configured_branch_when_pattern_set(pattern: str, slug: str, branch: str) -> None:
    assert render_branch(pattern, prefix="me/", issue_id="DEM-7", slug=slug) == branch


def test_ignores_slug_when_pattern_has_none() -> None:
    rendered = render_branch("{prefix}{issue_lower}", prefix="me/", issue_id="DEM-7", slug="x")

    assert rendered == "me/dem-7"


@pytest.mark.parametrize(
    ("pattern", "shown_prefix", "shape", "example"),
    [
        (DEFAULT_BRANCH, "jdoe/", "jdoe/{issue_lower}-{slug}", "jdoe/dem-7-collector"),
        ("{prefix}{ISSUE}-{slug}", "jdoe/", "jdoe/{ISSUE}-{slug}", "jdoe/DEM-7-collector"),
        ("{prefix}{ISSUE}-{slug}", "<prefix>", "<prefix>{ISSUE}-{slug}", "<prefix>DEM-7-collector"),
        (
            "feature/{issue_lower}/{slug}",
            "jdoe/",
            "feature/{issue_lower}/{slug}",
            "feature/dem-7/collector",
        ),
    ],
)
def test_shows_shape_and_example_when_pattern_rendered_for_text(
    *, pattern: str, shown_prefix: str, shape: str, example: str
) -> None:
    assert branch_shape_text(pattern, shown_prefix=shown_prefix) == shape
    assert branch_example(pattern, shown_prefix=shown_prefix, team="DEM") == example


def test_shows_project_and_repo_branches_when_hub_sets_conventions() -> None:
    shown = shown_branches(HubConfig.model_validate(a_conventions_document()))

    assert shown is not None
    assert shown.shown_prefix == "jdoe/"
    assert shown.project == ShownBranch("jdoe/{ISSUE}-{slug}", "jdoe/DEM-7-collector")
    # Each repo's effective branch, in hub.json order: demo-web inherits the project's.
    assert shown.repos == {
        "demo-api": ShownBranch("feature/{issue_lower}/{slug}", "feature/dem-7/collector"),
        "demo-web": ShownBranch("jdoe/{ISSUE}-{slug}", "jdoe/DEM-7-collector"),
    }
    assert list(shown.repos) == ["demo-api", "demo-web"]
    assert shown.texts() == {
        "jdoe/{ISSUE}-{slug}",
        "jdoe/DEM-7-collector",
        "feature/{issue_lower}/{slug}",
        "feature/dem-7/collector",
    }


def test_shows_default_branch_when_repo_conventions_empty() -> None:
    # An empty object still sets conventions: the texts show the default shape.
    document: dict[str, Any] = a_hub_document()
    document["repos"][0]["conventions"] = {}

    shown = shown_branches(HubConfig.model_validate(document))

    assert shown is not None
    assert shown.project == ShownBranch("jdoe/{issue_lower}-{slug}", "jdoe/dem-7-collector")


def test_shows_no_branch_when_hub_sets_no_conventions() -> None:
    assert shown_branches(HubConfig.model_validate(a_hub_document())) is None
