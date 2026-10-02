from pathlib import Path

import pytest

from agent_hub.cli.run_children import RunChildren, push_env
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

OVERRIDES = [
    ("core.fsmonitor", "false"),
    ("push.gpgSign", "false"),
    ("core.hooksPath", "/dev/null"),
]


def pairs(env: dict[str, str]) -> list[tuple[str, str]]:
    count = int(env["GIT_CONFIG_COUNT"])
    return [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)]


def test_adds_overrides_when_caller_sets_none() -> None:
    token = "y" * 8
    env = push_env({"PATH": "/bin", "LINEAR_API_KEY": "x", "GH_TOKEN": token})

    assert pairs(env) == OVERRIDES
    assert env["GH_TOKEN"] == token
    assert "LINEAR_API_KEY" not in env


def test_keeps_other_git_config_variables_when_overrides_added() -> None:
    env = push_env({"GIT_CONFIG_GLOBAL": "/home/x/.gitconfig", "GIT_CONFIG_NOSYSTEM": "1"})

    assert env["GIT_CONFIG_GLOBAL"] == "/home/x/.gitconfig"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_appends_overrides_when_caller_sets_some() -> None:
    caller = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "J"}

    assert pairs(push_env(caller)) == [("user.name", "J"), *OVERRIDES]


@pytest.mark.parametrize(
    "count", ["", "x", "-1", "\N{SUPERSCRIPT TWO}", "\N{ARABIC-INDIC DIGIT ONE}"]
)
def test_replaces_count_when_caller_count_invalid(count: str) -> None:
    env = push_env(
        {"GIT_CONFIG_COUNT": count, "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_GLOBAL": "/g"}
    )

    assert pairs(env) == OVERRIDES
    assert env["GIT_CONFIG_GLOBAL"] == "/g"


def run_children(repo: str, *, api_branch: str | None) -> RunChildren:
    """The children of a run on ``repo`` in a hub on ``trunk`` whose ``demo-api`` may set its
    own branch."""
    document = a_hub_document()
    document["project"]["default_branch"] = "trunk"
    document["repos"].append(a_second_repo())
    if api_branch is not None:
        document["repos"][0]["default_branch"] = api_branch
    config = HubConfig.model_validate(document)
    return RunChildren(config=config, hub=Path("/ws/hub"), repo=repo, issue_id="DEM-1")


def base_argument(argv: list[str]) -> str:
    return argv[argv.index("--base") + 1]


@pytest.mark.parametrize(("repo", "branch"), [("demo-api", "master"), ("demo-web", "trunk")])
def test_bases_run_on_repo_branch_when_repo_sets_one(repo: str, branch: str) -> None:
    children = run_children(repo, api_branch="master")

    assert children.base == f"origin/{branch}"
    assert base_argument(children.pr_argv(title="t", body="b")) == branch


@pytest.mark.parametrize("repo", ["demo-api", "demo-web"])
def test_bases_run_on_project_branch_when_repo_sets_none(repo: str) -> None:
    children = run_children(repo, api_branch=None)

    assert children.base == "origin/trunk"
    assert base_argument(children.pr_argv(title="t", body="b")) == "trunk"
