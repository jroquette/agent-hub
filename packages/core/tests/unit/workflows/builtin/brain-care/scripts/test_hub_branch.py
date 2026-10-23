"""The brain-care pack's ``hub_branch.py`` (AGH-487), in process: the hub worktree, its target.

The branch, its name and the hub's target skeleton come from ``hub step config --branch
brain-care-<workflow> --run-slug`` (``--config``, AGH-480); the script opens no ``hub.json``."""

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
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/hub_branch.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.hub_branch"


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


RUN = "0a1b2c3d"
UNTITLED = {
    "branch": "",
    "commit_title": "",
    "pr_title": "",
    "titles_configured": False,
    "pr_title_explicit": False,
}
TARGET = {"github": "acme/demo-hub", "default_branch": "trunk", "conventions": UNTITLED}


def a_config(workflow: str = "inbox", target: dict[str, Any] | None = None, **top: Any) -> str:
    """What ``hub step config --branch brain-care-<workflow> --run-slug`` prints for the run."""
    name = f"brain-care-{workflow}-{RUN}"
    hub = {"github": "acme/demo-hub", "default_branch": "trunk", "target": target or TARGET}
    value = {"default_branch": "trunk", "repos": [], "hub": hub}
    value |= {"branch_name": name, "branch": f"jdoe/{name}"}
    return json.dumps(value | top)


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


def a_git_hub(tmp_path: Path) -> Path:
    hub = a_hub(tmp_path)
    (hub / ".gitignore").write_text(".claude/worktrees/\n")
    git(hub, "init", "-q", "-b", "trunk")
    git(hub, "add", ".")
    git(hub, "commit", "-qm", "base")
    git(hub, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    return hub


def main(workflow: str, config: str = "") -> int:
    code: int = load().main(["--workflow", workflow, "--config", config or a_config(workflow)])
    return code


def test_builds_hub_target_from_the_config_skeleton_when_config_complete(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    module = load()
    config = module.read_config(a_config(), workflow="inbox", run_id=RUN)

    found = module.target_for(hub=hub, workflow="inbox", run_id=RUN, config=config, base="f" * 40)

    path = str(hub / ".claude/worktrees/brain-care-inbox-0a1b2c3d")
    assert found == {
        "path": path,
        "branch": "jdoe/brain-care-inbox-0a1b2c3d",
        "base": "f" * 40,
        "target": {
            "path": path,
            "branch": "jdoe/brain-care-inbox-0a1b2c3d",
            "base": "f" * 40,
            "default_branch": "trunk",
            "github": "acme/demo-hub",
            "gate": "hub workflow inbox, run 0a1b2c3d: every change approved at its gate",
            "conventions": UNTITLED,
        },
    }


def test_takes_the_branch_the_config_prints_when_config_read() -> None:
    # hub step config resolved the prefix (hub.local.json first): the script takes it as is.
    config = load().read_config(
        a_config(branch=f"ana/brain-care-inbox-{RUN}"), workflow="inbox", run_id=RUN
    )

    assert config.branch == f"ana/brain-care-inbox-{RUN}"


def test_reads_no_hub_json_when_config_given(tmp_path: Path) -> None:
    hub = a_hub(tmp_path)
    (hub / "hub.json").write_text(json.dumps({"project": {"hub_repo": "other/x"}}))

    config = load().read_config(a_config(), workflow="inbox", run_id=RUN)

    assert config.target["github"] == "acme/demo-hub"


@pytest.mark.parametrize(
    "config",
    [
        "{",
        "[1]",
        json.dumps({"hub": []}),
        "x" * (1024 * 1024 + 1),
        a_config(target=TARGET | {"github": "demo-hub"}),
        a_config(target=TARGET | {"default_branch": ""}),
        a_config(branch=""),
        a_config(branch=f"claude/brain-care-inbox-{RUN}"),
        a_config(branch_name=f"brain-care-context-{RUN}"),
    ],
    ids=["text", "array", "hub", "large", "github", "default", "no-branch", "claude", "other-name"],
)
def test_exits_two_when_config_is_unusable(
    config: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(a_hub(tmp_path))
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)

    assert main("inbox", config) == 2
    assert capsys.readouterr().err.startswith("hub_branch.py: the config: ")


@pytest.mark.parametrize("run_id", ["", "Not/A-Run"])
def test_exits_two_when_run_id_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_id: str
) -> None:
    monkeypatch.chdir(a_hub(tmp_path))
    monkeypatch.setenv("AGENT_HUB_RUN_ID", run_id)

    assert main("inbox") == 2


def test_refuses_branch_when_it_equals_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    name = f"brain-care-inbox-{RUN}"
    config = a_config(target=TARGET | {"default_branch": f"x/{name}"}, branch=f"x/{name}")
    monkeypatch.chdir(a_hub(tmp_path))
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)

    assert main("inbox", config) == 2
    assert "the default branch" in capsys.readouterr().err


def test_adds_worktree_on_origin_default_when_hub_is_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_git_hub(tmp_path)
    monkeypatch.chdir(hub)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)

    assert main("context") == 0
    first = json.loads(capsys.readouterr().out)
    # A resumed run finds its worktree and reuses it.
    assert main("context") == 0
    again = json.loads(capsys.readouterr().out)

    assert first == again
    assert first["branch"] == "jdoe/brain-care-context-0a1b2c3d"
    assert first["base"] == git(hub, "rev-parse", "origin/trunk")
    assert git(Path(first["path"]), "branch", "--show-current") == first["branch"]
    assert git(hub, "branch", "--show-current") == "trunk"
    assert git(hub, "status", "--porcelain") == ""


def test_exits_one_when_origin_default_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = a_git_hub(tmp_path)
    git(hub, "update-ref", "-d", "refs/remotes/origin/trunk")
    monkeypatch.chdir(hub)
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)

    assert main("inbox") == 1
    assert "origin/trunk" in capsys.readouterr().err
