import posixpath
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

REQUIRED_KEYS: list[tuple[str | int, ...]] = [
    ("schema_version",),
    ("platform",),
    ("platform", "version"),
    ("project",),
    ("project", "name"),
    ("project", "hub_repo"),
    ("project", "branch_prefix"),
    ("project", "author_name"),
    ("project", "author_email"),
    ("tracker",),
    ("tracker", "kind"),
    ("tracker", "team"),
    ("repos",),
    ("repos", 0, "dir"),
    ("repos", 0, "github"),
    ("repos", 0, "check_fast"),
    ("repos", 0, "check"),
]

GUARD_PATH_LISTS = ["ask_before_edit", "deny_paths"]


def error_locs(document: dict[str, Any]) -> list[tuple[str | int, ...]]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    return [error["loc"] for error in caught.value.errors()]


def error_types(document: dict[str, Any]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    return [(error["loc"], error["type"]) for error in caught.value.errors()]


def with_value(path: tuple[str | int, ...], value: object) -> dict[str, Any]:
    document = a_hub_document()
    parent: Any = document
    for segment in path[:-1]:
        parent = parent[segment]
    parent[path[-1]] = value
    return document


def test_accepts_document_when_design_example_given() -> None:
    config = HubConfig.model_validate(a_hub_document())

    assert config.model_dump(mode="json", exclude_none=True, exclude_defaults=True) == (
        a_hub_document()
    )


def test_rejects_assignment_when_model_frozen() -> None:
    config = HubConfig.model_validate(a_hub_document())

    with pytest.raises(ValidationError):
        config.schema_version = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        config.project.name = "other"  # type: ignore[misc]


def test_applies_defaults_when_optional_fields_absent() -> None:
    document = a_hub_document()
    del document["$schema"]
    del document["guard"]

    config = HubConfig.model_validate(document)

    assert config.schema_uri is None
    assert config.project.default_branch == "main"
    assert config.tracker.ready_label == "agent-ready"
    assert config.tracker.failed_label == "agent-failed"
    assert config.repos[0].role == "app"
    assert config.guard.ask_before_edit == ()
    assert config.guard.deny_hosts == ()
    assert config.guard.deny_paths == ()


@pytest.mark.parametrize("path", REQUIRED_KEYS, ids=lambda path: ".".join(map(str, path)))
def test_rejects_document_when_required_key_missing(path: tuple[str | int, ...]) -> None:
    document = a_hub_document()
    parent: Any = document
    for segment in path[:-1]:
        parent = parent[segment]
    del parent[path[-1]]

    assert error_locs(document) == [path]


@pytest.mark.parametrize("repo_dir", ["agent-hub", "tradeSentinel", "loki-trader-ui"])
def test_accepts_repo_dir_when_single_safe_segment(repo_dir: str) -> None:
    document = with_value(("repos", 0, "dir"), repo_dir)
    document["guard"] = {}

    assert HubConfig.model_validate(document).repos[0].dir == repo_dir


@pytest.mark.parametrize(
    "repo_dir", [".", "..", "a/b", "a b", "@hub", "", "-x", ".git", "a..b", "x.", "a\\b"]
)
def test_rejects_repo_dir_when_not_single_safe_segment(repo_dir: str) -> None:
    document = with_value(("repos", 0, "dir"), repo_dir)
    document["guard"] = {}

    assert error_locs(document) == [("repos", 0, "dir")]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tracker", "team"), "AGH"),
        (("tracker", "team"), "LOK"),
        (("project", "branch_prefix"), "roquettejh/"),
        (("project", "hub_repo"), "jroquette/agent-hub-hub"),
        (("project", "hub_repo"), "LokiTrader/loki-trader-hub"),
        (("repos", 0, "github"), "jroquette/agent-hub-hub"),
        (("repos", 0, "github"), "LokiTrader/loki-trader-hub"),
        (("project", "default_branch"), "main"),
        (("guard", "deny_paths"), ["_archive", "@hub/brain"]),
    ],
)
def test_accepts_values_when_existing_hubs_use_them(
    path: tuple[str | int, ...], value: object
) -> None:
    HubConfig.model_validate(with_value(path, value))


@pytest.mark.parametrize(
    "name", ["Demo", "demo_hub", "-demo", "demo-", "demo--hub", "demo hub", ""]
)
def test_rejects_project_name_when_not_kebab_case(name: str) -> None:
    assert error_locs(with_value(("project", "name"), name)) == [("project", "name")]


@pytest.mark.parametrize("kind", ["jira", "Linear", ""])
def test_rejects_tracker_kind_when_not_linear(kind: str) -> None:
    assert error_locs(with_value(("tracker", "kind"), kind)) == [("tracker", "kind")]


@pytest.mark.parametrize("prefix", ["jdoe", "jdoe/x", "/", "jdoe//", "../", ".git/", "-x/"])
def test_rejects_branch_prefix_when_no_trailing_slash(prefix: str) -> None:
    locs = error_locs(with_value(("project", "branch_prefix"), prefix))

    assert locs == [("project", "branch_prefix")]


@pytest.mark.parametrize(
    "email", ["a@b@c", "a b@c", "jane.example.com", "@example.com", "a$(x)@c", 'a"b@c']
)
def test_rejects_author_email_when_not_one_at_without_space(email: str) -> None:
    assert error_locs(with_value(("project", "author_email"), email)) == [
        ("project", "author_email")
    ]


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "0.2.0\n", "\uff10.\uff12.\uff10", "1.2.3.4"])
def test_rejects_platform_version_when_not_three_ascii_numbers(version: str) -> None:
    assert error_locs(with_value(("platform", "version"), version)) == [("platform", "version")]


@pytest.mark.parametrize("schema_version", [2, True, 1.0, "1", 0])
def test_rejects_schema_version_when_not_integer_one(schema_version: object) -> None:
    assert error_locs(with_value(("schema_version",), schema_version)) == [("schema_version",)]


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_reports_integer_type_when_schema_version_not_integer(schema_version: object) -> None:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(with_value(("schema_version",), schema_version))

    [error] = caught.value.errors()
    assert (error["type"], error["msg"]) == ("int_type", "must be an integer")


@pytest.mark.parametrize("repo", ["../x", "-o/x", "a/.git", "a/b/c", "a$b/c", "a/b\n"])
def test_rejects_github_repo_when_not_two_safe_segments(repo: str) -> None:
    document = with_value(("project", "hub_repo"), repo)
    document["repos"][0]["github"] = repo

    assert error_locs(document) == [("project", "hub_repo"), ("repos", 0, "github")]


@pytest.mark.parametrize(
    "branch", ["main\n", "main ", "--force", "-rf", "../..", "main/", "", "a//b", "feat/-x"]
)
def test_rejects_default_branch_when_not_safe_segments(branch: str) -> None:
    locs = error_locs(with_value(("project", "default_branch"), branch))

    assert locs == [("project", "default_branch")]


@pytest.mark.parametrize("host", ["api.example.com", "localhost", "a-b.example.com", "x1"])
def test_accepts_deny_host_when_dns_name(host: str) -> None:
    document = with_value(("guard", "deny_hosts"), [host])

    assert HubConfig.model_validate(document).guard.deny_hosts == (host,)


@pytest.mark.parametrize(
    "host",
    ["evil.com\n", "a b", "-x.com", "x-.com", "evil..com", "", ".evil.com", "https://evil.com"],
)
def test_rejects_deny_host_when_not_dns_name(host: str) -> None:
    assert error_locs(with_value(("guard", "deny_hosts"), [host])) == [("guard", "deny_hosts", 0)]


@pytest.mark.parametrize("guard_list", GUARD_PATH_LISTS)
@pytest.mark.parametrize(
    "path",
    [
        "demo-api/a\x00b",
        "demo-api/a\nb",
        "demo-api/a\tb",
        "demo-api/a\u200bb",
        "demo-api\u2215docs",
        "demo-api/a b",
        "demo-api/a\x7fb",
    ],
)
def test_rejects_guard_path_when_not_printable_ascii(guard_list: str, path: str) -> None:
    document = with_value(("guard", guard_list), [path])

    assert error_types(document) == [(("guard", guard_list, 0), "string_pattern_mismatch")]


@pytest.mark.parametrize(
    "path",
    [
        ("project", "author_name"),
        ("tracker", "ready_label"),
        ("tracker", "failed_label"),
        ("repos", 0, "role"),
        ("repos", 0, "check_fast"),
        ("repos", 0, "check"),
    ],
    ids=lambda path: ".".join(map(str, path)),
)
@pytest.mark.parametrize("value", ["x\ny", "\x00", "x\x7f", "x\ty", "make check\r"])
def test_rejects_free_string_when_control_character(
    path: tuple[str | int, ...], value: str
) -> None:
    assert error_locs(with_value(path, value)) == [path]


def test_reports_other_errors_when_object_has_null_value() -> None:
    document = with_value(("project", "name"), None)
    document["project"]["hub_repo"] = "bad"

    assert sorted(error_types(document)) == [
        (("project", "hub_repo"), "string_pattern_mismatch"),
        (("project", "name"), "null_not_allowed"),
    ]


def test_reports_nested_locations_when_list_item_has_null_value() -> None:
    document = with_value(("repos", 0, "role"), None)
    document["repos"][0]["dir"] = "a b"
    document["guard"] = {}

    assert error_types(document) == [
        (("repos", 0, "role"), "null_not_allowed"),
        (("repos", 0, "dir"), "string_pattern_mismatch"),
    ]


def test_keeps_nested_error_when_top_level_key_is_null() -> None:
    document = a_hub_document()
    document["repos"].append(document["repos"][0] | {"github": "acme/other"})
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    [duplicate] = caught.value.errors()
    document["guard"] = None

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [
        (("guard",), "null_not_allowed"),
        (("repos", 1, "dir"), "duplicate_repo_dir"),
    ]
    assert caught.value.errors()[1] == duplicate


def test_rejects_schema_key_when_control_character() -> None:
    assert error_locs(with_value(("$schema",), "./hub.schema.json\n")) == [("$schema",)]


def test_rejects_repos_when_dir_differs_only_in_case() -> None:
    document = a_hub_document()
    document["repos"].append(document["repos"][0] | {"dir": "Demo-api", "github": "acme/b"})
    document["guard"] = {}

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert error["loc"] == ("repos", 1, "dir")
    assert '"Demo-api"' in error["msg"]


def test_rejects_repos_when_dir_duplicated() -> None:
    document = a_hub_document()
    document["repos"].append(document["repos"][0] | {"github": "acme/other"})

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert error["loc"] == ("repos", 1, "dir")
    assert '"demo-api"' in error["msg"]


def test_rejects_repos_when_empty() -> None:
    document = with_value(("repos",), [])
    document["guard"] = {}

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert (error["loc"], error["type"], error["msg"]) == (
        ("repos",),
        "empty_list",
        "must hold at least one item",
    )


def test_accepts_guard_paths_when_rooted_at_repo_or_hub() -> None:
    paths = ["agent-hub/docs/adr", "@hub/brain"]
    document = with_value(("repos", 0, "dir"), "agent-hub")
    document["guard"] = {"ask_before_edit": paths, "deny_paths": paths}

    guard = HubConfig.model_validate(document).guard

    assert guard.ask_before_edit == tuple(paths)
    assert guard.deny_paths == tuple(paths)


def test_rejects_ask_before_edit_when_root_unknown() -> None:
    document = with_value(("guard", "ask_before_edit"), ["demo-api/docs", "_archive/old"])

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert error["loc"] == ("guard", "ask_before_edit", 1)
    assert '"_archive"' in error["msg"]


def test_accepts_deny_path_when_rooted_at_other_workspace_dir() -> None:
    document = with_value(("guard", "deny_paths"), ["_archive"])

    assert HubConfig.model_validate(document).guard.deny_paths == ("_archive",)


@pytest.mark.parametrize("guard_list", GUARD_PATH_LISTS)
@pytest.mark.parametrize(
    "path",
    [
        "/abs",
        "/demo-api/docs",
        "demo-api/./b",
        "demo-api/../b",
        "demo-api\\b",
        "demo-api//docs",
        "demo-api/docs/",
        "demo-api/.",
        "",
    ],
)
def test_rejects_guard_path_when_not_normalized_relative(guard_list: str, path: str) -> None:
    # A backslash is not a separator to posixpath, so normpath cannot see it; the model can.
    assert posixpath.isabs(path) or "\\" in path or posixpath.normpath(path) != path
    document = with_value(("guard", guard_list), [path])

    assert error_types(document) == [(("guard", guard_list, 0), "string_pattern_mismatch")]


def test_accepts_hub_document_when_migrated_with_version_keys() -> None:
    document = {
        "_comment": "Project values for the demo hub; read it instead of assuming names.",
        "schema_version": 1,
        "platform": {"version": "0.2.0"},
        "project": {
            "name": "demo-hub",
            "hub_repo": "acme/demo-hub",
            "branch_prefix": "jdoe/",
            "default_branch": "main",
            "author_name": "Jane Doe",
            "author_email": "jane@example.com",
        },
        "tracker": {
            "kind": "linear",
            "team": "DEM",
            "ready_label": "agent-ready",
            "failed_label": "agent-failed",
        },
        "repos": [
            {
                "dir": "demo-api",
                "github": "acme/demo-api",
                "role": "app",
                "check_fast": "make check-fast",
                "check": "make check",
            }
        ],
        "guard": {
            "ask_before_edit": [
                "demo-api/docs/adr",
                "demo-api/packages/storage/migrations/versions",
            ],
            "deny_hosts": [],
        },
    }

    config = HubConfig.model_validate(document)

    assert config.guard.ask_before_edit[1] == "demo-api/packages/storage/migrations/versions"
