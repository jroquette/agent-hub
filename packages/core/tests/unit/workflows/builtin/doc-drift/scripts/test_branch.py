"""The doc-drift pack's ``branch.py`` (AGH-491), in process: the repo worktree a run commits its
approved doc lines in, and the target ``hub step commits|pr`` read. The branch, its name and the
target's repo facts come from ``hub step config --branch doc-drift --run-slug`` (``--config``,
AGH-480); the script opens no ``hub.json``."""

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
RUN = "0a1b2c3d"
UNTITLED = {
    "branch": "",
    "commit_title": "",
    "pr_title": "",
    "titles_configured": False,
    "pr_title_explicit": False,
}
TARGET = {"github": "acme/demo-api", "default_branch": "trunk", "conventions": UNTITLED}
REPO = {"dir": "demo-api", "github": "acme/demo-api", "default_branch": "trunk", "target": TARGET}


def a_config(repo: dict[str, Any] | None = None, **top: Any) -> str:
    """What ``hub step config --branch doc-drift --run-slug`` prints for the run."""
    value = {
        "default_branch": "trunk",
        "branch_prefix": "jdoe/",
        "repos": [REPO if repo is None else repo],
        "branch_name": f"doc-drift-{RUN}",
        "branch": f"jdoe/doc-drift-{RUN}",
    }
    return json.dumps(value | top)


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


def a_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
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


def run(hub: Path, monkeypatch: pytest.MonkeyPatch, *argv: str, config: str = "") -> int:
    monkeypatch.chdir(hub)
    code: int = branch.main([*argv, "--config", config or a_config()])
    return code


def test_builds_repo_target_from_the_config_skeleton_when_config_complete(tmp_path: Path) -> None:
    repo = tmp_path / "demo-api"
    config = branch.read_config(a_config(), "demo-api")

    found = branch.target_for(repo=repo, run_id=RUN, config=config, base="f" * 40)

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
            "conventions": UNTITLED,
        },
    }


def test_takes_the_branch_the_config_prints_when_config_read() -> None:
    # hub step config resolved the prefix (hub.local.json first): the script takes it as is.
    config = branch.read_config(a_config(branch=f"ana/doc-drift-{RUN}"), "demo-api")

    assert config.branch == f"ana/doc-drift-{RUN}"
    assert config.name == f"doc-drift-{RUN}"


def test_reads_repo_branch_from_its_target_when_config_read() -> None:
    target = TARGET | {"default_branch": "main"}

    config = branch.read_config(a_config(REPO | {"target": target}), "demo-api")

    assert config.default_branch == "main"


def test_reads_no_hub_json_when_config_given(tmp_path: Path) -> None:
    hub = a_hub(tmp_path)
    (hub / "hub.json").write_text(json.dumps({"repos": []}))

    assert branch.read_config(a_config(), "demo-api").target["github"] == "acme/demo-api"


@pytest.mark.parametrize(
    "config",
    [
        "not json",
        a_config(REPO | {"dir": "other"}),
        a_config(REPO | {"target": TARGET | {"github": "demo-api"}}),
        a_config(REPO | {"target": "x"}),
        a_config(branch=""),
        a_config(branch=f"claude/doc-drift-{RUN}"),
        a_config(branch_name="../up"),
        json.dumps({"repos": [REPO]}),
    ],
    ids=["text", "no-repo", "github", "target", "no-branch", "claude", "name", "no-branch-keys"],
)
def test_exits_two_when_config_is_unusable(
    config: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hub = a_hub(tmp_path)

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40, config=config) == 2
    assert capsys.readouterr().err.startswith("branch.py: the config: ")


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
    hub = a_hub(tmp_path)
    target = TARGET | {"default_branch": f"x/doc-drift-{RUN}"}
    config = a_config(REPO | {"target": target}, branch=f"x/doc-drift-{RUN}")

    assert run(hub, monkeypatch, "--repo", "demo-api", "--base", "f" * 40, config=config) == 2
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
