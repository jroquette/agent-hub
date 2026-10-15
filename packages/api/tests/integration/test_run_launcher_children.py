"""hub web's run launcher starting a fake ``hub`` executable as its children (AC-213.19)."""

import fcntl
import json
import os
import signal
import stat
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.run_launcher import ProcessRunLauncher
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.launch import LaunchSpec, RunConflictError, RunLaunchError

# Records each call (a decision's stdin too); exits 3 on --abandon or decide when told to;
# sleeps when told to, ignoring SIGINT when told to as well.
FAKE_HUB = """#!{python}
import json, os, signal, sys, time
if os.environ.get("FAKE_HUB_IGNORE_INT") and "--abandon" not in sys.argv:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
with open(os.environ["FAKE_HUB_CALLS"], "a") as calls:
    calls.write(json.dumps({{
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "linear": "LINEAR_API_KEY" in os.environ,
        "root": os.environ.get("AGENT_HUB_ROOT"),
        "db": os.environ.get("AGENT_HUB_DB"),
        "stdin": sys.stdin.read() if "decide" in sys.argv else None,
    }}) + "\\n")
if "--abandon" in sys.argv or "decide" in sys.argv:
    sys.exit(3 if os.environ.get("FAKE_HUB_REFUSE") else 0)
if os.environ.get("FAKE_HUB_SLEEP"):
    time.sleep(30)
"""
SLEEP = {"FAKE_HUB_SLEEP": "1"}


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    folder = tmp_path / "hub"
    folder.mkdir()
    return folder


@pytest.fixture
def make_launcher(tmp_path: Path) -> Callable[..., ProcessRunLauncher]:
    program = tmp_path / "hub-fake"
    program.write_text(FAKE_HUB.format(python=sys.executable))
    program.chmod(0o700)

    def make(*, grace: float = 5, max_children: int = 8, **env: str) -> ProcessRunLauncher:
        environ = {
            "PATH": os.environ.get("PATH", ""),
            "FAKE_HUB_CALLS": str(tmp_path / "calls.jsonl"),
            "LINEAR_API_KEY": "lin_api_synthetic",
            **env,
        }
        return ProcessRunLauncher(
            db_path=tmp_path / "agent-hub.db",
            environ=environ,
            program=[str(program)],
            grace=grace,
            max_children=max_children,
        )

    return make


def calls(tmp_path: Path, count: int) -> list[dict[str, Any]]:
    path = tmp_path / "calls.jsonl"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        lines = path.read_text().splitlines() if path.exists() else []
        if len(lines) >= count:
            return [json.loads(line) for line in lines]
        time.sleep(0.05)
    raise AssertionError(f"fewer than {count} calls")


def gone(path: Path) -> bool:
    deadline = time.monotonic() + 10
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return not path.exists()


def spec(hub: Path, run_id: str = "run-1", **inputs: Any) -> LaunchSpec:
    return LaunchSpec(
        run_id=run_id,
        project="demo",
        hub_path=str(hub),
        workflow="fix",
        inputs=inputs,
        issue="DEM-7",
    )


def test_starts_live_cli_with_argv_and_scoped_env_when_run_launched(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    make_launcher().start(spec(hub, issue="DEM-7", tries=2, strict=True))

    [call] = calls(tmp_path, 1)
    assert call["argv"] == [
        "workflow", "run", "fix", "--run-id", "run-1", "--live",
        "--input", "issue=DEM-7", "--input", "tries=2", "--input", "strict=true",
    ]  # fmt: skip
    assert (call["cwd"], call["root"]) == (os.path.realpath(hub), str(hub))
    assert call["db"] == str((tmp_path / "agent-hub.db").resolve())
    assert call["linear"] is False
    assert gone(hub / ".agent-runs" / "web" / "run-1.pid")
    log = hub / ".agent-runs" / "web" / "run-1.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_passes_absolute_database_when_path_given_relative(
    hub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    program = tmp_path / "hub-fake"
    program.write_text(FAKE_HUB.format(python=sys.executable))
    program.chmod(0o700)
    environ = {"FAKE_HUB_CALLS": str(tmp_path / "calls.jsonl")}
    launcher = ProcessRunLauncher(db_path=Path("rel.db"), environ=environ, program=[str(program)])

    launcher.start(spec(hub))

    assert calls(tmp_path, 1)[0]["db"] == str(tmp_path.resolve() / "rel.db")


def test_keeps_owner_only_pid_file_while_child_runs_when_live(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    launcher = make_launcher(**SLEEP)
    launcher.start(spec(hub))
    calls(tmp_path, 1)
    pid_file = hub / ".agent-runs" / "web" / "run-1.pid"

    try:
        assert stat.S_IMODE(pid_file.stat().st_mode) == 0o600
        assert launcher.live_runs(str(hub)) == {"run-1": "DEM-7"}
        with pytest.raises(RunConflictError) as caught:
            launcher.resume(str(hub), "run-1", issue="DEM-7")
        assert caught.value.code == "in_use"
        assert pid_file.exists()
    finally:
        assert launcher.cancel(str(hub), "run-1")
    assert gone(pid_file)


def test_signals_group_then_abandons_when_cancelled(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    launcher = make_launcher(**SLEEP)
    launcher.start(spec(hub))
    calls(tmp_path, 1)

    assert launcher.cancel(str(hub), "run-1") is True

    abandon = calls(tmp_path, 2)[1]
    assert abandon["argv"] == ["workflow", "run", "--abandon", "run-1"]
    assert launcher.live_runs(str(hub)) == {}


def test_kills_group_then_abandons_when_child_ignores_interrupt(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    launcher = make_launcher(grace=0.5, FAKE_HUB_IGNORE_INT="1", **SLEEP)
    launcher.start(spec(hub))
    calls(tmp_path, 1)
    child = launcher._children[hub / ".agent-runs" / "web" / "run-1.pid"]  # noqa: SLF001

    assert launcher.cancel(str(hub), "run-1") is True

    abandon = calls(tmp_path, 2)[1]
    assert abandon["argv"] == ["workflow", "run", "--abandon", "run-1"]
    assert child.process.wait(timeout=10) == -signal.SIGKILL


@pytest.mark.parametrize("attempt", range(20))
def test_starts_one_child_when_two_resumes_race(
    hub: Path,
    tmp_path: Path,
    make_launcher: Callable[..., ProcessRunLauncher],
    *,
    attempt: int,
) -> None:
    launcher = make_launcher(**SLEEP)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def resume() -> None:
        barrier.wait()
        try:
            launcher.resume(str(hub), "run-1", issue=None)
            outcomes.append("started")
        except RunConflictError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=resume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert sorted(outcomes) == ["in_use", "started"], attempt
        calls(tmp_path, 1)
        time.sleep(0.2)
        assert len(calls(tmp_path, 1)) == 1
    finally:
        launcher.cancel(str(hub), "run-1")
    assert gone(hub / ".agent-runs" / "web" / "run-1.pid")


def test_refuses_start_when_too_many_children_run(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    launcher = make_launcher(max_children=1, **SLEEP)
    launcher.start(spec(hub))

    try:
        with pytest.raises(RunConflictError) as caught:
            launcher.start(spec(hub, "run-2"))
        assert caught.value.code == "too_many_runs"
    finally:
        launcher.cancel(str(hub), "run-1")
    assert len(calls(tmp_path, 1)) >= 1


def test_refuses_resume_when_cli_holds_run_lock(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    folder = hub / ".agent-runs" / "workflows" / "run-1"
    folder.mkdir(parents=True)
    descriptor = os.open(folder / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        with pytest.raises(RunConflictError) as caught:
            make_launcher().resume(str(hub), "run-1", issue=None)
    finally:
        os.close(descriptor)

    assert caught.value.code == "in_use"
    assert not (tmp_path / "calls.jsonl").exists()


def test_appends_to_log_when_run_resumed(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    folder = hub / ".agent-runs" / "web"
    folder.mkdir(parents=True)
    (folder / "run-1.log").write_text("first child\n")

    make_launcher().resume(str(hub), "run-1", issue=None)

    assert calls(tmp_path, 1)[0]["argv"] == ["workflow", "run", "--resume", "run-1"]
    assert gone(folder / "run-1.pid")
    assert (folder / "run-1.log").read_text().startswith("first child\n")


def test_replaces_link_without_following_it_when_pid_path_is_link(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    folder = hub / ".agent-runs" / "web"
    folder.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.write_text("kept")
    (folder / "run-1.pid").symlink_to(target)

    make_launcher().start(spec(hub))

    calls(tmp_path, 1)
    assert target.read_text() == "kept"


def test_waits_for_cli_when_run_abandoned(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    make_launcher().abandon(str(hub), "run-1")

    assert calls(tmp_path, 1)[0]["argv"] == ["workflow", "run", "--abandon", "run-1"]


def test_refuses_abandon_when_cli_exits_non_zero(
    hub: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    with pytest.raises(RunConflictError) as caught:
        make_launcher(FAKE_HUB_REFUSE="1").abandon(str(hub), "run-1")

    assert caught.value.code == "refused"


def test_reports_launch_error_when_program_cannot_start(hub: Path, tmp_path: Path) -> None:
    launcher = ProcessRunLauncher(
        db_path=tmp_path / "db", environ={}, program=[str(tmp_path / "missing")]
    )

    with pytest.raises(RunLaunchError):
        launcher.start(spec(hub))
    assert not (hub / ".agent-runs" / "web" / "run-1.pid").exists()


def test_passes_gate_choice_and_text_on_stdin_when_decision_recorded(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    make_launcher().decide(
        str(hub), "run-1", gate_id="run-1:ship:1", answer=GateAnswer("reject", "too big\n")
    )

    [call] = calls(tmp_path, 1)
    assert call["argv"] == [
        "workflow",
        "decide",
        "run-1",
        "--gate",
        "run-1:ship:1",
        "--where",
        "web",
        "--choice",
        "reject",
        "--text-stdin",
    ]
    assert (call["stdin"], call["cwd"], call["linear"]) == ("too big\n", str(hub), False)


def test_passes_no_text_flag_when_answer_has_no_text(
    hub: Path, tmp_path: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    make_launcher().decide(str(hub), "run-1", gate_id="run-1:ship:1", answer=GateAnswer("approve"))

    [call] = calls(tmp_path, 1)
    assert call["argv"][-2:] == ["--choice", "approve"]
    assert call["stdin"] == ""


def test_refuses_decision_when_cli_exits_non_zero(
    hub: Path, make_launcher: Callable[..., ProcessRunLauncher]
) -> None:
    with pytest.raises(RunConflictError) as caught:
        make_launcher(FAKE_HUB_REFUSE="1").decide(
            str(hub), "run-1", gate_id="run-1:ship:1", answer=GateAnswer("approve")
        )

    assert (caught.value.code, caught.value.run_id) == ("refused", "run-1")
    assert "decided" in caught.value.reason


def test_reports_launch_error_when_decision_program_cannot_start(hub: Path, tmp_path: Path) -> None:
    launcher = ProcessRunLauncher(
        db_path=tmp_path / "db", environ={}, program=[str(tmp_path / "missing")]
    )

    with pytest.raises(RunLaunchError, match="hub workflow decide did not finish"):
        launcher.decide(str(hub), "run-1", gate_id="run-1:ship:1", answer=GateAnswer("approve"))
