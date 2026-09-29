from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.placeholders import PLATFORM_REPOSITORY, substitution_mapping

# AC-3.9: the Rendered values of project-config.md, the platform repository (erratum E3) and the
# derived module includes (erratum E2). author_name, check_fast, check and platform.version are
# read at run time or quoted per format, never placeholders.
RENDERED_KEYS = {
    "project_name",
    "project_hub_repo",
    "project_branch_prefix",
    "project_default_branch",
    "project_author_email",
    "tracker_team",
    "repo_dirs",
    "repo_githubs",
    "guard_deny_hosts",
    "platform_repository",
    "module_includes",
}


def config_with(**sections: Any) -> HubConfig:
    document = a_hub_document()
    document.update(sections)
    return HubConfig.model_validate(document)


def test_lists_rendered_values_when_mapping_built(
    demo_config: HubConfig, variant_config: HubConfig
) -> None:
    for config in (demo_config, variant_config):
        assert set(substitution_mapping(config)) == RENDERED_KEYS


def test_takes_values_from_model_when_demo_mapped(demo_config: HubConfig) -> None:
    mapping = substitution_mapping(demo_config)

    # default_branch is absent from the document: the model's default proves the source.
    assert mapping == {
        "project_name": "demo",
        "project_hub_repo": "acme/demo-hub",
        "project_branch_prefix": "jdoe/",
        "project_default_branch": "main",
        "project_author_email": "jane@example.com",
        "tracker_team": "DEM",
        "repo_dirs": "demo-api",
        "repo_githubs": "acme/demo-api",
        "guard_deny_hosts": "",
        "platform_repository": PLATFORM_REPOSITORY,
        "module_includes": "include mk/bench.mk\ninclude mk/cloud.mk\n",
    }


def test_joins_repos_in_config_order_when_variant_mapped(variant_config: HubConfig) -> None:
    mapping = substitution_mapping(variant_config)

    assert mapping["repo_dirs"] == "demo-api, demo-web"
    assert mapping["repo_githubs"] == "acme/demo-api, acme/demo-web"
    assert mapping["project_default_branch"] == "trunk"


def test_joins_repos_in_config_order_when_order_reversed() -> None:
    document = a_hub_document()
    document["repos"].insert(
        0,
        {"dir": "zeta", "github": "acme/zeta", "check_fast": "make f", "check": "make c"},
    )

    mapping = substitution_mapping(HubConfig.model_validate(document))

    assert mapping["repo_dirs"] == "zeta, demo-api"
    assert mapping["repo_githubs"] == "acme/zeta, acme/demo-api"


@pytest.mark.parametrize(
    ("hosts", "expected"),
    [
        (["a.example.com", "b.example.com"], "a.example.com, b.example.com"),
        ([], ""),
    ],
)
def test_joins_deny_hosts_when_hosts_listed(hosts: list[str], expected: str) -> None:
    config = config_with(guard={"deny_hosts": hosts})

    assert substitution_mapping(config)["guard_deny_hosts"] == expected


@pytest.mark.parametrize(
    ("modules", "expected"),
    [
        ({"cloud": {}, "bench": {}}, "include mk/bench.mk\ninclude mk/cloud.mk\n"),
        ({"contract-sync": {}}, "include mk/contract-sync.mk\n"),
        ({}, ""),
    ],
)
def test_lists_sorted_includes_when_modules_selected(
    modules: dict[str, dict[str, object]], expected: str
) -> None:
    config = config_with(modules=modules)

    assert substitution_mapping(config)["module_includes"] == expected


def test_matches_core_release_command_when_source_formatted() -> None:
    expected = f"uvx --from {PLATFORM_REPOSITORY}@v1.2.3#subdirectory=packages/agent-hub hub"

    assert PINNED_RELEASE_COMMAND.format(version="1.2.3") == expected


def test_renders_no_run_time_value_when_variant_mapped(variant_config: HubConfig) -> None:
    values = substitution_mapping(variant_config).values()

    for never_rendered in ("sentinel-fast-q7", "sentinel-full-q7", "9.8.7", "Sentinel Author Q7"):
        assert not any(never_rendered in value for value in values)
