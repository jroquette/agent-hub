import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import typer

from agent_hub.cli import hub_root
from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.hub_root import (
    HUB_ROOT_VARIABLE,
    NOT_A_HUB_EXIT,
    hub_root_or_exit,
    local_home,
    main_checkout,
)


def a_hub(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "hub.json").write_bytes(b"{}\n")
    return path


def git_environ(tmp_path: Path) -> dict[str, str]:
    """Git reads only this test's home and config, and finds no repo above ``tmp_path``."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }


def found_git() -> str:
    git = shutil.which("git")
    assert git is not None, "git is needed for a real checkout"
    return os.path.abspath(git)


def run_git(root: Path, environ: dict[str, str], *args: str) -> None:
    author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [found_git(), *author, "-c", "commit.gpgsign=false", *args],
        cwd=root,
        env=environ,
        check=True,
        capture_output=True,
    )


def a_git_hub(path: Path, environ: dict[str, str]) -> Path:
    a_hub(path)
    run_git(path, environ, "-c", "init.defaultBranch=main", "init", "-q")
    run_git(path, environ, "add", "-A")
    run_git(path, environ, "commit", "-q", "-m", "init")
    return path


def test_uses_variable_when_agent_hub_root_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = a_hub(tmp_path / "hub")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert hub_root_or_exit({HUB_ROOT_VARIABLE: str(hub)}, command="worktree") == hub.resolve()


def test_uses_real_path_when_variable_names_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = a_hub(tmp_path / "hub")
    link = tmp_path / "link"
    link.symlink_to(hub)
    monkeypatch.chdir(tmp_path)

    assert hub_root_or_exit({HUB_ROOT_VARIABLE: str(link)}, command="worktree") == hub.resolve()


def test_resolves_against_cwd_when_variable_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = a_hub(tmp_path / "hub")
    monkeypatch.chdir(tmp_path)

    assert hub_root_or_exit({HUB_ROOT_VARIABLE: "hub"}, command="worktree") == hub.resolve()


def test_uses_cwd_when_variable_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = a_hub(tmp_path / "hub")
    monkeypatch.chdir(hub)

    assert hub_root_or_exit({HUB_ROOT_VARIABLE: ""}, command="worktree") == hub.resolve()
    assert hub_root_or_exit({}, command="worktree") == hub.resolve()


def test_exits_two_when_root_has_no_hub_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "plain"
    root.mkdir()

    with pytest.raises(typer.Exit) as raised:
        hub_root_or_exit({HUB_ROOT_VARIABLE: str(root)}, command="brief")

    assert raised.value.exit_code == NOT_A_HUB_EXIT == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"{root.resolve()}: not a hub: no hub.json in this folder"
        " (hub brief runs in the hub folder or through ./hub)\n"
    )


def test_finds_main_checkout_when_root_is_hub_worktree(tmp_path: Path) -> None:
    environ = git_environ(tmp_path)
    hub = a_git_hub(tmp_path / "hub", environ)
    worktree = hub / ".claude" / "worktrees" / "x"
    run_git(hub, environ, "worktree", "add", "-q", "-b", "x", str(worktree))
    # A location variable set by the caller must not change which repo git reads.
    decoy = environ | {"GIT_DIR": str(tmp_path / "decoy"), "GIT_COMMON_DIR": str(tmp_path)}

    assert main_checkout(worktree, git=found_git(), environ=decoy) == hub.resolve()
    assert main_checkout(hub, git=found_git(), environ=decoy) == hub.resolve()


def test_keeps_root_when_worktree_of_bare_repo(tmp_path: Path) -> None:
    environ = git_environ(tmp_path)
    hub = a_git_hub(tmp_path / "hub", environ)
    bare = tmp_path / "bare.git"
    run_git(tmp_path, environ, "clone", "-q", "--bare", str(hub), str(bare))
    worktree = tmp_path / "from-bare"
    run_git(bare, environ, "worktree", "add", "-q", "-b", "x", str(worktree))

    # Its git data is a bare repo, not the .git folder of a checkout: no main checkout to take.
    assert main_checkout(worktree, git=found_git(), environ=environ) == worktree


def test_keeps_root_when_hub_not_git(tmp_path: Path) -> None:
    hub = a_hub(tmp_path / "hub")

    assert main_checkout(hub, git=found_git(), environ=git_environ(tmp_path)) == hub


def test_keeps_root_when_hub_inside_another_repo(tmp_path: Path) -> None:
    environ = git_environ(tmp_path)
    outer = a_git_hub(tmp_path / "outer", environ)
    hub = a_hub(outer / "nested-hub")

    assert main_checkout(hub, git=found_git(), environ=environ) == hub


def test_keeps_caller_group_when_main_checkout_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E6: the read stays in the caller's process group, said explicitly, not by default."""
    environ = git_environ(tmp_path)
    hub = a_git_hub(tmp_path / "hub", environ)
    calls: list[dict[str, Any]] = []

    def spy(argv: list[str], **options: Any) -> ChildResult:
        calls.append(options)
        return run_child(argv, **options)

    monkeypatch.setattr(hub_root, "run_child", spy)

    assert main_checkout(hub, git=found_git(), environ=environ) == hub.resolve()
    assert [call.get("own_session", "unset") for call in calls] == [False]
    assert calls[0]["timeout"] is None


def refuse_child(argv: list[str], **options: Any) -> ChildResult:
    raise AssertionError(f"no child expected: {argv}")


def test_returns_root_without_git_when_root_has_no_git_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hub_root, "run_child", refuse_child)
    plain = a_hub(tmp_path / "plain")
    checkout = a_hub(tmp_path / "checkout")
    (checkout / ".git").mkdir()

    assert local_home(plain, environ=git_environ(tmp_path)) == plain
    assert local_home(checkout, environ=git_environ(tmp_path)) == checkout


def test_returns_main_checkout_when_root_is_hub_worktree(tmp_path: Path) -> None:
    environ = git_environ(tmp_path)
    hub = a_git_hub(tmp_path / "hub", environ)
    worktree = hub / ".claude" / "worktrees" / "x"
    run_git(hub, environ, "worktree", "add", "-q", "-b", "x", str(worktree))

    assert local_home(worktree, environ=environ) == hub.resolve()


def test_returns_root_when_git_cannot_run(tmp_path: Path) -> None:
    environ = git_environ(tmp_path)
    hub = a_git_hub(tmp_path / "hub", environ)
    worktree = hub / ".claude" / "worktrees" / "x"
    run_git(hub, environ, "worktree", "add", "-q", "-b", "x", str(worktree))

    assert local_home(worktree, environ=environ | {"PATH": str(tmp_path / "empty")}) == worktree
