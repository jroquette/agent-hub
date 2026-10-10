from typing import Any

import pytest
from pydantic import BaseModel

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.local_config import (
    LocalConfig,
    LocalProject,
    LocalTracker,
    check_local_document,
)
from agent_hub.core.hub_config.model import Project, Tracker
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import CUSTOM_REPOSITORY, SECRET_PARTS

RUNNING = "0.3.1"
HUB_ONLY_MESSAGE = (
    "set only in hub.json; hub.local.json holds project.branch_prefix, author_name,"
    " author_email and tracker.transport"
)
EXTRA_MESSAGE = "Extra inputs are not permitted"
ROOT_MESSAGE = "must be a JSON object"
# The schema keywords that carry a value's rule; titles and defaults differ by design.
RULE_KEYWORDS = ("type", "pattern", "enum", "minLength")


def problems_of(document: object) -> tuple[ConfigProblem, ...]:
    result = check_local_document(document)
    assert isinstance(result, tuple)
    return result


def hub_problem_at(path: str, value: object) -> ConfigProblem:
    section, key = path.split(".")
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    document[section][key] = value
    result = check_hub_document(document, running_version=RUNNING)
    assert isinstance(result, tuple)
    (problem,) = result
    return problem


def local_document_at(path: str, value: object) -> dict[str, Any]:
    section, key = path.split(".")
    return {section: {key: value}}


def rule_of(model: type[BaseModel], key: str) -> dict[str, Any]:
    schema = model.model_json_schema()["properties"][key]
    return {keyword: schema[keyword] for keyword in RULE_KEYWORDS if keyword in schema}


def test_accepts_local_keys_when_document_valid() -> None:
    document = {
        "_note": "per developer",
        "project": {
            "_note": "mine",
            "branch_prefix": "me/",
            "author_name": "Jane Roe",
            "author_email": "jane@example.com",
        },
        "tracker": {"_note": "mine", "transport": "mcp"},
    }

    assert check_local_document(document) == LocalConfig(
        project=LocalProject(
            branch_prefix="me/", author_name="Jane Roe", author_email="jane@example.com"
        ),
        tracker=LocalTracker(transport="mcp"),
    )


def test_overrides_nothing_when_document_empty() -> None:
    config = check_local_document({})

    assert isinstance(config, LocalConfig)
    assert config.project.branch_prefix is None
    assert config.project.author_name is None
    assert config.project.author_email is None
    assert config.tracker.transport is None


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"project": {"name": "x"}}, ConfigProblem("project.name", HUB_ONLY_MESSAGE)),
        (
            {"project": {"default_branch": "x"}},
            ConfigProblem("project.default_branch", HUB_ONLY_MESSAGE),
        ),
        (
            {"project": {"conventions": {}}},
            ConfigProblem("project.conventions", HUB_ONLY_MESSAGE),
        ),
        ({"guard": {}}, ConfigProblem("guard", HUB_ONLY_MESSAGE)),
        (
            {"guard": {"infra": {"allow": ["--profile[= ]other\\b"]}}},
            ConfigProblem("guard", HUB_ONLY_MESSAGE),
        ),
        ({"repos": []}, ConfigProblem("repos", HUB_ONLY_MESSAGE)),
        ({"tracker": {"team": "X"}}, ConfigProblem("tracker.team", HUB_ONLY_MESSAGE)),
        ({"tracker": {"teams": ["X"]}}, ConfigProblem("tracker.teams", HUB_ONLY_MESSAGE)),
        ({"tracker": {"kind": "linear"}}, ConfigProblem("tracker.kind", HUB_ONLY_MESSAGE)),
        ({"$schema": "x"}, ConfigProblem("$schema", HUB_ONLY_MESSAGE)),
        (
            {"platform": {"repository": CUSTOM_REPOSITORY}},
            ConfigProblem("platform", HUB_ONLY_MESSAGE),
        ),
        ({"colour": 1}, ConfigProblem("colour", EXTRA_MESSAGE)),
    ],
    ids=[
        "project-name",
        "project-default-branch",
        "project-conventions",
        "guard",
        "guard-infra",
        "repos",
        "tracker-team",
        "tracker-teams",
        "tracker-kind",
        "schema-uri",
        "platform-repository",
        "unknown",
    ],
)
def test_rejects_key_when_not_local(document: dict[str, Any], expected: ConfigProblem) -> None:
    assert problems_of(document) == (expected,)


def test_refuses_tracker_states_when_local_file_sets_it() -> None:
    document = {"tracker": {"states": {"started": "Doing"}}}

    assert problems_of(document) == (ConfigProblem("tracker.states", HUB_ONLY_MESSAGE),)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("project.branch_prefix", "-x/"),
        ("tracker.transport", "ftp"),
        ("project.author_email", "x"),
        ("project.author_name", ""),
        ("project.author_name", "a\u0007"),
        ("project.author_name", None),
    ],
    ids=["prefix", "transport", "email", "empty-name", "control-name", "null"],
)
def test_rejects_value_when_hub_pattern_fails(path: str, value: object) -> None:
    (problem,) = problems_of(local_document_at(path, value))

    assert problem == ConfigProblem(path, hub_problem_at(path, value).message)


@pytest.mark.parametrize("document", [[], "x", 7], ids=["list", "string", "number"])
def test_reports_root_problem_when_document_not_object(document: object) -> None:
    assert problems_of(document) == (ConfigProblem("$", ROOT_MESSAGE),)


@pytest.mark.parametrize(
    ("local_model", "hub_model", "key"),
    [
        (LocalProject, Project, "branch_prefix"),
        (LocalProject, Project, "author_name"),
        (LocalProject, Project, "author_email"),
        (LocalTracker, Tracker, "transport"),
    ],
    ids=["branch-prefix", "author-name", "author-email", "transport"],
)
def test_shares_hub_patterns_when_schemas_compared(
    local_model: type[BaseModel], hub_model: type[BaseModel], key: str
) -> None:
    rule = rule_of(local_model, key)

    assert rule.keys() & {"pattern", "enum"}
    assert rule == rule_of(hub_model, key)


# AGH-94: hub.local.json's objects, like hub.json's, never repeat a value of another JSON type.
@pytest.mark.parametrize("key", ["project", "tracker"])
@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (SECRET_PARTS[1], SECRET_PARTS[1]),
        (31337, "31337"),
        ([SECRET_PARTS[1]], SECRET_PARTS[1]),
        (True, "true"),
    ],
    ids=["string", "number", "array", "boolean"],
)
def test_never_echoes_value_when_local_object_holds_other_type(
    key: str, value: object, shown: str
) -> None:
    problems = problems_of({key: value})

    assert problems
    assert not [problem for problem in problems if shown in problem.message]
