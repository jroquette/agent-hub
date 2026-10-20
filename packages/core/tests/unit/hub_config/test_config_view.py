from collections.abc import Mapping
from typing import Any

from agent_hub.core.hub_config.config_view import hub_config_view
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_models_document,
)


def _no_git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {}


def _git(_keys: frozenset[str]) -> Mapping[str, str]:
    return {"author_name": "Git Person", "author_email": "git.person@example.com"}


def _view(document: dict[str, Any], local: object = None, read_git: Any = _no_git) -> Any:
    return hub_config_view(
        hub_path="/hubs/demo-hub",
        config=HubConfig.model_validate(document),
        local=LocalConfig() if local is None else local,  # type: ignore[arg-type]
        read_git=read_git,
    )


def test_identity_comes_from_the_team_file_when_only_it_sets_it() -> None:
    view = _view(a_hub_document())

    assert (view.author_name.value, view.author_name.source) == ("Jane Doe", "team")
    assert view.author_email.where == "hub.json → project.author_email"


def test_takes_local_identity_when_team_file_also_sets_it() -> None:
    local = LocalConfig.model_validate({"project": {"author_email": "me@example.com"}})

    view = _view(a_hub_document(), local)

    assert (view.author_email.value, view.author_email.source) == ("me@example.com", "local")
    assert view.author_email.where == "hub.local.json → project.author_email"


def test_falls_back_to_git_and_derives_prefix_when_identity_unset() -> None:
    document = a_hub_document()
    for key in ("author_name", "author_email", "branch_prefix"):
        del document["project"][key]

    view = _view(document, read_git=_git)

    assert (view.author_name.source, view.author_name.where) == ("git", "git config user.name")
    assert (view.branch_prefix.value, view.branch_prefix.source) == ("git.person/", "derived")


def test_shows_built_in_conventions_with_examples_when_repo_unconfigured() -> None:
    repo = _view(a_hub_document()).repos[0]

    assert repo.commit_title.source == "default"
    assert repo.commit_title.example == "feat(api): add the hub config view (DEM-42)"
    assert repo.branch.example == "jdoe/dem-42-hub-config"
    assert repo.pr_title.source == "commit_title"


def test_takes_repo_conventions_when_repo_overrides_project() -> None:
    document = a_hub_document()
    document["project"]["conventions"] = {"commit_title": "{type}: {summary}"}
    document["repos"][0]["conventions"] = {"commit_title": "[{ISSUE}] {summary}"}

    view = _view(document)

    assert view.conventions[1].source == "project"
    assert view.repos[0].commit_title.source == "repo"
    assert view.repos[0].commit_title.where == "hub.json → repos[0].conventions.commit_title"
    assert view.repos[0].commit_title.example == "[DEM-42] add the hub config view"


def test_names_branch_source_when_repo_or_project_sets_it() -> None:
    document = a_hub_document()
    document["repos"][0]["default_branch"] = "develop"

    view = _view(document)

    assert view.default_branch.source == "default"
    assert (view.repos[0].default_branch.value, view.repos[0].default_branch.source) == (
        "develop",
        "team",
    )


def test_keeps_layers_apart_when_blocked_words_read() -> None:
    document = a_hub_document()
    document["guard"]["blocked_words"] = ["acme-prod"]
    local = LocalConfig.model_validate({"guard": {"blocked_words": ["my-client"]}})

    guard = _view(document, local).guard

    assert guard.blocked_words.team == ("acme-prod",)
    assert guard.blocked_words.local == ("my-client",)


def test_reports_and_ignores_local_file_when_invalid() -> None:
    problems = (ConfigProblem("project.author_email", "not an email"),)

    view = _view(a_hub_document(), problems)

    assert view.local_file.problems == ("project.author_email: not an email",)
    assert view.author_email.source == "team"


# AC-PG-38.1: per repo of hub.json, the checks it runs, while working and before a PR.
def test_lists_each_repo_checks_when_hub_has_two_repos() -> None:
    view = _view(a_conventions_document())

    assert [(repo.index, repo.dir, repo.github) for repo in view.repos] == [
        (0, "demo-api", "acme/demo-api"),
        (1, "demo-web", "acme/demo-web"),
    ]
    assert [(repo.check_fast, repo.check) for repo in view.repos] == [
        ("make check-fast", "make check"),
        ("make check-fast", "make check"),
    ]
    assert view.repos[0].check_fast_timeout is None


# AC-PG-38.1: the PR title pattern of each repo, with its layer and a rendered example.
def test_renders_pr_title_example_when_project_sets_pr_title() -> None:
    view = _view(a_conventions_document())

    pr_title = view.repos[1].pr_title
    assert (pr_title.pattern, pr_title.source) == ("{ISSUE}: {type}({scope}): {summary}", "project")
    assert pr_title.where == "hub.json → project.conventions.pr_title"
    assert pr_title.example == "DEM-42: feat(api): add the hub config view"
    assert view.repos[0].branch.example == "feature/dem-42/hub-config"


# AC-PG-38.1: the tracker, with its transport's source (built-in default here).
def test_answers_tracker_with_default_transport_when_team_sets_only_kind_and_team() -> None:
    tracker = _view(a_hub_document()).tracker

    assert (tracker.kind, tracker.teams) == ("linear", ("DEM",))
    assert (tracker.transport.value, tracker.transport.source) == ("api", "default")
    assert (tracker.ready_label, tracker.failed_label, tracker.blocked_label) == (
        "agent-ready",
        "agent-failed",
        None,
    )
    assert (tracker.started_state, tracker.review_state) == ("In Progress", "In Review")


# AC-PG-38.1: the local layer wins over the team's tracker transport, which stays visible.
def test_takes_local_transport_when_local_file_sets_it() -> None:
    local = LocalConfig.model_validate({"tracker": {"transport": "mcp"}})

    transport = _view(a_hub_document(), local).tracker.transport

    assert (transport.value, transport.source, transport.team_value) == ("mcp", "local", "api")
    assert transport.where == "hub.local.json → tracker.transport"


# AC-PG-38.1: the models: each tier's model (defaults filled in) and the agents moved off theirs.
def test_answers_tiers_and_moved_agents_when_models_set() -> None:
    view = _view(a_models_document())

    assert view.model_tiers == {"small": "haiku", "medium": "sonnet", "large": "claude-opus-4-1"}
    assert {(item.agent, item.tier) for item in view.agent_models} == {
        ("evaluator", "small"),
        ("researcher", "large"),
    }


# AC-PG-38.1: without a models block, the built-in tier models and no moved agent.
def test_answers_default_tiers_when_models_unset() -> None:
    view = _view(a_hub_document())

    assert view.model_tiers == {"small": "haiku", "medium": "sonnet", "large": "opus"}
    assert view.agent_models == ()


# The screen marks a tier the team names apart from a built-in one.
def test_names_team_tiers_when_models_set() -> None:
    assert _view(a_models_document()).model_tiers_set == ("medium", "large")


def test_names_no_team_tier_when_models_unset() -> None:
    assert _view(a_hub_document()).model_tiers_set == ()


# The screen marks the tracker labels and states the team sets apart from built-in ones.
def test_names_team_tracker_keys_when_hub_sets_some() -> None:
    document = a_hub_document()
    document["tracker"] = {
        **document["tracker"],
        "ready_label": "go",
        "states": {"review": "Review"},
    }

    assert _view(document).tracker.team_set == ("ready_label", "review_state")


def test_names_no_team_tracker_key_when_hub_sets_none() -> None:
    assert _view(a_hub_document()).tracker.team_set == ()


def test_names_blocked_label_and_started_state_when_hub_sets_them() -> None:
    document = a_hub_document()
    document["tracker"] = {
        **document["tracker"],
        "blocked_label": "stuck",
        "states": {"started": "Doing"},
    }

    assert _view(document).tracker.team_set == ("blocked_label", "started_state")


def test_lists_team_and_own_environments_with_their_source() -> None:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "write"}}
    document["repos"][0]["services"] = {
        "api": {"kind": "api", "endpoints": {"staging": {"url": "https://staging.example.com"}}}
    }
    local = LocalConfig.model_validate(
        {
            "environments": {"staging": {"access": "read"}, "mine": {"access": "write"}},
            "repos": [
                {
                    "dir": "demo-api",
                    "services": {"api": {"endpoints": {"mine": {"url": "http://localhost:8000"}}}},
                }
            ],
        }
    )

    environments = _view(document, local).environments

    assert [(e.name, e.access, e.source) for e in environments.environments] == [
        ("staging", "read", "hub.local.json"),
        ("mine", "write", "hub.local.json"),
    ]
    assert [(e.environment, e.source) for e in environments.services[0].endpoints] == [
        ("staging", "hub.json"),
        ("mine", "hub.local.json"),
    ]


def test_shows_only_team_environments_when_local_one_loosens_access() -> None:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "read"}}
    local = LocalConfig.model_validate({"environments": {"staging": {"access": "write"}}})

    view = _view(document, local)

    assert [(e.name, e.access) for e in view.environments.environments] == [("staging", "read")]
    assert view.local_file.problems == (
        "environments.staging.access: may only tighten hub.json's read",
    )
