"""The release pack's ``hub_branch.py`` (AGH-494), in process: the hub worktree, its target."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/hub_branch.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.hub_branch"


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


PROJECT = {"hub_repo": "acme/demo-hub", "default_branch": "trunk", "branch_prefix": "jdoe/"}
ARGS = ["--issue", "AGH-9", "--slug", "bump-platform"]


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_hub(tmp_path: Path, project: dict[str, Any] | None = None) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text(json.dumps({"project": PROJECT if project is None else project}))
    return hub


def a_git_hub(tmp_path: Path) -> Path:
    hub = a_hub(tmp_path)
    (hub / ".gitignore").write_text(".claude/worktrees/\n")
    git(hub, "init", "-q", "-b", "trunk")
    git(hub, "add", ".")
    git(hub, "commit", "-qm", "base")
    git(hub, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    return hub


def test_builds_hub_target_when_config_complete(tmp_path: Path) -> None:
    hub = tmp_path / "hub"

    found = load().target_for(
        hub=hub,
        issue="AGH-9",
        slug="bump-platform",
        prefix="jdoe/",
        default_branch="trunk",
        github="acme/demo-hub",
        base="f" * 40,
    )

    path = str(hub / ".claude/worktrees/agh-9-bump-platform")
    assert found == {
        "path": path,
        "branch": "jdoe/agh-9-bump-platform",
        "base": "f" * 40,
        "target": {
            "path": path,
            "branch": "jdoe/agh-9-bump-platform",
            "base": "f" * 40,
            "default_branch": "trunk",
            "github": "acme/demo-hub",
            "gate": "hub workflow release, AGH-9: the hub change approved at its gate",
            "conventions": {
                "branch": "",
                "commit_title": "",
                "pr_title": "",
                "titles_configured": False,
                "pr_title_explicit": False,
            },
        },
    }


def test_reads_prefix_from_hub_json_when_no_local_file(tmp_path: Path) -> None:
    hub = a_hub(tmp_path, PROJECT | {"branch_prefix": "ana/"})

    assert load().read_config(hub).prefix == "ana/"


def test_prefers_local_prefix_when_hub_local_json_sets_one(tmp_path: Path) -> None:
    hub = a_hub(tmp_path)
    (hub / "hub.local.json").write_text(json.dumps({"project": {"branch_prefix": "ana/"}}))

    assert load().read_config(hub).prefix == "ana/"


@pytest.mark.parametrize("text", ["{", "[1]", '{"project": []}', "x" * (1024 * 1024 + 1)])
def test_exits_two_when_hub_json_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    text: str,
) -> None:
    hub = a_hub(tmp_path)
    (hub / "hub.json").write_text(text)
    monkeypatch.chdir(hub)

    assert load().main(ARGS) == 2
    assert capsys.readouterr().err.startswith("hub_branch.py: hub.json: ")


@pytest.mark.parametrize(
    "project",
    [
        {"hub_repo": "acme/demo-hub", "default_branch": "trunk"},
        PROJECT | {"branch_prefix": ""},
        PROJECT | {"branch_prefix": "claude/"},
        PROJECT | {"hub_repo": "demo-hub"},
        PROJECT | {"default_branch": ""},
    ],
)
def test_exits_two_when_branch_prefix_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: dict[str, Any]
) -> None:
    monkeypatch.chdir(a_hub(tmp_path, project))

    assert load().main(ARGS) == 2


@pytest.mark.parametrize(
    ("issue", "slug"), [("AGH 9", "bump-platform"), ("AGH-9", "Bump/Platform"), ("", "x")]
)
def test_exits_two_when_issue_or_slug_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, issue: str, slug: str
) -> None:
    monkeypatch.chdir(a_hub(tmp_path))

    assert load().main(["--issue", issue, "--slug", slug]) == 2


def test_refuses_branch_when_it_equals_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = PROJECT | {"branch_prefix": "x/", "default_branch": "x/agh-9-bump-platform"}
    monkeypatch.chdir(a_hub(tmp_path, project))

    assert load().main(ARGS) == 2
    assert "the default branch" in capsys.readouterr().err


def test_reuses_worktree_when_branch_already_checked_out_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_git_hub(tmp_path)
    monkeypatch.chdir(hub)

    assert load().main(ARGS) == 0
    first = json.loads(capsys.readouterr().out)
    # A resumed run finds its worktree and reuses it.
    assert load().main(ARGS) == 0
    again = json.loads(capsys.readouterr().out)

    assert first == again
    assert first["branch"] == "jdoe/agh-9-bump-platform"
    assert first["base"] == git(hub, "rev-parse", "origin/trunk")
    assert first["target"]["github"] == "acme/demo-hub"
    assert git(Path(first["path"]), "branch", "--show-current") == first["branch"]
    assert git(hub, "branch", "--show-current") == "trunk"
    assert git(hub, "status", "--porcelain") == ""


def test_exits_one_when_origin_default_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_git_hub(tmp_path)
    git(hub, "update-ref", "-d", "refs/remotes/origin/trunk")
    monkeypatch.chdir(hub)

    assert load().main(ARGS) == 1
    assert "origin/trunk" in capsys.readouterr().err
