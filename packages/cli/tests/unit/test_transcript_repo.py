import json
from pathlib import Path

import pytest

from agent_hub.cli.transcript_repo import first_cwd, repo_of


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    folder = tmp_path / "work" / "demo-hub"
    folder.mkdir(parents=True)
    document = {"project": {"name": "demo"}, "repos": [{"dir": "demo-api"}, {"dir": "../x"}]}
    (folder / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    return folder


def test_finds_repo_when_cwd_in_repo_checkout(hub: Path) -> None:
    assert repo_of(str(hub.parent / "demo-api" / "src"), hub) == "demo-api"


def test_finds_repo_when_cwd_in_repo_worktree(hub: Path) -> None:
    worktree = hub.parent / "demo-api" / ".claude" / "worktrees" / "dem-7-export"

    assert repo_of(str(worktree), hub) == "demo-api"


def test_uses_main_checkout_when_hub_root_is_hub_worktree(hub: Path) -> None:
    worktree = hub / ".claude" / "worktrees" / "dem-8"
    worktree.mkdir(parents=True)
    (worktree / "hub.json").write_text("{}", encoding="utf-8")

    assert repo_of(str(hub.parent / "demo-api"), worktree) == "demo-api"


def test_finds_no_repo_when_cwd_outside_repos(hub: Path) -> None:
    assert repo_of(str(hub), hub) is None
    assert repo_of(str(hub.parent / "other"), hub) is None
    assert repo_of(None, hub) is None


def test_finds_no_repo_when_hub_json_unreadable(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text("[not json", encoding="utf-8")

    assert repo_of(str(tmp_path / "demo-api"), hub) is None


def test_takes_first_cwd_when_lines_name_one() -> None:
    text = "\n".join(["not json", json.dumps({"type": "summary"}), json.dumps({"cwd": "/w/a"})])

    assert first_cwd(text) == "/w/a"
    assert first_cwd("[1]\n") is None
