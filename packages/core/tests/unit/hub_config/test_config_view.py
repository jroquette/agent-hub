from collections.abc import Mapping
from typing import Any

from agent_hub.core.hub_config.config_view import hub_config_view
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.builders import a_hub_document


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


def test_local_identity_wins_over_the_team_file() -> None:
    local = LocalConfig.model_validate({"project": {"author_email": "me@example.com"}})

    view = _view(a_hub_document(), local)

    assert (view.author_email.value, view.author_email.source) == ("me@example.com", "local")
    assert view.author_email.where == "hub.local.json → project.author_email"


def test_identity_falls_back_to_git_and_derives_the_prefix() -> None:
    document = a_hub_document()
    for key in ("author_name", "author_email", "branch_prefix"):
        del document["project"][key]

    view = _view(document, read_git=_git)

    assert (view.author_name.source, view.author_name.where) == ("git", "git config user.name")
    assert (view.branch_prefix.value, view.branch_prefix.source) == ("git.person/", "derived")


def test_an_unconfigured_repo_shows_the_built_in_conventions_with_examples() -> None:
    repo = _view(a_hub_document()).repos[0]

    assert repo.commit_title.source == "default"
    assert repo.commit_title.example == "feat(api): add the hub config view (DEM-42)"
    assert repo.branch.example == "jdoe/dem-42-hub-config"
    assert repo.pr_title.source == "commit_title"


def test_a_repo_override_wins_over_the_project_conventions() -> None:
    document = a_hub_document()
    document["project"]["conventions"] = {"commit_title": "{type}: {summary}"}
    document["repos"][0]["conventions"] = {"commit_title": "[{ISSUE}] {summary}"}

    view = _view(document)

    assert view.conventions[1].source == "project"
    assert view.repos[0].commit_title.source == "repo"
    assert view.repos[0].commit_title.where == "hub.json → repos[0].conventions.commit_title"
    assert view.repos[0].commit_title.example == "[DEM-42] add the hub config view"


def test_default_branch_says_whether_the_repo_or_the_project_sets_it() -> None:
    document = a_hub_document()
    document["repos"][0]["default_branch"] = "develop"

    view = _view(document)

    assert view.default_branch.source == "default"
    assert (view.repos[0].default_branch.value, view.repos[0].default_branch.source) == (
        "develop",
        "team",
    )


def test_blocked_words_keep_the_team_and_local_layers_apart() -> None:
    document = a_hub_document()
    document["guard"]["blocked_words"] = ["acme-prod"]
    local = LocalConfig.model_validate({"guard": {"blocked_words": ["my-client"]}})

    guard = _view(document, local).guard

    assert guard.blocked_words.team == ("acme-prod",)
    assert guard.blocked_words.local == ("my-client",)


def test_an_invalid_local_file_is_reported_and_ignored() -> None:
    problems = (ConfigProblem("project.author_email", "not an email"),)

    view = _view(a_hub_document(), problems)

    assert view.local_file.problems == ("project.author_email: not an email",)
    assert view.author_email.source == "team"
