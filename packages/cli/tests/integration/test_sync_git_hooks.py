"""AGH-835 (ADR 0061): ``hub sync`` turns on the hub's ``.githooks`` through ``core.hooksPath``."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from agent_hub.cli.git_hooks_path import SET_LINE

type SyncRunner = Callable[..., Result]


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    found = shutil.which("git")
    assert found is not None
    return subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
        [found, *arguments], cwd=root, capture_output=True, text=True, check=False, timeout=30
    )


def hooks_path(root: Path) -> str:
    return git(root, "config", "--local", "--get", "core.hooksPath").stdout.strip()


@pytest.fixture
def git_hub(demo_hub: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    assert git(demo_hub, "init", "-q").returncode == 0
    return demo_hub


def test_sets_hooks_path_when_unset(git_hub: Path, run_sync: SyncRunner) -> None:
    result = run_sync(git_hub)

    assert result.exit_code == 0, result.stderr
    assert SET_LINE in result.stdout.splitlines()
    assert hooks_path(git_hub) == ".githooks"


def test_replaces_git_default_when_pre_commit_installed(
    git_hub: Path, run_sync: SyncRunner
) -> None:
    assert git(git_hub, "config", "core.hooksPath", ".git/hooks").returncode == 0

    result = run_sync(git_hub)

    assert result.exit_code == 0, result.stderr
    assert hooks_path(git_hub) == ".githooks"


def test_prints_nothing_when_hooks_path_already_set(git_hub: Path, run_sync: SyncRunner) -> None:
    assert git(git_hub, "config", "core.hooksPath", ".githooks").returncode == 0

    result = run_sync(git_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")


def test_keeps_foreign_hooks_path_with_warning_when_set(
    git_hub: Path, run_sync: SyncRunner
) -> None:
    assert git(git_hub, "config", "core.hooksPath", ".husky").returncode == 0

    result = run_sync(git_hub)

    assert result.exit_code == 0
    assert hooks_path(git_hub) == ".husky"
    assert "warning: git hooks: core.hooksPath is '.husky'" in result.stderr


def test_sets_nothing_when_checked(git_hub: Path, run_sync: SyncRunner) -> None:
    result = run_sync(git_hub, "--check")

    assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
    assert hooks_path(git_hub) == ""


def test_prints_nothing_when_hub_not_git_repository(demo_hub: Path, run_sync: SyncRunner) -> None:
    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
