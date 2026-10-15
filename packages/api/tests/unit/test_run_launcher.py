"""hub web's run launcher over pid files: states, links, signals, caps (AC-213.19)."""

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from agent_hub.api.run_launcher import MAX_CHILDREN, MAX_PID_FILES, ProcessRunLauncher
from agent_hub.core.workflows.launch import LaunchSpec, RunLaunchError

STARTED = "Thu Oct 15 09:00:00 2026"


def launcher(tmp_path: Path) -> ProcessRunLauncher:
    return ProcessRunLauncher(
        db_path=tmp_path / "db",
        environ={},
        program=[str(tmp_path / "never-run")],
        started_of=lambda pid: STARTED if pid == os.getpid() else None,
    )


def pid_file(hub: Path, run_id: str, started: str, *, issue: str | None = None) -> None:
    folder = hub / ".agent-runs" / "web"
    folder.mkdir(parents=True, exist_ok=True)
    record = {"pid": os.getpid(), "started": started, "issue": issue}
    (folder / f"{run_id}.pid").write_text(json.dumps(record))


def test_lists_run_and_drops_stale_file_when_pid_files_scanned(tmp_path: Path) -> None:
    pid_file(tmp_path, "run-1", STARTED, issue="DEM-7")
    pid_file(tmp_path, "run-2", "Thu Jan  1 00:00:00 1970")

    assert launcher(tmp_path).live_runs(str(tmp_path)) == {"run-1": "DEM-7"}
    assert not (tmp_path / ".agent-runs" / "web" / "run-2.pid").exists()


def test_counts_but_never_signals_process_when_start_time_unreadable(tmp_path: Path) -> None:
    # A live process (this one) whose start time cannot be read: maybe ours, so kept.
    pid_file(tmp_path, "run-1", STARTED, issue="DEM-7")
    unreadable = ProcessRunLauncher(
        db_path=tmp_path / "db", environ={}, program=["never-run"], started_of=lambda _: None
    )

    assert unreadable.live_runs(str(tmp_path)) == {"run-1": "DEM-7"}
    assert unreadable.cancel(str(tmp_path), "run-1") is False
    assert (tmp_path / ".agent-runs" / "web" / "run-1.pid").exists()


def test_signals_group_when_pid_file_process_has_recorded_start(tmp_path: Path) -> None:
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)  # noqa: S607
    try:
        record = {"pid": child.pid, "started": STARTED, "issue": None}
        folder = tmp_path / ".agent-runs" / "web"
        folder.mkdir(parents=True)
        (folder / "run-1.pid").write_text(json.dumps(record))
        owner = ProcessRunLauncher(
            db_path=tmp_path / "db",
            environ={},
            program=[str(tmp_path / "never-run")],
            started_of=lambda pid: STARTED if pid == child.pid and child.poll() is None else None,
            grace=0.2,
        )

        assert owner.cancel(str(tmp_path), "run-1") is True
        assert child.wait(timeout=10) == -signal.SIGINT
    finally:
        child.kill()
        child.wait()


def test_refuses_cancel_when_web_runs_folder_is_link(tmp_path: Path) -> None:
    (tmp_path / ".agent-runs").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / ".agent-runs" / "web").symlink_to(tmp_path / "out")

    with pytest.raises(RunLaunchError, match="not a folder of the hub"):
        launcher(tmp_path).cancel(str(tmp_path), "run-1")


@pytest.mark.parametrize("content", ["", "{", '{"pid": true, "started": "x"}', '{"pid": 1}'])
def test_ignores_pid_file_when_it_does_not_read(tmp_path: Path, content: str) -> None:
    folder = tmp_path / ".agent-runs" / "web"
    folder.mkdir(parents=True)
    (folder / "run-1.pid").write_text(content)

    assert launcher(tmp_path).live_runs(str(tmp_path)) == {}


def test_refuses_cancel_when_pid_file_names_another_process(tmp_path: Path) -> None:
    # Our own pid, with a start time it never had: a reused pid is never signalled.
    pid_file(tmp_path, "run-1", "Thu Jan  1 00:00:00 1970")

    assert launcher(tmp_path).cancel(str(tmp_path), "run-1") is False
    assert launcher(tmp_path).cancel(str(tmp_path), "missing") is False
    assert launcher(tmp_path).cancel(str(tmp_path), "../run-1") is False


def test_refuses_start_when_web_runs_folder_is_link(tmp_path: Path) -> None:
    hub, outside = tmp_path / "hub", tmp_path / "out"
    (hub / ".agent-runs").mkdir(parents=True)
    outside.mkdir()
    (hub / ".agent-runs" / "web").symlink_to(outside)
    spec = LaunchSpec(
        run_id="run-1",
        project="demo",
        hub_path=str(hub),
        workflow="fix",
        inputs={},
        issue=None,
    )

    with pytest.raises(RunLaunchError, match="not a folder of the hub"):
        launcher(tmp_path).start(spec)
    assert list(outside.iterdir()) == []


def test_pins_caps_when_launcher_built() -> None:
    assert (MAX_CHILDREN, MAX_PID_FILES) == (8, 64)


def test_scans_first_sixty_four_pid_files_when_folder_holds_more(tmp_path: Path) -> None:
    for index in range(65):
        pid_file(tmp_path, f"run-{index:03d}", STARTED)

    live = launcher(tmp_path).live_runs(str(tmp_path))

    assert len(live) == 64
    assert "run-064" not in live
