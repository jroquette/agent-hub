from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestConflictError,
    RefspecRefusedError,
)
from agent_hub.core.testing.builders import a_brain_change
from agent_hub.hub_git.brain_change_requests import (
    CHECK_TIMED_OUT,
    READ_ONLY,
    GitBrainChangeRequests,
)
from agent_hub.hub_git.git_runner import GitRunner, ProcessResult


class TimingOutLauncher:
    """Every child runs past its deadline; records that it was asked."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        del cwd, env, timeout, keep_stdout
        self.calls.append(list(argv))
        raise TimeoutError(argv[0])


def _adapter(tmp_path: Path, launcher: TimingOutLauncher) -> GitBrainChangeRequests:
    tool = tmp_path / "bin" / "git"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    runner = GitRunner(environ={"PATH": str(tool.parent)}, launch=launcher)
    return GitBrainChangeRequests(runner, temp_root=tmp_path)


def test_reports_check_timed_out_when_git_hangs(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, TimingOutLauncher())

    assert adapter.availability(str(tmp_path)) == CHECK_TIMED_OUT


def test_reports_read_only_when_hub_is_a_file(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.write_text("")
    launcher = TimingOutLauncher()

    assert _adapter(tmp_path, launcher).availability(str(hub)) == READ_ONLY
    assert launcher.calls == []


def test_refuses_push_before_git_when_branch_names_other_note(tmp_path: Path) -> None:
    launcher = TimingOutLauncher()
    change = a_brain_change(hub_path=str(tmp_path), branch="demo/learning-accept-other-note")

    with pytest.raises(RefspecRefusedError):
        _adapter(tmp_path, launcher).accept(change)
    assert launcher.calls == []


def test_refuses_conflict_before_git_when_destination_refused(tmp_path: Path) -> None:
    launcher = TimingOutLauncher()
    change = a_brain_change(hub_path=str(tmp_path), destination="auto/testing-x.md")

    with pytest.raises(ChangeRequestConflictError):
        _adapter(tmp_path, launcher).accept(change)
    assert launcher.calls == []


def test_refuses_conflict_before_git_when_destination_differs_from_rule(tmp_path: Path) -> None:
    launcher = TimingOutLauncher()
    change = a_brain_change(
        hub_path=str(tmp_path),
        action="reject",
        destination="_inbox/_archive/other.md",
        branch="demo/learning-reject-testing-x",
    )

    with pytest.raises(ChangeRequestConflictError, match="Destination not allowed"):
        _adapter(tmp_path, launcher).reject(change)
    assert launcher.calls == []
