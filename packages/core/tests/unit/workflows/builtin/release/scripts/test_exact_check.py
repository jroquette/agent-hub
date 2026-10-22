"""The release pack's ``exact_check.py`` (AGH-494), in process: the check on the commit."""

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
    str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/exact_check.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.exact_check"


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


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_release(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("one\n")
    (repo / ".gitignore").write_text("build/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "chore(repo): release 0.21.0 (AGH-9)")
    return repo, git(repo, "rev-parse", "HEAD")


def run(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    command: str,
    sha: str,
) -> dict[str, Any]:
    monkeypatch.chdir(repo)
    assert load().main([command, "--sha", sha]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_passes_when_check_green_on_release_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_release(tmp_path)

    found = run(repo, monkeypatch, capsys, command="mkdir -p build && echo gates green", sha=sha)

    assert (found["sha"], found["passed"], found["exit_code"]) == (sha, True, 0)
    assert found["problem"] == ""
    assert found["tail"].strip() == "gates green"
    assert Path(found["log"]).read_text().strip() == "gates green"


def test_keeps_tail_and_log_when_check_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    repo, sha = a_release(tmp_path)
    command = "for n in $(seq 1 3000); do echo line-$n; done; exit 3"

    found = run(repo, monkeypatch, capsys, command=command, sha=sha)

    assert (found["passed"], found["exit_code"]) == (False, 3)
    assert len(found["tail"]) <= module.TAIL_CHARS == 4000
    assert found["tail"].rstrip().endswith("line-3000")
    log = Path(found["log"])
    assert log.is_file()
    assert not log.is_relative_to(repo)
    assert log.read_text().startswith("line-1\n")
    assert "exited 3" in found["problem"]


def test_refuses_when_head_is_not_release_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_release(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "later")
    monkeypatch.chdir(repo)

    assert load().main(["touch ran", "--sha", sha]) == 1
    assert "not the release commit" in capsys.readouterr().err
    assert not (repo / "ran").exists()


def test_refuses_when_worktree_has_untracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_release(tmp_path)
    (repo / "stray.txt").write_text("x")
    monkeypatch.chdir(repo)

    assert load().main(["touch ran", "--sha", sha]) == 1
    assert "stray.txt" in capsys.readouterr().err
    assert not (repo / "ran").exists()


def test_fails_when_check_changes_tracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_release(tmp_path)

    found = run(repo, monkeypatch, capsys, command="echo two >> tracked.txt", sha=sha)

    assert (found["passed"], found["exit_code"]) == (False, 0)
    assert "tracked.txt" in found["problem"]


def test_fails_when_check_moves_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, sha = a_release(tmp_path)
    command = "git -c user.name=T -c user.email=t@e commit -q --allow-empty -m x"

    found = run(repo, monkeypatch, capsys, command=command, sha=sha)

    assert found["passed"] is False
    assert "HEAD" in found["problem"]


@pytest.mark.parametrize("sha", ["abc", "G" * 40])
def test_exits_two_when_sha_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, sha: str
) -> None:
    repo, _ = a_release(tmp_path)
    monkeypatch.chdir(repo)

    assert load().main(["true", "--sha", sha]) == 2
