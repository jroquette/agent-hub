import itertools
import json
import posixpath
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.core.hub_config.model import (
    MODULE_IDS,
    BranchName,
    BranchPrefix,
    GitHubRepo,
    HubConfig,
    RepoDir,
)
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

REQUIRED_KEYS: list[tuple[str | int, ...]] = [
    ("schema_version",),
    ("platform",),
    ("platform", "version"),
    ("project",),
    ("project", "name"),
    ("project", "hub_repo"),
    ("tracker",),
    ("tracker", "kind"),
    ("tracker", "team"),
    ("repos",),
    ("repos", 0, "dir"),
    ("repos", 0, "github"),
    ("repos", 0, "check_fast"),
    ("repos", 0, "check"),
]

# Set per developer (hub.local.json, else hub.json, else git config): optional in hub.json.
IDENTITY_KEYS = ["branch_prefix", "author_name", "author_email"]

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
    return with_path_value(a_hub_document(), path, value)


def with_path_value(
    document: dict[str, Any], path: tuple[str | int, ...], value: object
) -> dict[str, Any]:
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
    del document["modules"]

    config = HubConfig.model_validate(document)

    assert config.schema_uri is None
    assert config.project.default_branch == "main"
    assert config.tracker.ready_label == "agent-ready"
    assert config.tracker.failed_label == "agent-failed"
    assert config.repos[0].role == "app"
    assert config.guard.ask_before_edit == ()
    assert config.guard.deny_hosts == ()
    assert config.guard.deny_paths == ()
    dump = config.model_dump(mode="json", exclude_none=True)
    assert dump["modules"] == {}
    assert dump["doctor"] == {"rules": {}}


def schema_defaults(node: object) -> list[object]:
    if isinstance(node, list):
        return [default for item in node for default in schema_defaults(item)]
    if not isinstance(node, dict):
        return []
    own = [node["default"]] if "default" in node else []
    return own + [default for value in node.values() for default in schema_defaults(value)]


def holds_null(value: object) -> bool:
    if isinstance(value, dict):
        return any(map(holds_null, value.values()))
    if isinstance(value, list):
        return any(map(holds_null, value))
    return value is None


def test_exports_no_null_default_when_schema_generated() -> None:
    defaults = schema_defaults(HubConfig.model_json_schema())

    assert defaults
    assert [default for default in defaults if holds_null(default)] == []


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


# ``_`` left the segment separator class: it was also in the segment class, so
# Python's ``re`` (the hooks' reader) backtracked exponentially on a long run of ``_``.
OLD_SEGMENT = r"[A-Za-z0-9_]+(?:[._-][A-Za-z0-9_]+)*"
OLD_SEGMENT_PATTERNS: list[tuple[object, str]] = [
    (RepoDir, rf"{OLD_SEGMENT}"),
    (GitHubRepo, rf"{OLD_SEGMENT}/{OLD_SEGMENT}"),
    (BranchPrefix, rf"{OLD_SEGMENT}/"),
    (BranchName, rf"{OLD_SEGMENT}(?:/{OLD_SEGMENT})*"),
]


def strings_up_to(length: int, alphabet: str) -> list[str]:
    return [
        "".join(characters)
        for size in range(length + 1)
        for characters in itertools.product(alphabet, repeat=size)
    ]


def is_valid(adapter: TypeAdapter[str], value: str) -> bool:
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    ("value_type", "old_pattern"),
    OLD_SEGMENT_PATTERNS,
    ids=["repo-dir", "github-repo", "branch-prefix", "branch-name"],
)
def test_accepts_same_values_when_segment_separator_drops_underscore(
    value_type: object, old_pattern: str
) -> None:
    adapter: TypeAdapter[str] = TypeAdapter(value_type)
    old = re.compile(old_pattern)

    differing = [
        value
        for value in strings_up_to(6, "a_.-/ ")
        if is_valid(adapter, value) != bool(old.fullmatch(value))
    ]

    assert differing == []


@pytest.mark.parametrize(
    "name", ["Demo", "demo_hub", "-demo", "demo-", "demo--hub", "demo hub", ""]
)
def test_rejects_project_name_when_not_kebab_case(name: str) -> None:
    assert error_locs(with_value(("project", "name"), name)) == [("project", "name")]


@pytest.mark.parametrize("kind", ["jira", "Linear", ""])
def test_rejects_tracker_kind_when_not_linear(kind: str) -> None:
    assert error_locs(with_value(("tracker", "kind"), kind)) == [("tracker", "kind")]


def test_defaults_transport_to_api_when_absent() -> None:
    document = a_hub_document()
    assert "transport" not in document["tracker"]

    config = HubConfig.model_validate(document)

    assert config.tracker.transport == "api"
    # The key is optional with a default, so the schema version does not move.
    assert config.schema_version == 1
    assert HubConfig.model_json_schema()["properties"]["schema_version"]["const"] == 1


@pytest.mark.parametrize("transport", ["api", "mcp"])
def test_accepts_transport_when_value_known(transport: str) -> None:
    config = HubConfig.model_validate(with_value(("tracker", "transport"), transport))

    assert config.tracker.transport == transport


@pytest.mark.parametrize("transport", ["connector", "", 1, "API"])
def test_rejects_transport_when_value_unknown(transport: object) -> None:
    document = with_value(("tracker", "transport"), transport)

    assert error_locs(document) == [("tracker", "transport")]
    # A known key with a bad value, not an unknown key.
    assert error_types(document) == [(("tracker", "transport"), "literal_error")]


def test_reads_team_keys_when_tracker_sets_team() -> None:
    tracker = HubConfig.model_validate(a_hub_document()).tracker

    assert tracker.team_keys == ("DEM",)
    assert tracker.default_team == "DEM"


def test_reads_team_keys_from_fields_when_tracker_copied() -> None:
    tracker = HubConfig.model_validate(a_hub_document()).tracker

    copied = tracker.model_copy(update={"team": "LONGTEAMKEY1"})

    assert copied.team_keys == ("LONGTEAMKEY1",)
    assert copied.default_team == "LONGTEAMKEY1"


TRACKER_TEAM_READ = re.compile(r"\.tracker\.teams?\b")


def test_reads_team_field_only_in_model_when_sources_scanned() -> None:
    """Readers go through Tracker.team_keys and Tracker.default_team (AGH-56)."""
    packages = Path(__file__).resolve().parents[4]
    assert packages.is_dir(), packages  # an empty scan would pass anywhere
    hits = {
        f"{source.relative_to(packages).as_posix()}:{number}": line.strip()
        for source in sorted(packages.glob("*/src/**/*.py"))
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1)
        if TRACKER_TEAM_READ.search(line)
    }

    assert hits == {}, "\n".join(f"{where}: {line}" for where, line in hits.items())


@pytest.mark.parametrize("key", IDENTITY_KEYS)
def test_accepts_document_when_identity_key_absent(key: str) -> None:
    document = a_hub_document()
    del document["project"][key]

    config = HubConfig.model_validate(document)

    assert getattr(config.project, key) is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("branch_prefix", "jdoe"),
        ("branch_prefix", "-x/"),
        ("branch_prefix", ""),
        ("branch_prefix", None),
        ("author_name", ""),
        ("author_name", "Jane\nDoe"),
        ("author_name", None),
        ("author_email", "jane"),
        ("author_email", ""),
        ("author_email", None),
    ],
)
def test_keeps_identity_patterns_when_key_present(key: str, value: object) -> None:
    assert error_locs(with_value(("project", key), value)) == [("project", key)]


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


@pytest.mark.parametrize(
    ("project_branch", "expected"),
    [(None, "main"), ("trunk", "trunk")],
    ids=["project-absent", "project-trunk"],
)
def test_inherits_project_branch_when_repo_sets_none(
    project_branch: str | None, expected: str
) -> None:
    document = a_hub_document()
    if project_branch is not None:
        document["project"]["default_branch"] = project_branch

    config = HubConfig.model_validate(document)

    assert config.repos[0].default_branch is None
    assert config.default_branch_for("demo-api") == expected


@pytest.mark.parametrize("branch", ["master", "release/2"])
def test_reads_repo_branch_when_repo_sets_one(branch: str) -> None:
    document = a_hub_document()
    document["project"]["default_branch"] = "trunk"
    document["repos"][0]["default_branch"] = branch
    document["repos"].append(a_second_repo())

    config = HubConfig.model_validate(document)

    assert config.default_branch_for("demo-api") == branch
    assert config.default_branch_for("demo-web") == "trunk"


def branch_errors(path: tuple[str | int, ...], value: object) -> list[tuple[Any, str, str]]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(with_value(path, value))
    return [(error["loc"], error["type"], error["msg"]) for error in caught.value.errors()]


@pytest.mark.parametrize("branch", ["-x", "a..b", "main/", "", 1, None])
def test_rejects_repo_branch_as_project_branch_when_value_invalid(branch: object) -> None:
    repo_path = ("repos", 0, "default_branch")
    project_path = ("project", "default_branch")

    [(repo_loc, repo_type, repo_msg)] = branch_errors(repo_path, branch)
    [(project_loc, project_type, project_msg)] = branch_errors(project_path, branch)

    assert repo_loc == repo_path
    assert project_loc == project_path
    assert (repo_type, repo_msg) == (project_type, project_msg)


def test_raises_key_error_when_repo_dir_unknown() -> None:
    config = HubConfig.model_validate(a_hub_document())

    with pytest.raises(KeyError, match="demo-web"):
        config.default_branch_for("demo-web")


PROJECT_BRANCH_READ = re.compile(
    r"\bproject\.default_branch|project_default_branch|\bcfg\.default_branch"
)

TEMPLATES = "generator/src/agent_hub/generator/templates"

# Lines per file that may read the project branch; a per-repo use calls default_branch_for.
PROJECT_BRANCH_READERS = {
    # the helper's fallback and the schema description of repos[].default_branch
    "core/src/agent_hub/core/hub_config/model.py": 2,
    # the project branch AGENTS.md names, which the doctor's refs rule skips as not a path
    "core/src/agent_hub/core/doctor/instruction_rules.py": 1,
    # the hub checkout's branch in the brief
    "cli/src/agent_hub/cli/brief_command.py": 1,
    # project_default_branch for ci.yml, and the project branch in AGENTS.md's mentions
    "generator/src/agent_hub/generator/placeholders.py": 2,
    # the project's branch in the managed settings' push denies (the guard's protected set)
    "generator/src/agent_hub/generator/built_json.py": 1,
    # the CI trigger branches
    f"{TEMPLATES}/github/workflows/ci.yml.tmpl": 2,
    # the hub repo's CI pair and the hub log
    f"{TEMPLATES}/scripts/retro_metrics.py.tmpl": 2,
    # Config.default_branch, and the project's branch in the protected set (also the root file's)
    f"{TEMPLATES}/plugin/hub-workflow/hooks/hubhooks.py.tmpl": 2,
}


def test_reads_project_branch_only_in_allowed_files_when_sources_scanned() -> None:
    packages = Path(__file__).resolve().parents[4]
    assert packages.is_dir(), packages  # an empty scan would pass anywhere
    hits = [
        (source.relative_to(packages).as_posix(), number, line.strip())
        for source in sorted(packages.glob("*/src/**/*"))
        if source.is_file() and source.suffix in {".py", ".tmpl"}
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1)
        if PROJECT_BRANCH_READ.search(line)
    ]
    counts: dict[str, int] = {}
    for name, _number, _line in hits:
        counts[name] = counts.get(name, 0) + 1

    assert counts == PROJECT_BRANCH_READERS, "\n".join(
        f"{name}:{number}: {line}" for name, number, line in hits
    )


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


def test_keeps_cross_field_error_when_top_level_key_is_null() -> None:
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


def test_keeps_nested_error_when_top_level_key_is_null() -> None:
    document = with_value(("guard",), None)
    document["project"]["name"] = "BAD"

    assert sorted(error_types(document)) == [
        (("guard",), "null_not_allowed"),
        (("project", "name"), "string_pattern_mismatch"),
    ]


@pytest.mark.parametrize(
    "path",
    [
        ("guard",),
        ("project", "name"),
        ("repos", 0, "role"),
        ("modules", "cloud"),
        ("doctor", "rules", "links.dead"),
        ("doctor", "rules", "links.dead", "severity"),
    ],
    ids=lambda path: ".".join(map(str, path)),
)
def test_reports_same_errors_when_null_document_validated_as_json(
    path: tuple[str | int, ...],
) -> None:
    document = with_value(("doctor",), {"rules": {"links.dead": {}}})
    document = with_path_value(document, path, None)
    document["tracker"]["team"] = "D-M"
    with pytest.raises(ValidationError) as from_python:
        HubConfig.model_validate(document)

    with pytest.raises(ValidationError) as from_json:
        HubConfig.model_validate_json(json.dumps(document))

    python_errors = {(error["loc"], error["type"]) for error in from_python.value.errors()}
    assert {(error["loc"], error["type"]) for error in from_json.value.errors()} == python_errors
    assert python_errors == {
        (path, "null_not_allowed"),
        (("tracker", "team"), "string_pattern_mismatch"),
    }


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


CONTRACT_SYNC = ("modules", "contract-sync")


def a_contract_sync_document(settings: object) -> dict[str, Any]:
    """The example document with ``demo-web`` added and these contract-sync settings."""
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["modules"]["contract-sync"] = settings
    return document


def test_accepts_every_module_when_all_selected() -> None:
    modules = {
        "cloud": {},
        "bench": {},
        "contract-sync": {"source": "demo-api", "target": "demo-web"},
        "marketplace": {},
    }
    document = a_contract_sync_document(modules["contract-sync"])
    document["modules"] = modules

    config = HubConfig.model_validate(document)

    assert config.model_dump(mode="json", exclude_none=True)["modules"] == modules


def test_rejects_module_when_id_unknown() -> None:
    assert error_types(with_value(("modules", "slack"), {})) == [
        (("modules", "slack"), "extra_forbidden")
    ]


def test_lists_json_ids_when_module_ids_read() -> None:
    assert MODULE_IDS == ("bench", "cloud", "contract-sync", "marketplace")


def test_rejects_module_settings_when_key_not_underscore() -> None:
    assert error_types(with_value(("modules", "cloud"), {"x": 1})) == [
        (("modules", "cloud", "x"), "extra_forbidden")
    ]


def test_accepts_module_settings_when_only_comment_keys() -> None:
    config = HubConfig.model_validate(with_value(("modules",), {"cloud": {"_note": "x"}}))

    assert config.model_dump(mode="json", exclude_none=True)["modules"] == {"cloud": {}}


@pytest.mark.parametrize("entry", [{}, {"enabled": False}, {"severity": "info"}])
def test_rejects_bench_rule_when_bench_module_not_selected(entry: dict[str, Any]) -> None:
    document = with_value(("modules",), {"cloud": {}})
    document["doctor"] = {"rules": {"bench.tasks": entry}}

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert error["loc"] == ("doctor", "rules", "bench.tasks")
    assert '"bench"' in error["msg"]


def test_accepts_bench_rule_when_bench_module_selected() -> None:
    document = with_value(("modules",), {"bench": {}})
    document["doctor"] = {"rules": {"bench.tasks": {"enabled": False}}}

    config = HubConfig.model_validate(document)

    assert config.doctor.rules.bench_tasks is not None
    assert config.doctor.rules.bench_tasks.enabled is False


# Every fixed-key object of a document that has them all, as a path from the root.
OBJECT_PATHS: list[tuple[str | int, ...]] = [
    (),
    ("platform",),
    ("project",),
    ("tracker",),
    ("repos", 0),
    ("guard",),
    ("modules",),
    ("modules", "cloud"),
    ("modules", "bench"),
    ("modules", "contract-sync"),
    ("modules", "marketplace"),
    ("doctor",),
    ("doctor", "rules"),
    ("doctor", "rules", "links.dead"),
    ("doctor", "rules", "instructions.size"),
    ("doctor", "rules", "brain.leak"),
]


def a_full_document() -> dict[str, Any]:
    document = a_contract_sync_document({"source": "demo-api", "target": "demo-web"})
    document["repos"][0]["default_branch"] = "release/2"
    document["modules"] |= {"marketplace": {}}
    document["guard"] |= {"deny_hosts": ["api.example.com"], "deny_paths": ["_archive"]}
    document["doctor"] = {
        "rules": {
            "links.dead": {"severity": "warning"},
            "instructions.size": {"max_lines": {"AGENTS.md": 120}},
            "brain.leak": {"min_line_length": 80},
        }
    }
    return document


def object_at(document: dict[str, Any], path: tuple[str | int, ...]) -> dict[str, Any]:
    target: Any = document
    for segment in path:
        target = target[segment]
    return target  # type: ignore[no-any-return]


@pytest.mark.parametrize("path", OBJECT_PATHS, ids=lambda path: ".".join(map(str, path)) or "root")
def test_drops_comment_keys_when_at_every_object_level(path: tuple[str | int, ...]) -> None:
    expected = HubConfig.model_validate(a_full_document()).model_dump(mode="json")
    document = a_full_document()
    object_at(document, path)["_comment"] = {"note": "ignored", "x": [1]}

    assert HubConfig.model_validate(document).model_dump(mode="json") == expected


@pytest.mark.parametrize("path", OBJECT_PATHS, ids=lambda path: ".".join(map(str, path)) or "root")
def test_rejects_unknown_key_when_at_any_object_level(path: tuple[str | int, ...]) -> None:
    document = a_full_document()
    object_at(document, path)["comment"] = "x"

    assert error_types(document) == [((*path, "comment"), "extra_forbidden")]


class TestContractSync:
    def test_accepts_settings_when_source_and_target_are_repos(self) -> None:
        settings = {"_note": "api to web", "source": "demo-api", "target": "demo-web"}

        config = HubConfig.model_validate(a_contract_sync_document(settings))

        assert config.modules.contract_sync is not None
        assert (config.modules.contract_sync.source, config.modules.contract_sync.target) == (
            "demo-api",
            "demo-web",
        )
        assert config.model_dump(mode="json", exclude_none=True)["modules"]["contract-sync"] == {
            "source": "demo-api",
            "target": "demo-web",
        }

    @pytest.mark.parametrize(
        ("settings", "locs"),
        [
            ({}, [(*CONTRACT_SYNC, "source"), (*CONTRACT_SYNC, "target")]),
            ({"source": "demo-api"}, [(*CONTRACT_SYNC, "target")]),
            ({"target": "demo-web"}, [(*CONTRACT_SYNC, "source")]),
            (
                {"source": "demo-api", "target": "demo-web", "branch": "main"},
                [(*CONTRACT_SYNC, "branch")],
            ),
        ],
        ids=["empty", "no-target", "no-source", "extra"],
    )
    def test_rejects_settings_when_key_missing_or_extra(
        self, settings: dict[str, Any], locs: list[tuple[str | int, ...]]
    ) -> None:
        assert error_locs(a_contract_sync_document(settings)) == locs

    @pytest.mark.parametrize("key", ["source", "target"])
    @pytest.mark.parametrize(
        ("value", "error_type"),
        [
            (1, "string_type"),
            (True, "string_type"),
            (["demo-api"], "string_type"),
            ({"dir": "demo-api"}, "string_type"),
            (None, "null_not_allowed"),
        ],
        ids=["int", "bool", "list", "object", "null"],
    )
    def test_rejects_value_when_not_string_or_null(
        self, key: str, value: object, error_type: str
    ) -> None:
        settings: dict[str, object] = {"source": "demo-api", "target": "demo-web"}
        settings[key] = value

        assert error_types(a_contract_sync_document(settings)) == [
            ((*CONTRACT_SYNC, key), error_type)
        ]

    @pytest.mark.parametrize("key", ["source", "target"])
    def test_rejects_repo_when_not_in_repos(self, key: str) -> None:
        settings = {"source": "demo-api", "target": "demo-web"} | {key: "nope"}

        with pytest.raises(ValidationError) as caught:
            HubConfig.model_validate(a_contract_sync_document(settings))

        [error] = caught.value.errors()
        assert (error["loc"], error["type"]) == ((*CONTRACT_SYNC, key), "unknown_repo_dir")
        assert error["msg"] == 'repo dir "nope" is not in repos'

    def test_rejects_settings_when_source_equals_target(self) -> None:
        settings = {"source": "demo-api", "target": "demo-api"}

        with pytest.raises(ValidationError) as caught:
            HubConfig.model_validate(a_contract_sync_document(settings))

        [error] = caught.value.errors()
        assert (error["loc"], error["type"]) == ((*CONTRACT_SYNC, "target"), "same_repo_dir")
        assert error["msg"] == 'target "demo-api" is the source too; give two different repos'

    def test_reports_only_same_repo_when_source_equals_target_and_not_in_repos(self) -> None:
        """Two steps: the settings' own error stops validation before HubConfig checks repos.

        A fix of ``same_repo_dir`` can then surface ``unknown_repo_dir`` on the next run.
        """
        settings = {"source": "nope", "target": "nope"}

        assert error_types(a_contract_sync_document(settings)) == [
            ((*CONTRACT_SYNC, "target"), "same_repo_dir")
        ]

    @pytest.mark.parametrize("module", ["cloud", "bench", "marketplace"])
    def test_rejects_settings_when_other_module_has_keys(self, module: str) -> None:
        assert error_types(with_value(("modules", module), {"x": 1})) == [
            (("modules", module, "x"), "extra_forbidden")
        ]

    def test_rejects_module_when_id_unknown(self) -> None:
        assert error_types(with_value(("modules", "deploy"), {})) == [
            (("modules", "deploy"), "extra_forbidden")
        ]
