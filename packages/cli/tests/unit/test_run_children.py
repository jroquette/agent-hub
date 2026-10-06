from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.run_children import RunChildren, RunOptions, push_env
from agent_hub.cli.worktree_steps import worktree_task
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_second_repo,
    an_issue,
)

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
    return RunChildren(
        config=config, hub=Path("/ws/hub"), repo=repo, issue_id="DEM-1", branch_prefix="jdoe/"
    )


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


OPTIONS = RunOptions(
    live=False, max_turns=40, budget=3.0, model="sonnet", start="implement", effort="medium"
)


def session_prompt(tracker: dict[str, object], issue_id: str) -> str:
    """The implementing session's prompt for ``issue_id`` in a hub whose tracker is ``tracker``."""
    document = a_hub_document()
    document["tracker"] = {"kind": "linear", **tracker}
    children = RunChildren(
        config=HubConfig.model_validate(document),
        hub=Path("/ws/hub"),
        repo="demo-api",
        issue_id=issue_id,
        branch_prefix="jdoe/",
    )
    argv = children.session_argv(an_issue(id=issue_id), OPTIONS)
    return argv[argv.index("-p") + 1]


def test_prefixes_prompt_with_issue_team_when_hub_lists_teams() -> None:
    prompt = session_prompt({"teams": ["APP", "OPS"]}, "OPS-12")

    assert "(OPS-N)" in prompt
    assert "(APP-N)" not in prompt


def test_prefixes_prompt_with_configured_spelling_when_key_lowercase() -> None:
    prompt = session_prompt({"team": "app"}, "APP-1")

    assert "(app-N)" in prompt
    assert "(APP-N)" not in prompt


def test_refuses_team_when_issue_matches_no_team() -> None:
    document = a_hub_document()
    children = RunChildren(
        config=HubConfig.model_validate(document),
        hub=Path("/ws/hub"),
        repo="demo-api",
        issue_id="OPS-1",
        branch_prefix="jdoe/",
    )

    with pytest.raises(ValueError, match=r"^OPS-1 matches no team of hub\.json$"):
        _ = children.team


def children_of(document: dict[str, Any], repo: str) -> RunChildren:
    return RunChildren(
        config=HubConfig.model_validate(document),
        hub=Path("/ws/hub"),
        repo=repo,
        issue_id="DEM-1",
        branch_prefix="jdoe/",
    )


def unconfigured_two_repo_document() -> dict[str, Any]:
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    return document


HUB_BRANCHES = {
    "mixed-api": (a_conventions_document, "demo-api", "feature/dem-1"),
    "mixed-web": (a_conventions_document, "demo-web", "jdoe/DEM-1"),
    "unconfigured-api": (unconfigured_two_repo_document, "demo-api", "jdoe/dem-1"),
    "unconfigured-web": (unconfigured_two_repo_document, "demo-web", "jdoe/dem-1"),
}


@pytest.mark.parametrize(
    ("document", "repo", "branch"), list(HUB_BRANCHES.values()), ids=list(HUB_BRANCHES)
)
def test_takes_branch_from_repo_convention_when_hub_sets_conventions(
    document: Any, repo: str, branch: str
) -> None:
    children = children_of(document(), repo)
    pr_argv = children.pr_argv(title="t", body="b")

    assert children.branch == branch
    assert children.push_argv()[-1] == branch
    assert pr_argv[pr_argv.index("--head") + 1] == branch
    assert children.pr_view_argv()[3] == branch


def accepting_runner(
    argv: Sequence[str],
    *,
    cwd: Path | str,
    env: Mapping[str, str],
    timeout: float | None,
    own_session: bool | None = None,
) -> ChildResult:
    """A git that accepts every call (``check-ref-format`` is the only one ``worktree_task``
    makes)."""
    del argv, cwd, env, timeout, own_session
    return ChildResult(returncode=0, stdout=b"", stderr=b"")


@pytest.mark.parametrize(
    ("document", "repo", "branch"), list(HUB_BRANCHES.values()), ids=list(HUB_BRANCHES)
)
def test_matches_worktree_branch_when_run_and_worktree_build_it(
    document: Any, repo: str, branch: str
) -> None:
    children = children_of(document(), repo)

    task = worktree_task(
        children.config,
        name=children.slug,
        branch_prefix=children.branch_prefix,
        only=repo,
        hub=children.hub,
        git="git",
        env={},
        git_timeout=None,
        runner=accepting_runner,
    )

    assert task.branches == {repo: branch}
    assert children.branch == task.branches[repo]
