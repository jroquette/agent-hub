from typing import Any

import pytest

from agent_hub.core.hub_config.effective_environments import (
    effective_environments,
    local_environment_problems,
)
from agent_hub.core.hub_config.local_config import LocalConfig, check_local_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_local_environments_document,
    an_environments_document,
)


def hub_config() -> HubConfig:
    return HubConfig.model_validate(an_environments_document())


def local_config(document: dict[str, Any]) -> LocalConfig:
    local = check_local_document(document)
    assert isinstance(local, LocalConfig), local
    return local


def local_problems(document: dict[str, Any]) -> list[tuple[str, str]]:
    problems = local_environment_problems(hub_config(), local_config(document))
    return [(problem.path, problem.message) for problem in problems]


def test_finds_no_problem_when_local_declares_own_environments() -> None:
    assert local_problems(a_local_environments_document()) == []


def with_change(path: tuple[str | int, ...], value: object) -> dict[str, Any]:
    document = a_local_environments_document()
    parent: Any = document
    for segment in path[:-1]:
        parent = parent[segment]
    parent[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value", "where", "message"),
    [
        pytest.param(
            ("environments", "live"),
            {"production": True},
            "environments.live.production",
            "hub.json declares live; hub.local.json may only tighten its access",
            id="redeclare_live",
        ),
        pytest.param(
            ("environments", "live"),
            {"description": "mine"},
            "environments.live.description",
            "hub.json declares live; hub.local.json may only tighten its access",
            id="describe_live",
        ),
        pytest.param(
            ("repos", 0, "services", "api", "endpoints", "staging"),
            {"url": "https://api.jane.example.com"},
            "repos[0].services.api.endpoints.staging",
            "staging is declared in hub.json; a local endpoint names a local environment",
            id="endpoint_staging",
        ),
        pytest.param(
            ("repos", 0, "services", "api", "endpoints", "qa"),
            {"url": "https://api.qa.example.com"},
            "repos[0].services.api.endpoints.qa",
            'environment "qa" is not in environments',
            id="endpoint_undeclared",
        ),
        pytest.param(
            ("repos", 0, "dir"),
            "other",
            "repos[0].dir",
            'repo dir "other" is not in hub.json\'s repos',
            id="dir_other",
        ),
        pytest.param(
            ("repos", 0, "services", "api", "kind"),
            "lambda",
            "repos[0].services.api.kind",
            "hub.json declares api; hub.local.json may only add its endpoints",
            id="committed_service_kind",
        ),
        pytest.param(
            ("environments", "jane-cloud"),
            {"credentials": {"aws_profile": "jane-sandbox"}},
            "environments.jane-cloud.access",
            "a new environment needs an access: read, write or ask",
            id="new_without_access",
        ),
        pytest.param(
            ("environments", "Live"),
            {"access": "read"},
            "environments.Live",
            'environment name "Live" is already used by "live" in hub.json, ignoring case',
            id="name_case",
        ),
        pytest.param(
            ("environments", "JANE-CLOUD"),
            {"access": "read"},
            "environments.JANE-CLOUD",
            'environment name "JANE-CLOUD" is already used by "jane-cloud" in hub.local.json,'
            " ignoring case",
            id="local_name_case",
        ),
    ],
)
def test_rejects_local_environments_when_conflict_given(
    path: tuple[str | int, ...], value: object, *, where: str, message: str
) -> None:
    assert local_problems(with_change(path, value)) == [(where, message)]


@pytest.mark.parametrize(
    ("name", "access", "committed"),
    [("staging", "write", "ask"), ("staging", "ask", "ask"), ("live", "write", "read")],
    ids=["looser", "equal", "live_looser"],
)
def test_rejects_tighten_when_access_looser_or_equal(
    name: str, access: str, committed: str
) -> None:
    document = with_change(("environments", name), {"access": access})

    assert local_problems(document) == [
        (f"environments.{name}.access", f"may only tighten hub.json's {committed}")
    ]


@pytest.mark.parametrize(
    ("name", "access"), [("staging", "read"), ("local", "ask"), ("local", "read")]
)
def test_accepts_tighten_when_access_stricter(name: str, access: str) -> None:
    assert local_problems(with_change(("environments", name), {"access": access})) == []


def environment_rows(local: dict[str, Any]) -> list[tuple[str, str, bool, str]]:
    effective = effective_environments(hub_config(), local_config(local))
    return [
        (environment.name, environment.access, environment.production, environment.source)
        for environment in effective.environments
    ]


def test_merges_local_environments_when_local_declares_them() -> None:
    effective = effective_environments(hub_config(), local_config(a_local_environments_document()))

    assert environment_rows(a_local_environments_document()) == [
        ("local", "write", False, "hub.json"),
        ("staging", "ask", False, "hub.json"),
        ("live", "read", True, "hub.json"),
        ("jane-cloud", "write", False, "hub.local.json"),
    ]
    jane = effective.environments[-1]
    assert jane.credentials is not None
    assert jane.credentials.aws_profile == "jane-sandbox"
    assert [(service.repo, service.name) for service in effective.services] == [
        ("demo-api", "api"),
        ("demo-api", "orders"),
    ]
    api = effective.services[0]
    assert api.kind == "api"
    assert [(row.environment, row.endpoint.url, row.source) for row in api.endpoints] == [
        ("local", "http://localhost:8000", "hub.json"),
        ("staging", "https://api.staging.example.com", "hub.json"),
        ("live", "https://api.example.com", "hub.json"),
        ("jane-cloud", "https://api.jane.example.com", "hub.local.json"),
    ]
    assert [(entry.value, entry.layer) for entry in effective.blocked_words] == [
        ("prod", "hub.json"),
        ("production", "hub.json"),
        ("demo-live", "hub.local.json"),
    ]
    assert [entry.value for entry in effective.blocked_files] == [
        "config/*.json",
        "serverless.yml",
        "deploy/*.tfvars",
    ]


def test_tightens_access_when_local_sets_stricter() -> None:
    local = a_local_environments_document()
    local["environments"]["staging"] = {"access": "read"}

    assert environment_rows(local)[1] == ("staging", "read", False, "hub.local.json")


def test_keeps_hub_environments_when_local_file_absent() -> None:
    assert environment_rows({}) == [
        ("local", "write", False, "hub.json"),
        ("staging", "ask", False, "hub.json"),
        ("live", "read", True, "hub.json"),
    ]


def test_adds_local_service_when_local_names_new_one() -> None:
    local = a_local_environments_document()
    local["repos"][0]["services"]["queue"] = {
        "kind": "sqs",
        "endpoints": {"jane-cloud": {"resource": "jane-queue"}},
    }

    services = effective_environments(hub_config(), local_config(local)).services

    assert [(service.name, service.kind) for service in services] == [
        ("api", "api"),
        ("orders", "dynamodb"),
        ("queue", "sqs"),
    ]
    assert [(row.environment, row.source) for row in services[2].endpoints] == [
        ("jane-cloud", "hub.local.json")
    ]
