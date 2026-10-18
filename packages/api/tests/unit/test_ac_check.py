"""``AcCheckRunner``: runs the command features.json records for an AC, in its repo's checkout."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent_hub.api import ac_check
from agent_hub.api.ac_check import AcCheckError, AcCheckRunner
from agent_hub.core.readmodels.read_ports import HubReadModels


def _ac(ac_id: str, command: str | None, *, manual: bool = False, repo: str | None = "app") -> Any:
    return SimpleNamespace(id=ac_id, command=command, manual=manual, repo=repo)


def _models(tmp_path: Path, *acs: Any) -> HubReadModels:
    (tmp_path / "hub").mkdir()
    (tmp_path / "app").mkdir()
    repo = SimpleNamespace(name="app", dir="app")
    return cast(
        "HubReadModels",
        SimpleNamespace(
            get_feature=lambda _p, _s: SimpleNamespace(ac_rows=acs),
            project_repos=lambda _p: SimpleNamespace(items=(repo,)),
            get_project=lambda _p: SimpleNamespace(hub_path=str(tmp_path / "hub")),
        ),
    )


def test_answers_exit_zero_and_output_when_check_passes_in_repo(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "pwd && echo ok")))

    run = runner.run("p", "f", "AC-1")

    assert run.passed
    assert run.exit_code == 0
    assert run.repo == "app"
    assert str(tmp_path / "app") in run.output
    assert "ok" in run.output
    assert run.branch is None
    assert run.commit is None


def test_names_branch_and_commit_when_check_runs(tmp_path: Path) -> None:
    models = _models(tmp_path, _ac("AC-1", "true"))
    app = tmp_path / "app"
    for argv in (
        ["init", "-q", "-b", "main"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
    ):
        subprocess.run(["git", *argv], cwd=app, check=True)  # noqa: S603, S607

    run = AcCheckRunner(models).run("p", "f", "AC-1")

    assert run.branch == "main"
    assert run.commit is not None


def test_answers_exit_code_and_stderr_when_check_fails(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "echo boom >&2; exit 3")))

    run = runner.run("p", "f", "AC-1")

    assert not run.passed
    assert run.exit_code == 3
    assert "boom" in run.output


def test_kills_check_when_past_timeout(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "sleep 5")), timeout=0.2)

    run = runner.run("p", "f", "AC-1")

    assert run.timed_out
    assert run.exit_code is None
    assert not run.passed


@pytest.mark.parametrize(
    ("ac", "status"),
    [
        (_ac("AC-1", "true", manual=True), 409),
        (_ac("AC-1", None), 409),
        (_ac("AC-1", "true", repo="other"), 409),
        (_ac("AC-9", "true"), 404),
    ],
)
def test_refuses_run_when_ac_cannot_run(tmp_path: Path, ac: Any, status: int) -> None:
    runner = AcCheckRunner(_models(tmp_path, ac))

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-1")

    assert raised.value.status == status


# AC-PG-37.1: an unknown AC is refused with its reason, and nothing runs.
def test_refuses_with_reason_when_ac_unknown(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "touch ran")))

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-9")

    assert (raised.value.status, raised.value.title, raised.value.detail) == (
        404,
        "Unknown acceptance criterion",
        "f has no AC-9.",
    )
    assert not (tmp_path / "app" / "ran").exists()


# AC-PG-37.1: a repo not checked out beside the hub (absent, or a file) is refused with its reason.
@pytest.mark.parametrize("shape", ["absent", "file"])
def test_refuses_with_reason_when_checkout_missing(tmp_path: Path, shape: str) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "touch ran")))
    (tmp_path / "app").rmdir()
    if shape == "file":
        (tmp_path / "app").write_text("not a checkout\n", encoding="utf-8")

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-1")

    assert (raised.value.status, raised.value.title, raised.value.detail) == (
        409,
        "No checkout",
        "app is not checked out beside the hub.",
    )
    assert not (tmp_path / "ran").exists()
    assert not (tmp_path / "hub" / "ran").exists()


# AC-PG-37.1: an AC naming a repo the project lacks is refused with that repo's name.
def test_refuses_with_reason_when_repo_unknown(tmp_path: Path) -> None:
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "true", repo="other")))

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-1")

    assert (raised.value.title, raised.value.detail) == (
        "Repo unknown",
        "The project has no repo other.",
    )


# AC-PG-37.1: a manual AC and one with no command answer 409 with their reasons.
@pytest.mark.parametrize(
    ("ac", "title", "detail"),
    [
        (_ac("AC-1", "true", manual=True), "Manual owner step", "AC-1 is checked by hand."),
        (_ac("AC-1", None), "No check recorded", "AC-1 records no command."),
        (_ac("AC-1", ""), "No check recorded", "AC-1 records no command."),
    ],
)
def test_refuses_with_reason_when_ac_has_no_command_to_run(
    tmp_path: Path, *, ac: Any, title: str, detail: str
) -> None:
    runner = AcCheckRunner(_models(tmp_path, ac))

    with pytest.raises(AcCheckError) as raised:
        runner.run("p", "f", "AC-1")

    assert (raised.value.status, raised.value.title, raised.value.detail) == (409, title, detail)


def test_hides_linear_key_from_check_when_parent_environment_has_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "lin" + "_api_" + "x" * 20)
    monkeypatch.setenv("AC_CHECK_MARKER", "kept")
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "env")))

    run = runner.run("p", "f", "AC-1")

    assert run.passed
    assert "AC_CHECK_MARKER=kept" in run.output.splitlines()
    assert not any(line.startswith("LINEAR_API_KEY=") for line in run.output.splitlines())


def test_keeps_output_tail_when_output_is_longer_than_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ac_check, "MAX_OUTPUT_BYTES", 8)
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", "printf 'head-0123456789-TAIL1234'")))

    run = runner.run("p", "f", "AC-1")

    assert run.truncated
    assert run.output == "TAIL1234"


def _gone(pid: int) -> bool:
    """True when ``pid`` no longer runs (absent, or a zombie nobody reaped yet)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0]
    except OSError:
        return True
    return state in {"Z", "X"}


@pytest.fixture
def escaped(tmp_path: Path) -> Iterator[Path]:
    """The pid file a check's escaped process writes; that process is killed afterwards."""
    pid_file = tmp_path / "escaped.pid"
    yield pid_file
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8"))
        if not _gone(pid):
            os.kill(pid, signal.SIGKILL)


def test_kills_background_grandchild_in_group_when_past_timeout(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    command = f"sleep 30 & echo $! > {pid_file}; sleep 30"
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", command)), timeout=0.5)

    started = time.monotonic()
    run = runner.run("p", "f", "AC-1")

    assert time.monotonic() - started < 10
    assert (run.timed_out, run.exit_code, run.passed) == (True, None, False)
    pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _gone(pid)


def test_answers_timed_out_promptly_when_escaped_process_holds_output_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, escaped: Path
) -> None:
    # A process that left the check's group keeps its stdout open after the group is killed.
    monkeypatch.setattr(ac_check, "DRAIN_SECONDS", 0.5)
    leave = (
        "import os, sys, time; os.setsid(); "
        f"open({str(escaped)!r}, 'w').write(str(os.getpid())); time.sleep(30)"
    )
    command = f'echo before; {sys.executable} -c "{leave}" & sleep 30'
    runner = AcCheckRunner(_models(tmp_path, _ac("AC-1", command)), timeout=1.0)

    started = time.monotonic()
    run = runner.run("p", "f", "AC-1")

    assert time.monotonic() - started < 10
    assert (run.timed_out, run.exit_code, run.passed) == (True, None, False)
    assert "before" in run.output
