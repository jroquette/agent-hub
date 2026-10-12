from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
)
from agent_hub.hub_git.git_runner import (
    GIT_LOCATION_VARIABLES,
    Deadline,
    GitRunner,
    ProcessResult,
    child_env,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class RecordingLauncher:
    """Answers every child with ``result`` and records what it was given."""

    def __init__(self, result: ProcessResult | Exception) -> None:
        self.result = result
        self.argv: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.timeouts: list[float] = []
        self.kept: list[bool] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        del cwd
        self.argv.append(list(argv))
        self.envs.append(dict(env))
        self.timeouts.append(timeout)
        self.kept.append(keep_stdout)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _tools(tmp_path: Path) -> str:
    for name in ("git", "gh"):
        tool = tmp_path / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    return str(tmp_path)


def test_drops_git_location_when_env_built() -> None:
    environ = {name: "/elsewhere" for name in GIT_LOCATION_VARIABLES} | {
        "PATH": "/usr/bin",
        "HOME": "/home/demo",
    }

    env = child_env(environ)

    assert not set(GIT_LOCATION_VARIABLES) & set(env)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/demo"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GH_PROMPT_DISABLED"] == "1"
    assert env["GIT_LITERAL_PATHSPECS"] == "1"


def test_drops_askpass_helpers_when_env_built() -> None:
    environ = {"PATH": "/usr/bin", "GIT_ASKPASS": "/bin/ask", "SSH_ASKPASS": "/bin/ask"}

    env = child_env(environ)

    assert "GIT_ASKPASS" not in env
    assert "SSH_ASKPASS" not in env
    assert env["SSH_ASKPASS_REQUIRE"] == "never"


def test_runs_gh_without_git_options_when_gh_called(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    runner.start().gh(["auth", "status"], cwd=tmp_path, step="auth")

    assert launcher.argv == [[str(tmp_path / "gh"), "auth", "status"]]


def test_counts_down_when_deadline_runs() -> None:
    clock = FakeClock()
    deadline = Deadline(60.0, clock=clock)
    clock.now += 45.0

    assert deadline.remaining() == pytest.approx(15.0)


def test_raises_timeout_when_deadline_spent() -> None:
    clock = FakeClock()
    deadline = Deadline(1.0, clock=clock)
    clock.now += 1.0

    with pytest.raises(ChangeRequestTimeoutError):
        deadline.remaining()


def test_runs_git_with_absolute_program_when_found(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b"ok\n"))
    runner = GitRunner(environ={"PATH": _tools(tmp_path), "GIT_DIR": "/x"}, launch=launcher)

    result = runner.start().git(["status"], cwd=tmp_path, step="status")

    assert result.stdout == b"ok\n"
    assert launcher.argv == [[str(tmp_path / "git"), "-c", "core.askPass=", "status"]]
    assert "GIT_DIR" not in launcher.envs[0]
    assert 0 < launcher.timeouts[0] <= 60.0


def test_adds_extra_env_when_given(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    runner.start().git(
        ["commit-tree"], cwd=tmp_path, step="commit", extra_env={"GIT_AUTHOR_NAME": "Demo"}
    )

    assert launcher.envs[0]["GIT_AUTHOR_NAME"] == "Demo"


def test_raises_failed_step_when_child_exits_nonzero(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=1, stdout=b"secret-ish output"))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    with pytest.raises(ChangeRequestFailedError) as failed:
        runner.start().gh(["pr", "create"], cwd=tmp_path, step="pr")

    assert failed.value.step == "pr"
    assert "secret" not in str(failed.value)


def test_returns_result_when_check_disabled(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=1, stdout=b""))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    result = runner.start().git(["cat-file", "-e", "x"], cwd=tmp_path, step="x", check=False)

    assert result.returncode == 1


def test_discards_stdout_when_not_kept(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    runner.start().gh(["auth", "token"], cwd=tmp_path, step="auth", keep_stdout=False)

    assert launcher.kept == [False]


def test_raises_failed_step_when_tool_missing(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    runner = GitRunner(environ={"PATH": str(tmp_path)}, launch=launcher)

    with pytest.raises(ChangeRequestFailedError) as failed:
        runner.start().git(["status"], cwd=tmp_path, step="status")

    assert failed.value.step == "status"
    assert launcher.argv == []


def test_reports_tool_missing_when_not_on_path(tmp_path: Path) -> None:
    runner = GitRunner(environ={"PATH": str(tmp_path)})

    assert runner.program("git") is None
    assert runner.program("gh") is None


def test_raises_failed_step_when_child_cannot_start(tmp_path: Path) -> None:
    launcher = RecordingLauncher(PermissionError(13, "denied"))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    with pytest.raises(ChangeRequestFailedError) as failed:
        runner.start().git(["status"], cwd=tmp_path, step="status")

    assert failed.value.step == "status"


def test_raises_timeout_when_child_times_out(tmp_path: Path) -> None:
    launcher = RecordingLauncher(TimeoutError("git"))
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher)

    with pytest.raises(ChangeRequestTimeoutError):
        runner.start().git(["fetch"], cwd=tmp_path, step="fetch")


def test_raises_timeout_without_running_when_deadline_spent(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    clock = FakeClock()
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher, clock=clock)
    session = runner.start()
    clock.now += 61.0

    with pytest.raises(ChangeRequestTimeoutError):
        session.git(["status"], cwd=tmp_path, step="status")
    assert launcher.argv == []


def test_gives_cleanup_its_own_budget_when_action_deadline_spent(tmp_path: Path) -> None:
    launcher = RecordingLauncher(ProcessResult(returncode=0, stdout=b""))
    clock = FakeClock()
    runner = GitRunner(environ={"PATH": _tools(tmp_path)}, launch=launcher, clock=clock)
    runner.start()
    clock.now += 61.0

    runner.start(seconds=5.0).git(["push"], cwd=tmp_path, step="delete")

    assert launcher.timeouts == [pytest.approx(5.0)]
