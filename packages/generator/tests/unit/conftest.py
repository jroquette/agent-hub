"""Synthetic hub configs for the generator tests (TESTING.md: builders only, no real hub.json)."""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document


@pytest.fixture
def demo_config() -> HubConfig:
    """The builder's demo project: one repo, modules ``cloud`` and ``bench``."""
    return HubConfig.model_validate(a_hub_document())


@pytest.fixture
def variant_config() -> HubConfig:
    """A second project whose run-time values are sentinels no rendered file may contain.

    No module, two repos, a non-``main`` default branch; ``check_fast``, ``check``,
    ``platform.version`` and ``author_name`` hold values that are never rendered (AC-3.9).
    """
    document = a_hub_document()
    document["platform"]["version"] = "9.8.7"
    document["project"]["default_branch"] = "trunk"
    document["project"]["author_name"] = "Sentinel Author Q7"
    document["repos"] = [
        {
            "dir": repo_dir,
            "github": f"acme/{repo_dir}",
            "check_fast": "make sentinel-fast-q7",
            "check": "make sentinel-full-q7",
        }
        for repo_dir in ("demo-api", "demo-web")
    ]
    document["modules"] = {}
    return HubConfig.model_validate(document)
