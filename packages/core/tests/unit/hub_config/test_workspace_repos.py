from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.workspace_repos import workspace_repos
from agent_hub.core.testing.builders import a_hub_document, a_second_repo


def _one_repo() -> dict[str, Any]:
    return a_hub_document()


def _two_repo() -> dict[str, Any]:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    return document


def _zeta_first() -> dict[str, Any]:
    document = a_hub_document()
    document["repos"].insert(
        0,
        {"dir": "zeta", "github": "acme/zeta", "check_fast": "make f", "check": "make c"},
    )
    return document


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param(_one_repo(), [("demo-api", "acme/demo-api")], id="one-repo"),
        pytest.param(
            _two_repo(),
            [("demo-api", "acme/demo-api"), ("demo-web", "acme/demo-web")],
            id="two-repo",
        ),
        pytest.param(
            _zeta_first(),
            [("zeta", "acme/zeta"), ("demo-api", "acme/demo-api")],
            id="zeta-first",
        ),
    ],
)
def test_lists_dir_and_github_in_hub_order_when_config_given(
    document: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    repos = workspace_repos(HubConfig.model_validate(document))

    assert [(repo.dir, repo.github) for repo in repos] == expected


def test_refuses_assignment_when_entry_listed() -> None:
    (entry,) = workspace_repos(HubConfig.model_validate(a_hub_document()))

    with pytest.raises(AttributeError):
        entry.dir = "x"  # type: ignore[misc]
