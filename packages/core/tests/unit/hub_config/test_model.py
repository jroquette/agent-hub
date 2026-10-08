import itertools
import json
import posixpath
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.core.hub_config.model import (
    MAX_CHECK_FAST_TIMEOUT,
    MODULE_IDS,
    BranchName,
    BranchPrefix,
    GitHubRepo,
    HubConfig,
    RepoDir,
    Tracker,
)
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_MESSAGE
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_second_repo,
    a_two_team_document,
)
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    SECRET_PARTS,
    RepositoryCase,
)

REQUIRED_KEYS: list[tuple[str | int, ...]] = [
    ("schema_version",),
    ("platform",),
    ("platform", "version"),
    ("project",),
    ("project", "name"),
    ("project", "hub_repo"),
    ("tracker",),
    ("tracker", "kind"),
    # ``tracker.team`` is required while ``tracker.teams`` is absent.
    ("tracker", "team"),
    ("repos",),
    ("repos", 0, "dir"),
    ("repos", 0, "github"),
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


def test_reads_team_keys_when_tracker_sets_teams() -> None:
    tracker = HubConfig.model_validate(a_two_team_document()).tracker

    assert tracker.team_keys == ("APP", "OPS")
    assert tracker.default_team == "APP"
    assert tracker.team is None


def test_refuses_default_team_when_tracker_built_without_team_key() -> None:
    # Validation never builds it; the accessor still never returns a wrong team.
    tracker = Tracker.model_construct(kind="linear")

    assert tracker.team_keys == ()
    with pytest.raises(ValueError, match="no team key"):
        _ = tracker.default_team


def without_team(document: dict[str, Any]) -> dict[str, Any]:
    del document["tracker"]["team"]
    return document


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param(
            with_value(("tracker", "teams"), ["APP"]),
            (("tracker", "teams"), "team_and_teams"),
            id="both",
        ),
        pytest.param(
            without_team(a_hub_document()), (("tracker", "team"), "missing"), id="neither"
        ),
        pytest.param(
            with_path_value(without_team(a_hub_document()), ("tracker", "teams"), []),
            (("tracker", "teams"), "empty_list"),
            id="empty",
        ),
        pytest.param(
            with_path_value(without_team(a_hub_document()), ("tracker", "teams"), ["APP", "app"]),
            (("tracker", "teams", 1), "duplicate_team_key"),
            id="duplicate",
        ),
        pytest.param(
            with_path_value(without_team(a_hub_document()), ("tracker", "teams"), ["A-1"]),
            (("tracker", "teams", 0), "string_pattern_mismatch"),
            id="pattern",
        ),
        pytest.param(
            with_path_value(without_team(a_hub_document()), ("tracker", "teams"), "APP"),
            (("tracker", "teams"), "tuple_type"),
            id="string",
        ),
    ],
)
def test_rejects_tracker_when_team_keys_invalid(
    document: dict[str, Any], expected: tuple[tuple[str | int, ...], str]
) -> None:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    [error] = caught.value.errors()
    assert (error["loc"], error["type"]) == expected
    if error["type"] == "duplicate_team_key":
        assert '"app"' in error["msg"]
        assert "teams[0]" in error["msg"]


def test_names_first_use_for_each_repeat_when_team_key_repeated_twice() -> None:
    document = with_path_value(
        without_team(a_hub_document()), ("tracker", "teams"), ["A", "a", "A"]
    )

    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)

    errors = caught.value.errors()
    assert [(error["loc"], error["type"]) for error in errors] == [
        (("tracker", "teams", 1), "duplicate_team_key"),
        (("tracker", "teams", 2), "duplicate_team_key"),
    ]
    assert all("teams[0]" in error["msg"] for error in errors)


def test_reports_missing_team_alongside_kind_error_when_no_team_key_given() -> None:
    document = with_value(("tracker", "kind"), "jira")
    del document["tracker"]["team"]

    assert sorted(error_types(document)) == [
        (("tracker", "kind"), "literal_error"),
        (("tracker", "team"), "missing"),
    ]


def test_accepts_teams_when_keys_share_prefix() -> None:
    document = with_path_value(without_team(a_hub_document()), ("tracker", "teams"), ["AP", "APP"])

    assert HubConfig.model_validate(document).tracker.team_keys == ("AP", "APP")


TRACKER_TEAM_READ = re.compile(r"\.tracker\.teams?\b")


def test_reads_team_field_only_in_model_when_sources_scanned() -> None:
    """Readers go through Tracker.team_keys and Tracker.default_team (AGH-56)."""
    packages = Path(__file__).resolve().parents[4]
    assert packages.is_dir(), packages  # an empty scan would pass anywhere
    sources = sorted(packages.glob("*/src/**/*.py"))
    assert "core/src/agent_hub/core/hub_config/model.py" in {
        source.relative_to(packages).as_posix() for source in sources
    }
    hits = {
        f"{source.relative_to(packages).as_posix()}:{number}": line.strip()
        for source in sources
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


DEFAULT_CONVENTIONS = ("{prefix}{issue_lower}-{slug}", "{type}({scope}): {summary} ({ISSUE})")
MIXED_BRANCH = "{prefix}{ISSUE}-{slug}"
MIXED_TITLE = "{ISSUE}: {type}({scope}): {summary}"
REPO_BRANCH = "feature/{issue_lower}/{slug}"
PROJECT_CONVENTIONS = ("project", "conventions")
REPO_CONVENTIONS = ("repos", 0, "conventions")


def effective(config: HubConfig, repo_dir: str) -> tuple[str, str, str, bool]:
    conventions = config.conventions_for(repo_dir)
    return (
        conventions.branch,
        conventions.commit_title,
        conventions.pr_title,
        conventions.titles_configured,
    )


def a_layered_document(layers: str) -> dict[str, Any]:
    """The two-repo demo with the mixed hub's conventions at the named layers only."""
    document = a_conventions_document()
    if "project" not in layers:
        del document["project"]["conventions"]
    if "repo" not in layers:
        del document["repos"][0]["conventions"]
    return document


@pytest.mark.parametrize("layers", ["", "project", "repo", "project+repo"])
def test_accepts_document_when_conventions_layered(layers: str) -> None:
    document = a_layered_document(layers)

    config = HubConfig.model_validate(document)

    assert config.model_dump(mode="json", exclude_none=True, exclude_defaults=True) == document


def test_reads_effective_conventions_when_repo_overrides_branch() -> None:
    config = HubConfig.model_validate(a_conventions_document())

    assert effective(config, "demo-web") == (MIXED_BRANCH, MIXED_TITLE, MIXED_TITLE, True)
    assert effective(config, "demo-api") == (REPO_BRANCH, MIXED_TITLE, MIXED_TITLE, True)


def test_reads_default_conventions_when_hub_unconfigured() -> None:
    branch, title = DEFAULT_CONVENTIONS
    unconfigured = HubConfig.model_validate(a_hub_document())
    branch_only_document = a_hub_document()
    branch_only_document["repos"][0]["conventions"] = {"branch": MIXED_BRANCH}
    branch_only = HubConfig.model_validate(branch_only_document)

    assert effective(unconfigured, "demo-api") == (branch, title, title, False)
    assert effective(branch_only, "demo-api") == (MIXED_BRANCH, title, title, False)


def test_raises_key_error_when_conventions_dir_unknown() -> None:
    config = HubConfig.model_validate(a_hub_document())

    with pytest.raises(KeyError, match="demo-web"):
        config.conventions_for("demo-web")


@pytest.mark.parametrize("path", [PROJECT_CONVENTIONS, REPO_CONVENTIONS], ids=["project", "repo"])
def test_rejects_conventions_when_key_unknown(path: tuple[str | int, ...]) -> None:
    document = with_value(path, {"tag": "x"})

    assert error_types(document) == [((*path, "tag"), "extra_forbidden")]


BAD_BRANCHES = [
    "{prefix}{slug}",
    "{prefix}{type}-{ISSUE}",
    "{prefix}{ISSUE}{foo}",
    "{ISSUE}-{ISSUE}",
    "{prefix}{ISSUE} x",
    "{prefix}~{ISSUE}",
    "{prefix}{ISSUE}..{slug}",
    "{prefix}@{ISSUE}",
    "{prefix}{issue_lower}-{slug}-",
    "a" * 121 + "{ISSUE}",
]
BAD_TITLES = [
    "{slug} {summary}",
    "{prefix}{summary}",
    "{foo}{summary}",
    "{summary} {summary}",
    "{type}: x",
    "{summary} `x`",
    "{summary} {",
    "{summary}\x07",
    "a" * 112 + "{summary}",
    "{type}{scope}: {summary}",
]
BAD_PATTERNS = [("branch", value) for value in BAD_BRANCHES] + [
    (key, value) for key in ("commit_title", "pr_title") for value in BAD_TITLES
]


@pytest.mark.parametrize("layer", [PROJECT_CONVENTIONS, REPO_CONVENTIONS], ids=["project", "repo"])
@pytest.mark.parametrize(("key", "value"), BAD_PATTERNS, ids=[repr(row) for row in BAD_PATTERNS])
def test_rejects_pattern_at_its_key_when_conventions_invalid(
    layer: tuple[str | int, ...], key: str, value: str
) -> None:
    document = with_value(layer, {key: value})

    assert error_types(document) == [((*layer, key), "convention_pattern")]


def test_names_problem_when_conventions_pattern_invalid() -> None:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(with_value(REPO_CONVENTIONS, {"branch": "{prefix}{slug}"}))

    [error] = caught.value.errors()
    assert error["msg"] == "a branch needs {ISSUE} or {issue_lower}"


def test_names_touching_placeholders_at_key_when_title_pattern_invalid() -> None:
    document = with_value(PROJECT_CONVENTIONS, {"commit_title": "{type}{summary}"})

    assert pairing_errors(document) == [
        (
            (*PROJECT_CONVENTIONS, "commit_title"),
            "convention_pattern",
            "placeholders need a literal between them",
        )
    ]


def pairing_errors(document: dict[str, Any]) -> list[tuple[Any, str, str]]:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(document)
    return [(error["loc"], error["type"], error["msg"]) for error in caught.value.errors()]


TYPE_TITLE = "{type}: {summary}"
ISSUE_TITLE = "{ISSUE}: {summary}"
PAIRING_MESSAGE = "pr_title needs {type}, which commit_title `{ISSUE}: {summary}` lacks"


@pytest.mark.parametrize(
    ("project", "repo", "loc"),
    [
        (
            {"pr_title": TYPE_TITLE, "commit_title": ISSUE_TITLE},
            None,
            (*PROJECT_CONVENTIONS, "pr_title"),
        ),
        ({"commit_title": ISSUE_TITLE}, {"pr_title": TYPE_TITLE}, (*REPO_CONVENTIONS, "pr_title")),
        (
            None,
            {"pr_title": TYPE_TITLE, "commit_title": ISSUE_TITLE},
            (*REPO_CONVENTIONS, "pr_title"),
        ),
    ],
    ids=["project-pair", "repo-pr-project-commit", "repo-pair"],
)
def test_rejects_pr_title_when_commit_title_lacks_its_parts(
    project: dict[str, str] | None, repo: dict[str, str] | None, loc: tuple[str | int, ...]
) -> None:
    document = a_hub_document()
    if project is not None:
        document["project"]["conventions"] = project
    if repo is not None:
        document["repos"][0]["conventions"] = repo

    assert pairing_errors(document) == [(loc, "unfillable_pr_title", PAIRING_MESSAGE)]


def test_names_repo_commit_title_when_project_pr_title_clashes_with_override() -> None:
    document = a_hub_document()
    document["project"]["conventions"] = {"pr_title": TYPE_TITLE}
    document["repos"][0]["conventions"] = {"commit_title": ISSUE_TITLE}

    assert pairing_errors(document) == [
        (
            (*PROJECT_CONVENTIONS, "pr_title"),
            "unfillable_pr_title",
            "pr_title needs {type}, which repos[0].conventions.commit_title"
            " `{ISSUE}: {summary}` lacks",
        )
    ]


def test_lists_every_clashing_repo_when_project_pr_title_unfillable() -> None:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["project"]["conventions"] = {"pr_title": "{type}({scope}): {summary}"}
    document["repos"][0]["conventions"] = {"commit_title": ISSUE_TITLE}
    document["repos"][1]["conventions"] = {"commit_title": TYPE_TITLE}

    assert pairing_errors(document) == [
        (
            (*PROJECT_CONVENTIONS, "pr_title"),
            "unfillable_pr_title",
            "pr_title needs {type}, {scope}, which repos[0].conventions.commit_title"
            " `{ISSUE}: {summary}` lacks; pr_title needs {scope}, which"
            " repos[1].conventions.commit_title `{type}: {summary}` lacks",
        )
    ]


def test_joins_inherited_and_override_clashes_when_project_pr_title_unfillable() -> None:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["project"]["conventions"] = {"pr_title": TYPE_TITLE, "commit_title": ISSUE_TITLE}
    document["repos"][1]["conventions"] = {"commit_title": "{ISSUE} {summary}"}

    assert pairing_errors(document) == [
        (
            (*PROJECT_CONVENTIONS, "pr_title"),
            "unfillable_pr_title",
            f"{PAIRING_MESSAGE}; pr_title needs {{type}}, which"
            " repos[1].conventions.commit_title `{ISSUE} {summary}` lacks",
        )
    ]


def test_reports_pr_title_once_when_two_repos_inherit_it() -> None:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["project"]["conventions"] = {"pr_title": TYPE_TITLE, "commit_title": ISSUE_TITLE}

    assert pairing_errors(document) == [
        ((*PROJECT_CONVENTIONS, "pr_title"), "unfillable_pr_title", PAIRING_MESSAGE)
    ]


def test_accepts_project_pr_title_when_every_repo_overrides_it() -> None:
    """The pairing is checked on each repo's effective patterns, not on each layer alone."""
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["project"]["conventions"] = {"pr_title": TYPE_TITLE, "commit_title": ISSUE_TITLE}
    for repo in document["repos"]:
        repo["conventions"] = {"pr_title": ISSUE_TITLE}

    config = HubConfig.model_validate(document)

    for repo_dir in ("demo-api", "demo-web"):
        assert config.conventions_for(repo_dir).pr_title == ISSUE_TITLE


def test_names_every_missing_part_when_pr_title_unfillable() -> None:
    document = with_value(
        PROJECT_CONVENTIONS,
        {"pr_title": "{type}({scope}): {summary}", "commit_title": ISSUE_TITLE},
    )

    assert pairing_errors(document) == [
        (
            (*PROJECT_CONVENTIONS, "pr_title"),
            "unfillable_pr_title",
            "pr_title needs {type}, {scope}, which commit_title `{ISSUE}: {summary}` lacks",
        )
    ]


@pytest.mark.parametrize("layer", [PROJECT_CONVENTIONS, REPO_CONVENTIONS], ids=["project", "repo"])
def test_accepts_commit_title_alone_when_pr_title_follows_it(layer: tuple[str | int, ...]) -> None:
    config = HubConfig.model_validate(with_value(layer, {"commit_title": ISSUE_TITLE}))

    conventions = config.conventions_for("demo-api")
    assert (conventions.commit_title, conventions.pr_title) == (ISSUE_TITLE, ISSUE_TITLE)
    assert conventions.pr_title_explicit is False


@pytest.mark.parametrize("layer", [PROJECT_CONVENTIONS, REPO_CONVENTIONS], ids=["project", "repo"])
@pytest.mark.parametrize("title", ["{type}({scope}): {summary}", ISSUE_TITLE])
@pytest.mark.parametrize("keys", [("commit_title",), ("pr_title",), ("commit_title", "pr_title")])
def test_accepts_titles_when_issue_omitted(
    layer: tuple[str | int, ...], title: str, keys: tuple[str, ...]
) -> None:
    config = HubConfig.model_validate(with_value(layer, dict.fromkeys(keys, title)))

    conventions = config.conventions_for("demo-api")
    assert [getattr(conventions, key) for key in keys] == [title] * len(keys)


@pytest.mark.parametrize("layer", [PROJECT_CONVENTIONS, REPO_CONVENTIONS], ids=["project", "repo"])
def test_accepts_branch_when_named_after_agent(layer: tuple[str | int, ...]) -> None:
    config = HubConfig.model_validate(with_value(layer, {"branch": "claude/{issue_lower}"}))

    assert config.conventions_for("demo-api").branch == "claude/{issue_lower}"


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


def test_accepts_repo_when_check_fast_absent_or_blank() -> None:
    document = a_hub_document()
    del document["repos"][0]["check_fast"]

    assert HubConfig.model_validate(document).repos[0].check_fast is None
    for value in ("", "  "):
        config = HubConfig.model_validate(with_value(("repos", 0, "check_fast"), value))
        assert config.repos[0].check_fast == value


@pytest.mark.parametrize("value", ["make check", " make check "])
def test_accepts_check_when_it_holds_non_space(value: str) -> None:
    config = HubConfig.model_validate(with_value(("repos", 0, "check"), value))

    assert config.repos[0].check == value


@pytest.mark.parametrize("value", ["", " ", "   ", "\u00a0", "\u3000", " \u2028 "])
def test_rejects_check_when_blank(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        HubConfig.model_validate(with_value(("repos", 0, "check"), value))

    [error] = caught.value.errors()
    assert error["loc"] == ("repos", 0, "check")
    assert error["type"] == "blank_command"
    assert error["msg"] == "must hold a non-space character"


@pytest.mark.parametrize("value", ["\t", " \t ", "\x85"])
def test_rejects_check_when_blank_with_control_character(value: str) -> None:
    assert error_locs(with_value(("repos", 0, "check"), value)) == [("repos", 0, "check")]


@pytest.mark.parametrize("timeout", [1, 160])
def test_accepts_check_fast_timeout_when_in_range(timeout: int) -> None:
    config = HubConfig.model_validate(with_value(("repos", 0, "check_fast_timeout"), timeout))

    assert config.repos[0].check_fast_timeout == timeout


@pytest.mark.parametrize("timeout", [0, 161, 1.5, 150.0, "10", True, None])
def test_rejects_check_fast_timeout_when_not_integer_in_range(timeout: object) -> None:
    document = with_value(("repos", 0, "check_fast_timeout"), timeout)

    [(loc, kind)] = error_types(document)
    assert loc == ("repos", 0, "check_fast_timeout")
    assert kind != "extra_forbidden"


def test_states_check_fast_timeout_cap_when_module_read() -> None:
    assert MAX_CHECK_FAST_TIMEOUT == 160


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
    ("project", "conventions"),
    ("tracker",),
    ("repos", 0),
    ("repos", 0, "conventions"),
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
    document["platform"]["repository"] = CUSTOM_REPOSITORY
    document["repos"][0]["default_branch"] = "release/2"
    document["project"]["conventions"] = {"commit_title": "{ISSUE}: {summary}"}
    document["repos"][0]["conventions"] = {"branch": "feature/{issue_lower}/{slug}"}
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


GOOD_REPOSITORIES = [case for case in REPOSITORY_CASES if case.is_valid]
# ``null`` is never a value, for any key: it keeps the null message (ConfigObject).
BAD_REPOSITORIES = [
    case for case in REPOSITORY_CASES if not case.is_valid and case.value is not None
]


def case_name(case: RepositoryCase) -> str:
    return case.name


class TestPlatformRepository:
    @pytest.mark.parametrize("case", GOOD_REPOSITORIES, ids=case_name)
    def test_accepts_platform_repository_when_value_good(self, case: RepositoryCase) -> None:
        config = HubConfig.model_validate(with_value(("platform", "repository"), case.value))

        assert config.platform.repository == case.value
        assert config.platform.effective_repository == case.value

    def test_reads_default_repository_when_key_absent(self) -> None:
        config = HubConfig.model_validate(a_hub_document())

        assert config.platform.repository is None
        assert config.platform.effective_repository == "git+https://github.com/jroquette/agent-hub"

    @pytest.mark.parametrize("case", BAD_REPOSITORIES, ids=case_name)
    def test_rejects_platform_repository_at_its_key_when_value_bad(
        self, case: RepositoryCase
    ) -> None:
        document = with_value(("platform", "repository"), case.value)
        with pytest.raises(ValidationError) as caught:
            HubConfig.model_validate(document)

        [error] = caught.value.errors()
        assert (error["loc"], error["type"]) == (("platform", "repository"), "platform_repository")
        assert error["msg"] == PLATFORM_REPOSITORY_MESSAGE
        assert [part for part in SECRET_PARTS if part in error["msg"]] == []
        if isinstance(case.value, str) and case.value:
            assert case.value not in error["msg"]

    def test_rejects_null_repository_with_null_message_when_null(self) -> None:
        document = with_value(("platform", "repository"), None)
        with pytest.raises(ValidationError) as caught:
            HubConfig.model_validate(document)

        [error] = caught.value.errors()
        assert (error["loc"], error["type"]) == (("platform", "repository"), "null_not_allowed")
        assert error["msg"] == "null is not a value; give a value or leave the key out"
