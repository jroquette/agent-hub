import json
from typing import Any

import pytest
from pydantic import BaseModel

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE_MAX_BYTES,
    LocalConfig,
    LocalProject,
    LocalTracker,
    check_local_document,
    local_identity_bytes,
)
from agent_hub.core.hub_config.model import Project, Tracker
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.testing import builders
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import CUSTOM_REPOSITORY, SECRET_PARTS

RUNNING = "0.3.1"
HUB_ONLY_MESSAGE = (
    "set only in hub.json (hub.local.json's keys:"
    # The design doc names every local key, so the message does not list them.
    " docs/design/developer-identity.md)"
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
        ({"modules": {}}, ConfigProblem("modules", HUB_ONLY_MESSAGE)),
        (
            {"guard": {"infra": {"allow": ["--profile[= ]other\\b"]}}},
            ConfigProblem("guard.infra", HUB_ONLY_MESSAGE),
        ),
        (
            {"repos": [{"dir": "demo-api", "github": "x/y"}]},
            ConfigProblem("repos[0].github", HUB_ONLY_MESSAGE),
        ),
        ({"tracker": {"team": "X"}}, ConfigProblem("tracker.team", HUB_ONLY_MESSAGE)),
        ({"tracker": {"teams": ["X"]}}, ConfigProblem("tracker.teams", HUB_ONLY_MESSAGE)),
        ({"tracker": {"kind": "linear"}}, ConfigProblem("tracker.kind", HUB_ONLY_MESSAGE)),
        ({"$schema": "x"}, ConfigProblem("$schema", HUB_ONLY_MESSAGE)),
        (
            {"platform": {"repository": CUSTOM_REPOSITORY}},
            ConfigProblem("platform", HUB_ONLY_MESSAGE),
        ),
        ({"models": {"tiers": {"large": "opus"}}}, ConfigProblem("models", HUB_ONLY_MESSAGE)),
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
        "models",
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


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        pytest.param(
            {
                "branch_prefix": "jane/",
                "author_name": "Jane Roe",
                "author_email": "jane@example.com",
            },
            b'{\n  "project": {\n    "branch_prefix": "jane/",\n    "author_name": "Jane Roe",\n'
            b'    "author_email": "jane@example.com"\n  }\n}\n',
            id="all-three",
        ),
        pytest.param(
            {"author_name": "Jane Roe", "author_email": "jane@example.com"},
            b'{\n  "project": {\n    "author_name": "Jane Roe",\n'
            b'    "author_email": "jane@example.com"\n  }\n}\n',
            id="name-and-email",
        ),
        pytest.param(
            {"author_name": "Jos\u00e9 Roe"},
            '{\n  "project": {\n    "author_name": "Jos\u00e9 Roe"\n  }\n}\n'.encode(),
            id="utf8",
        ),
        pytest.param(
            {
                "author_email": "jane@example.com",
                "author_name": "Jane Roe",
                "branch_prefix": "jane/",
            },
            b'{\n  "project": {\n    "branch_prefix": "jane/",\n    "author_name": "Jane Roe",\n'
            b'    "author_email": "jane@example.com"\n  }\n}\n',
            id="reversed",
        ),
    ],
)
def test_writes_identity_bytes_when_keys_proposed(values: dict[str, str], expected: bytes) -> None:
    written = local_identity_bytes(values)

    assert written == expected
    # The bytes read back as the very values proposed: the writer and the reader agree.
    assert check_local_document(json.loads(written)) == LocalConfig(project=LocalProject(**values))


def test_returns_problem_when_no_identity_value_proposed() -> None:
    assert local_identity_bytes({}) == (
        ConfigProblem(
            "project", "holds no identity value: set branch_prefix, author_name or author_email"
        ),
    )


def test_returns_problems_when_proposed_value_invalid() -> None:
    result = local_identity_bytes({"branch_prefix": "-x/", "author_name": "Jane Roe"})

    assert result == (
        ConfigProblem(
            "project.branch_prefix", hub_problem_at("project.branch_prefix", "-x/").message
        ),
    )


def _name_bytes(length: int) -> bytes | tuple[ConfigProblem, ...]:
    """The identity bytes of an ``author_name`` of ``length`` characters, whose file is the
    name plus a fixed frame."""
    one_character = local_identity_bytes({"author_name": "J"})
    assert isinstance(one_character, bytes)
    frame = len(one_character) - 1
    return local_identity_bytes({"author_name": "J" * (length - frame)})


def test_writes_identity_bytes_when_file_size_at_reader_limit() -> None:
    written = _name_bytes(LOCAL_FILE_MAX_BYTES)

    assert isinstance(written, bytes)
    assert len(written) == LOCAL_FILE_MAX_BYTES


def test_returns_problem_when_identity_bytes_exceed_reader_limit() -> None:
    assert _name_bytes(LOCAL_FILE_MAX_BYTES + 1) == (
        ConfigProblem(ROOT_PATH, f"larger than {LOCAL_FILE_MAX_BYTES} bytes once written"),
    )


def test_loads_local_environments_when_declared() -> None:
    config = check_local_document(builders.a_local_environments_document())

    assert isinstance(config, LocalConfig)
    assert config.project.branch_prefix == "jane/"
    jane = config.environments["jane-cloud"]
    assert (jane.access, jane.production) == ("write", None)
    assert jane.credentials is not None
    assert jane.credentials.aws_profile == "jane-sandbox"
    (repo,) = config.repos
    assert repo.dir == "demo-api"
    assert repo.services["api"].endpoints["jane-cloud"].url == "https://api.jane.example.com"


def test_loads_tightened_access_when_local_names_committed_environment() -> None:
    config = check_local_document({"environments": {"staging": {"access": "read"}}})

    assert isinstance(config, LocalConfig)
    assert config.environments["staging"].access == "read"


def test_loads_local_guard_when_blocked_lists_given() -> None:
    document = builders.a_local_environments_document()
    document["guard"]["blocked_words_env"] = ["DEMO_TARGET", "DEMO_*"]

    config = check_local_document(document)

    assert isinstance(config, LocalConfig)
    assert config.guard.blocked_words == ("demo-live",)
    assert config.guard.blocked_words_files == ("deploy/*.tfvars",)
    assert config.guard.blocked_words_env == ("DEMO_TARGET", "DEMO_*")


def test_defaults_local_sections_when_file_sets_identity_only() -> None:
    config = check_local_document({"project": {"branch_prefix": "me/"}})

    assert isinstance(config, LocalConfig)
    assert (config.environments, config.repos) == ({}, ())
    assert config.guard.blocked_words == ()


@pytest.mark.parametrize(
    ("document", "path"),
    [
        ({"guard": {"deny_hosts": ["db.example.com"]}}, "guard.deny_hosts"),
        ({"guard": {"infra": {}}}, "guard.infra"),
        ({"guard": {"ask_before_edit": []}}, "guard.ask_before_edit"),
    ],
    ids=["deny-hosts", "infra", "ask-before-edit"],
)
def test_rejects_local_key_when_hub_only_in_guard(document: dict[str, Any], path: str) -> None:
    (problem,) = problems_of(document)

    assert problem.path == path
    assert problem.message.startswith("set only in hub.json")


@pytest.mark.parametrize(
    ("repo", "path", "message"),
    [
        ({"dir": "demo-api", "github": "x/y"}, "repos[0].github", "set only in hub.json"),
        ({"dir": "demo-api", "check": "make check"}, "repos[0].check", "set only in hub.json"),
        ({"dir": "demo-api", "colour": 1}, "repos[0].colour", EXTRA_MESSAGE),
        ({"services": {}}, "repos[0].dir", "Field required"),
    ],
    ids=["github", "check", "unknown", "no-dir"],
)
def test_rejects_local_repo_key_when_not_dir_or_services(
    repo: dict[str, Any], path: str, message: str
) -> None:
    (problem,) = problems_of({"repos": [repo]})

    assert problem.path == path
    assert problem.message.startswith(message)


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"guard": {"blocked_words": ["x"]}}, "guard.blocked_words[0]"),
        ({"guard": {"blocked_words_env": ["lower"]}}, "guard.blocked_words_env[0]"),
        ({"environments": {"jane-cloud": {"access": "admin"}}}, "environments.jane-cloud.access"),
    ],
    ids=["word", "env-name", "access"],
)
def test_rejects_local_value_when_hub_shape_fails(change: dict[str, Any], path: str) -> None:
    (problem,) = problems_of({**builders.a_local_environments_document(), **change})

    assert problem.path == path
