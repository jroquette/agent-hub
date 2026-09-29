from importlib.metadata import version
from typing import Any

import pytest

from agent_hub.cli.init_config import document_from_flags, flag_problems
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.json_form import dump_json

VERSION = version("agent-hub-cli")
# DEMO_FLAGS of the spec, by keyword.
DEMO_FLAGS: dict[str, Any] = {
    "project": "demo",
    "repos": "acme/demo-api",
    "tracker": "linear:DEM",
    "branch_prefix": "jdoe/",
    "author_name": "Jane Doe",
    "author_email": "jane@example.com",
    "hub_repo": "acme/demo-hub",
}
# The pattern messages quote the model's patterns, so they are built from the same text.
SAFE_SEGMENT = r"[A-Za-z0-9_]+(?:[._-][A-Za-z0-9_]+)*"
GITHUB_PATTERN = f"String should match pattern '^{SAFE_SEGMENT}/{SAFE_SEGMENT}$'"
DIR_PATTERN = f"String should match pattern '^{SAFE_SEGMENT}$'"
TEAM_PATTERN = "String should match pattern '^[A-Za-z0-9]+$'"


def demo_document(**flags: Any) -> dict[str, Any]:
    return document_from_flags(**(DEMO_FLAGS | flags), version=VERSION)


def problems_of(document: dict[str, Any]) -> tuple[ConfigProblem, ...]:
    checked = check_hub_document(document, running_version=VERSION)
    assert not isinstance(checked, HubConfig)
    return checked


def test_builds_exact_keys_when_all_flags_given() -> None:
    expected = {
        "$schema": "./hub.schema.json",
        "schema_version": 1,
        "platform": {"version": VERSION},
        "project": {
            "name": "demo",
            "hub_repo": "acme/demo-hub",
            "branch_prefix": "jdoe/",
            "author_name": "Jane Doe",
            "author_email": "jane@example.com",
        },
        "tracker": {"kind": "linear", "team": "DEM"},
        "repos": [
            {
                "dir": "demo-api",
                "github": "acme/demo-api",
                "role": "app",
                "check_fast": "make check-fast",
                "check": "make check",
            }
        ],
    }

    document = demo_document()

    assert document == expected
    assert dump_json(document) == dump_json(expected)
    assert not {"guard", "modules", "doctor"} & document.keys()
    assert "default_branch" not in document["project"]
    assert not {"ready_label", "failed_label"} & document["tracker"].keys()


def test_keeps_flag_order_when_repos_listed() -> None:
    document = demo_document(repos="acme/a,acme/b")

    assert [(repo["dir"], repo["github"]) for repo in document["repos"]] == [
        ("a", "acme/a"),
        ("b", "acme/b"),
    ]


def test_takes_dir_after_last_slash_when_repo_has_path() -> None:
    # The github value is the model's to refuse; the dir is always the last part.
    document = demo_document(repos="acme/tools/demo-api")

    assert document["repos"][0]["dir"] == "demo-api"
    assert document["repos"][0]["github"] == "acme/tools/demo-api"


@pytest.mark.parametrize(
    ("tracker", "kind", "team"),
    [
        ("linear:DEM", "linear", "DEM"),
        # No colon: the value is the kind, so `--tracker linear` names only the missing team.
        ("linear", "linear", ""),
        ("DEM", "DEM", ""),
        ("linear:DEM:X", "linear", "DEM:X"),
    ],
    ids=["kind-and-team", "no-colon-kind", "no-colon-team", "first-colon"],
)
def test_splits_tracker_on_first_colon_when_tracker_given(
    tracker: str, kind: str, team: str
) -> None:
    document = demo_document(tracker=tracker)

    assert document["tracker"] == {"kind": kind, "team": team}


# The seven values of AC-12.8, each with the lines it must print.
REJECTED = [
    pytest.param(
        {"tracker": "jira:DEM"}, ["--tracker: Input should be 'linear'"], id="tracker-kind"
    ),
    pytest.param(
        {"tracker": "DEM"},
        ["--tracker: Input should be 'linear'", f"--tracker: {TEAM_PATTERN}"],
        id="tracker-no-kind",
    ),
    pytest.param({"tracker": "linear"}, [f"--tracker: {TEAM_PATTERN}"], id="tracker-no-team"),
    pytest.param(
        {"repos": "acme"}, [f'--repos item 1 ("acme"): {GITHUB_PATTERN}'], id="repo-no-owner"
    ),
    pytest.param(
        # The empty item's dir is derived from its github, which already failed: one line.
        {"repos": "acme/a,,acme/b"},
        [f'--repos item 2 (""): {GITHUB_PATTERN}'],
        id="repo-empty",
    ),
    pytest.param(
        {"repos": "acme/a,ACME/A"},
        ['--repos item 2 ("ACME/A"): repo dir "A" is already used by repos[0], ignoring case'],
        id="repo-duplicate",
    ),
    pytest.param(
        {"project": "Demo"},
        ["PROJECT: String should match pattern '^[a-z0-9]+(-[a-z0-9]+)*$'"],
        id="project-name",
    ),
    pytest.param(
        {"branch_prefix": "jdoe"},
        [f"--branch-prefix: String should match pattern '^{SAFE_SEGMENT}/$'"],
        id="branch-prefix",
    ),
]


@pytest.mark.parametrize(("flags", "lines"), REJECTED)
def test_names_flag_when_model_rejects_value(flags: dict[str, str], lines: list[str]) -> None:
    problems = problems_of(demo_document(**flags))

    printed = flag_problems(problems, repos=flags.get("repos", DEMO_FLAGS["repos"]))

    assert printed == lines
    # Each line ends with the model's own message (a derived dir line may be dropped).
    assert all(any(line.endswith(f": {p.message}") for p in problems) for line in printed)


def test_names_every_missing_flag_when_values_absent() -> None:
    document = demo_document(branch_prefix=None, author_name=None, author_email=None, hub_repo=None)

    printed = flag_problems(problems_of(document), repos=DEMO_FLAGS["repos"])

    # All in one run, in the model's field order.
    assert printed == [
        "--hub-repo: Field required",
        "--branch-prefix: Field required",
        "--author-name: Field required",
        "--author-email: Field required",
    ]
    assert (
        not {"hub_repo", "branch_prefix", "author_name", "author_email"}
        & document["project"].keys()
    )


def test_names_each_project_flag_when_its_value_rejected() -> None:
    document = demo_document(hub_repo="demo-hub", author_name="Jane\nDoe", author_email="jane")

    printed = flag_problems(problems_of(document), repos=DEMO_FLAGS["repos"])

    assert [line.split(": ", 1)[0] for line in printed] == [
        "--hub-repo",
        "--author-name",
        "--author-email",
    ]


def test_shows_json_path_when_problem_has_no_flag() -> None:
    # The running version is the pin; a version of another shape is no flag's fault.
    document = document_from_flags(**DEMO_FLAGS, version="1.0")

    printed = flag_problems(problems_of(document), repos=DEMO_FLAGS["repos"])

    assert printed == ['platform.version: must be three numbers such as 1.2.3, not "1.0"']


def test_validates_with_hub_config_when_document_built() -> None:
    document = demo_document(repos="acme/a,acme/b")

    checked = check_hub_document(document, running_version=VERSION)

    assert checked == HubConfig.model_validate(document)


@pytest.mark.parametrize(
    ("repos", "line"),
    [
        # 1-based, and the item that failed, not the first one.
        ("acme/a,acme", f'--repos item 2 ("acme"): {GITHUB_PATTERN}'),
        # The item as typed: the space before it is part of the value.
        ("acme/a, acme/b", f'--repos item 2 (" acme/b"): {GITHUB_PATTERN}'),
        # JSON-quoted, so a quote in the value cannot end it.
        ('acme/"x', f'--repos item 1 ("acme/\\"x"): {GITHUB_PATTERN}'),
    ],
    ids=["second-item", "raw-value", "quoted-value"],
)
def test_names_item_and_value_when_repo_rejected(repos: str, line: str) -> None:
    problems = problems_of(demo_document(repos=repos))

    printed = flag_problems(problems, repos=repos)

    assert printed == [line]


@pytest.mark.parametrize(
    ("problems", "lines"),
    [
        (
            # Another item's github failed: this item's dir line stays.
            [ConfigProblem("repos[0].dir", "bad dir"), ConfigProblem("repos[1].github", "bad")],
            ['--repos item 1 ("acme/a"): bad dir', '--repos item 2 ("acme"): bad'],
        ),
        (
            # Only the derived dir is dropped: another field of the same item stays.
            [ConfigProblem("repos[0].github", "bad"), ConfigProblem("repos[0].check", "bad check")],
            ['--repos item 1 ("acme/a"): bad', '--repos item 1 ("acme/a"): bad check'],
        ),
        (
            # A problem with the list itself names no item.
            [ConfigProblem("repos", "bad list")],
            ["--repos: bad list"],
        ),
    ],
    ids=["other-item-dir-kept", "other-field-kept", "no-item"],
)
def test_keeps_line_when_not_derived_from_failed_github(
    problems: list[ConfigProblem], lines: list[str]
) -> None:
    printed = flag_problems(problems, repos="acme/a,acme")

    assert printed == lines
