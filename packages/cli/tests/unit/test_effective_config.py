import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path

import pytest
import typer

from agent_hub.cli import effective_config
from agent_hub.cli.effective_config import (
    EffectiveConfig,
    branch_prefix_or_lines,
    effective_or_problems,
    git_identity_reader,
    load_effective_config_or_exit,
)
from agent_hub.cli.git_defaults import GitDefaults
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

NO_PREFIX = [
    "no branch prefix for this developer; set one of:",
    "  hub.local.json → project.branch_prefix",
    "  hub.json → project.branch_prefix",
    "  git config user.email in the hub (its local part plus /)",
]


def a_hub(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    document = a_hub_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (folder / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def write_local(folder: Path, document: object) -> None:
    (folder / "hub.local.json").write_text(json.dumps(document), encoding="utf-8")


def a_config(**project: str | None) -> HubConfig:
    """The builders' config, its ``project`` keys replaced (``None`` unsets one, unvalidated)."""
    config = HubConfig.model_validate(a_hub_document())
    return config.model_copy(update={"project": config.project.model_copy(update=project)})


class GitSpy:
    """Replaces ``read_git_defaults``: records each call, answers ``values`` and ``problems``."""

    def __init__(
        self, values: dict[str, str] | None = None, problems: dict[str, str] | None = None
    ) -> None:
        self.values = values or {}
        self.problems = problems or {}
        self.calls: list[tuple[frozenset[str], Path]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(
        self, *, missing: frozenset[str], target: Path, env: Mapping[str, str]
    ) -> GitDefaults:
        self.calls.append((missing, target))
        self.envs.append(dict(env))
        return GitDefaults(
            values={key: value for key, value in self.values.items() if key in missing},
            problems={key: value for key, value in self.problems.items() if key in missing},
        )


def spy_git(monkeypatch: pytest.MonkeyPatch, spy: GitSpy) -> GitSpy:
    monkeypatch.setattr(effective_config, "read_git_defaults", spy)
    return spy


def test_merges_local_transport_when_effective_config_loaded(tmp_path: Path) -> None:
    hub = a_hub(tmp_path / "hub")
    write_local(hub, {"project": {"branch_prefix": "me/"}, "tracker": {"transport": "mcp"}})

    loaded = load_effective_config_or_exit(hub)

    assert loaded.home == hub
    assert loaded.local.tracker.transport == "mcp"
    assert loaded.config.tracker.transport == "mcp"
    assert loaded.config.project.branch_prefix == "me/"
    assert loaded.config.tracker.team == a_hub_document()["tracker"]["team"]


def test_exits_with_local_lines_when_local_file_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path / "hub")
    write_local(hub, {"guard": {}})

    with pytest.raises(typer.Exit) as caught:
        load_effective_config_or_exit(hub)

    assert caught.value.exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1, lines
    assert lines[0].startswith("hub.local.json: guard: set only in hub.json"), lines


def test_reads_local_file_from_home_when_root_differs(tmp_path: Path) -> None:
    config = a_config()
    root, home = tmp_path / "root", tmp_path / "home"
    root.mkdir()
    home.mkdir()
    write_local(root, {"tracker": {"transport": "api"}})
    write_local(home, {"tracker": {"transport": "mcp"}})

    loaded = effective_or_problems(config, home=home)

    assert isinstance(loaded, EffectiveConfig)
    assert loaded.home == home
    assert loaded.config.tracker.transport == "mcp"


def test_returns_problems_when_local_file_in_home_invalid(tmp_path: Path) -> None:
    write_local(tmp_path, [])

    problems = effective_or_problems(a_config(), home=tmp_path)

    assert not isinstance(problems, EffectiveConfig)
    assert [(problem.path, problem.message) for problem in problems] == [
        ("$", "must be a JSON object")
    ]


def test_asks_git_only_for_missing_keys_when_reader_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = spy_git(monkeypatch, GitSpy(values={"author_email": "jane.doe@example.com"}))
    read_git, git_problem = git_identity_reader(tmp_path)
    write_local(tmp_path, {"project": {"author_name": "Jane Roe"}})
    loaded = effective_or_problems(a_config(branch_prefix=None, author_email=None), home=tmp_path)
    assert isinstance(loaded, EffectiveConfig)

    assert read_git(frozenset({"author_name"})) == {}
    assert branch_prefix_or_lines(loaded) == "jane.doe/"

    # The prefix needs the email only: the name, set in hub.local.json, is never asked.
    assert spy.calls == [
        (frozenset({"author_name"}), tmp_path),
        (frozenset({"author_email"}), tmp_path),
    ]
    assert git_problem() is None


def test_runs_no_git_when_files_set_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = spy_git(monkeypatch, GitSpy(values={"author_email": "jane.doe@example.com"}))
    write_local(tmp_path, {"project": {"branch_prefix": "me/"}})
    loaded = effective_or_problems(a_config(branch_prefix=None), home=tmp_path)
    assert isinstance(loaded, EffectiveConfig)

    (tmp_path / "hub.local.json").unlink()
    from_hub = effective_or_problems(a_config(), home=tmp_path)
    assert isinstance(from_hub, EffectiveConfig)

    assert branch_prefix_or_lines(loaded) == "me/"
    assert branch_prefix_or_lines(from_hub) == "jdoe/"
    assert from_hub.local == LocalConfig()
    assert spy.calls == []


@pytest.mark.parametrize(
    ("git", "extra"),
    [
        (GitSpy(), []),
        (
            GitSpy(values={"author_email": "j+x@example.com"}),
            ['  git\'s user.email gives "j+x", not a valid prefix'],
        ),
        (
            GitSpy(values={"author_email": "not an email"}),
            ["  git's user.email is not an email address"],
        ),
        (GitSpy(problems={"author_email": "git timed out"}), ["  git: git timed out"]),
    ],
    ids=["no-email", "bad-local-part", "bad-email", "git-problem"],
)
def test_returns_lines_when_no_source_sets_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, git: GitSpy, extra: list[str]
) -> None:
    spy = spy_git(monkeypatch, git)
    loaded = effective_or_problems(a_config(branch_prefix=None, author_email=None), home=tmp_path)
    assert isinstance(loaded, EffectiveConfig)

    assert branch_prefix_or_lines(loaded) == NO_PREFIX + extra
    assert spy.calls == [(frozenset({"author_email"}), tmp_path)]


def test_uses_given_reader_when_one_passed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = spy_git(monkeypatch, GitSpy())
    loaded = effective_or_problems(a_config(branch_prefix=None, author_email=None), home=tmp_path)
    assert isinstance(loaded, EffectiveConfig)
    asked: list[frozenset[str]] = []

    def read_git(keys: frozenset[str]) -> dict[str, str]:
        asked.append(keys)
        return {"author_email": "jane@example.com"}

    assert branch_prefix_or_lines(loaded, read_git=read_git) == "jane/"
    assert asked == [frozenset({"author_email"})]
    assert spy.calls == []


def a_repo_with_email(folder: Path, email: str) -> Path:
    git = shutil.which("git")
    assert git is not None, "git is needed for a real repo"
    folder.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", email]):
        subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
            [os.path.abspath(git), *args], cwd=folder, env=dict(os.environ), check=True
        )
    return folder


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_COMMON_DIR"])
def test_reads_home_email_when_git_location_variable_names_other_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, variable: str
) -> None:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    home = a_repo_with_email(tmp_path / "home", "jane@example.com")
    other = a_repo_with_email(tmp_path / "other", "jane.doe@example.com")
    monkeypatch.setenv(variable, str(other / ".git"))
    read_git, git_problem = git_identity_reader(home)

    assert read_git(frozenset({"author_email"})) == {"author_email": "jane@example.com"}
    assert git_problem() is None


def test_hides_tokens_and_git_location_when_git_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.setenv(name, "x")
    spy = spy_git(monkeypatch, GitSpy())
    read_git, _ = git_identity_reader(tmp_path)

    read_git(frozenset({"author_email"}))

    assert len(spy.envs) == 1
    hidden = {"LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN", "GIT_DIR", "GIT_WORK_TREE"}
    assert hidden.isdisjoint(spy.envs[0])
    assert spy.envs[0]["GIT_OPTIONAL_LOCKS"] == "0"
