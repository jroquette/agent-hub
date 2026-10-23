"""The doc-drift pack's ``branch.py`` (AGH-491), in process: the repo worktree a run commits its
approved doc lines in, and the target ``hub step commits|pr`` read."""

import importlib.util
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/doc-drift/scripts/branch.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.doc-drift.scripts.branch"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


branch = load()
PROJECT = {"default_branch": "trunk", "branch_prefix": "jdoe/"}
REPO = {"dir": "demo-api", "github": "acme/demo-api"}
RUN = "0a1b2c3d"


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_hub(
    tmp_path: Path, project: dict[str, Any] | None = None, repo: dict[str, Any] | None = None
) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
    config = {"project": PROJECT if project is None else project, "repos": [repo or REPO]}
    (hub / "hub.json").write_text(json.dumps(config))
    return hub


def a_repo(tmp_path: Path) -> str:
    repo = tmp_path / "demo-api"
    repo.mkdir()
    (repo / ".gitignore").write_text(".claude/worktrees/\n")
    (repo / "README.md").write_text("# demo\n")
    git(repo, "init", "-q", "-b", "trunk")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    return git(repo, "rev-parse", "HEAD")


def run(hub: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(hub)
    code: int = branch.main(list(argv))
    return code


def test_builds_repo_target_when_config_complete(tmp_path: Path) -> None:
    repo = tmp_path / "demo-api"

    found = branch.target_for(
        repo=repo,
        run_id=RUN,
        prefix="jdoe/",
        default_branch="trunk",
        github="acme/demo-api",
        base="f" * 40,
    )

    path = str(repo / ".claude/worktrees/doc-drift-0a1b2c3d")
    assert found == {
        "path": path,
        "branch": "jdoe/doc-drift-0a1b2c3d",
        "base": "f" * 40,
        "target": {
            "path": path,
            "branch": "jdoe/doc-drift-0a1b2c3d",
            "base": "f" * 40,
            "default_branch": "trunk",
            "github": "acme/demo-api",
            "gate": (
                "doc-drift run 0a1b2c3d: docs-only diff check passed;"
                " every line approved at the gate"
            ),
            "conventions": {
                "branch": "",
                "commit_title": "",
                "pr_title": "",
                "titles_configured": False,
                "pr_title_explicit": False,
            },
        },
    }


def test_prefers_local_prefix_when_hub_local_json_sets_one(tmp_path: Path) -> None:
    hub = a_hub(tmp_path)
    (hub / "hub.local.json").write_text(json.dumps({"project": {"branch_prefix": "ana/"}}))

    assert branch.read_config(hub, "demo-api").prefix == "ana/"


def test_reads_repo_branch_when_repo_sets_its_own(tmp_path: Path) -> None:
    hub = a_hub(tmp_path, repo=REPO | {"default_branch": "main"})

    assert branch.read_config(hub, "demo-api").default_branch == "main"


@pytest.mark.parametrize(
    ("project", "repo"),
    [
        ({"default_branch": "trunk"}, REPO),
        (PROJECT | {"branch_prefix": ""}, REPO),
        (PROJECT | {"branch_prefix": "claude/"}, REPO),
        (PROJECT, REPO | {"github": "demo-api"}),
        (PROJECT, REPO | {"dir": "other"}),
    ],
)
def test_exits_two_when_branch_prefix_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    project: dict[str, Any],
    repo: dict[str, Any],
) -> None:
    hub = a_hub(tmp_path, project, repo)

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40) == 2
    assert capsys.readouterr().err.startswith("branch.py: hub.json: ")


@pytest.mark.parametrize("run_id", ["", "Not/A-Run"])
def test_exits_two_when_run_id_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_id: str
) -> None:
    hub = a_hub(tmp_path)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", run_id)

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40) == 2


def test_refuses_branch_when_it_equals_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = {"branch_prefix": "x/", "default_branch": f"x/doc-drift-{RUN}"}
    hub = a_hub(tmp_path, project)

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40) == 2
    assert "the default branch" in capsys.readouterr().err


def test_reuses_worktree_when_run_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    base = a_repo(tmp_path)
    repo = tmp_path / "demo-api"

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", base) == 0
    first = json.loads(capsys.readouterr().out)
    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", base) == 0
    again = json.loads(capsys.readouterr().out)

    assert first == again
    assert first["path"] == str(repo.resolve() / ".claude/worktrees/doc-drift-0a1b2c3d")
    assert first["branch"] == "jdoe/doc-drift-0a1b2c3d"
    assert first["base"] == base
    assert git(Path(first["path"]), "rev-parse", "HEAD") == base
    assert git(Path(first["path"]), "branch", "--show-current") == first["branch"]
    assert git(repo, "branch", "--show-current") == "trunk"
    assert git(repo, "status", "--porcelain") == ""


def test_exits_two_when_base_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_hub(tmp_path)
    a_repo(tmp_path)

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40) == 2
    assert "unknown commit" in capsys.readouterr().err
