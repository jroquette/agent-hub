"""hub web's run launcher over pid files: states, links, signals, caps (AC-213.19)."""

import fcntl
import json
import os
import signal
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

from agent_hub.api import run_launcher
from agent_hub.api.run_launcher import MAX_CHILDREN, MAX_PID_FILES, ProcessRunLauncher, _Child
from agent_hub.core.workflows.launch import LaunchSpec, RunConflictError, RunLaunchError

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


# The safeguards around start times read outside the lock (F4): ``started_of`` hooks change or
# hold a pid file while it is being judged, as another launch or hub web could.
OLD = "Thu Jan  1 00:00:00 1970"


def hooked(tmp_path: Path, hook: Callable[[int], str | None]) -> ProcessRunLauncher:
    return ProcessRunLauncher(
        db_path=tmp_path / "db",
        environ={},
        program=[str(tmp_path / "never-run")],
        started_of=hook,
    )


def web(hub: Path) -> Path:
    return hub / ".agent-runs" / "web"


def test_keeps_and_reports_file_when_it_changes_while_judged_stale(tmp_path: Path) -> None:
    pid_file(tmp_path, "run-1", OLD)

    def rewrite(_pid: int) -> str:
        # Judged stale (another start time), while a new child's record replaces the file.
        pid_file(tmp_path, "run-1", "Fri Oct 16 10:00:00 2026", issue="DEM-8")
        return STARTED

    live = hooked(tmp_path, rewrite).live_runs(str(tmp_path))

    assert (web(tmp_path) / "run-1.pid").exists()
    assert live == {"run-1": "DEM-8"}


def test_keeps_and_reports_file_when_it_is_held_while_judged_stale(tmp_path: Path) -> None:
    pid_file(tmp_path, "run-1", OLD, issue="DEM-7")
    owner: list[ProcessRunLauncher] = []

    def hold(_pid: int) -> str:
        owner[0]._children[web(tmp_path) / "run-1.pid"] = _Child(  # noqa: SLF001
            process=None,  # type: ignore[arg-type]
            issue="DEM-7",
            ended_read=-1,
        )
        return STARTED

    owner.append(hooked(tmp_path, hold))
    live = owner[0].live_runs(str(tmp_path))

    assert (web(tmp_path) / "run-1.pid").exists()
    assert live == {"run-1": "DEM-7"}


def spec_of(hub: Path) -> LaunchSpec:
    return LaunchSpec(
        run_id="run-1", project="demo", hub_path=str(hub), workflow="fix", inputs={}, issue=None
    )


def test_refuses_launch_when_file_changes_after_it_was_judged(tmp_path: Path) -> None:
    pid_file(tmp_path, "run-1", OLD)

    def rewrite(_pid: int) -> str:
        pid_file(tmp_path, "run-1", "Fri Oct 16 10:00:00 2026")
        return STARTED  # the old record is judged stale; the file now names another child

    with pytest.raises(RunConflictError) as caught:
        hooked(tmp_path, rewrite).start(spec_of(tmp_path))

    assert caught.value.code == "in_use"
    assert (web(tmp_path) / "run-1.pid").exists()


def test_refuses_launch_when_empty_file_appears_after_none_was_judged(tmp_path: Path) -> None:
    web(tmp_path).mkdir(parents=True)
    target = web(tmp_path) / "run-1.pid"
    real_bytes = run_launcher._pid_bytes  # noqa: SLF001
    calls: list[Path] = []

    def read_then_create(path: Path) -> bytes | None:
        found = real_bytes(path)
        if path == target and not calls:
            calls.append(path)
            target.touch()  # another process just made it, not yet written
        return found

    probe = launcher(tmp_path)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run_launcher, "_pid_bytes", read_then_create)
        with pytest.raises(RunConflictError) as caught:
            probe.start(spec_of(tmp_path))

    assert caught.value.code == "in_use"
    assert target.exists()


def test_reads_start_times_within_budget_then_keeps_rest_live_when_scan_is_slow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(5):
        pid_file(tmp_path, f"run-{index}", OLD)
    clock = [0.0]
    reads: list[int] = []

    def slow(_pid: int) -> str:
        reads.append(_pid)
        clock[0] += 1.0  # each read takes one second
        return STARTED  # every file is stale

    monkeypatch.setattr(run_launcher, "SCAN_BUDGET_SECONDS", 2.5)
    monkeypatch.setattr(
        run_launcher, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda _: None)
    )

    live = hooked(tmp_path, slow).live_runs(str(tmp_path))

    assert len(reads) == 3
    assert live == {"run-3": None, "run-4": None}
    assert sorted(path.name for path in web(tmp_path).iterdir()) == ["run-3.pid", "run-4.pid"]


def test_refuses_launch_when_empty_pid_file_is_held_by_its_writer(tmp_path: Path) -> None:
    web(tmp_path).mkdir(parents=True)
    target = web(tmp_path) / "run-1.pid"
    # Another hub web mid-spawn: its pid file is made and locked, the record not yet written.
    writer = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    fcntl.flock(writer, fcntl.LOCK_EX)
    try:
        with pytest.raises(RunConflictError) as caught:
            launcher(tmp_path).start(spec_of(tmp_path))
    finally:
        os.close(writer)

    assert caught.value.code == "in_use"
    assert target.exists()


def test_never_spawns_second_child_when_other_launcher_holds_pid_file(tmp_path: Path) -> None:
    spawning, release = threading.Event(), threading.Event()
    first, second = launcher(tmp_path), launcher(tmp_path)
    spawned: list[str] = []

    def slow_spawn(*_args: object, **_kwargs: object) -> NoReturn:
        spawned.append("first")
        spawning.set()
        release.wait(10)
        raise RunLaunchError("stopped by the test")

    def counted_spawn(*_args: object, **_kwargs: object) -> NoReturn:
        spawned.append("second")
        raise RunLaunchError("must not run")

    first._spawn = slow_spawn  # type: ignore[method-assign]
    second._spawn = counted_spawn  # type: ignore[method-assign]
    errors: list[Exception] = []

    def launch_first() -> None:
        try:
            first.start(spec_of(tmp_path))
        except RunLaunchError as error:
            errors.append(error)

    thread = threading.Thread(target=launch_first)
    thread.start()
    try:
        assert spawning.wait(10)
        with pytest.raises(RunConflictError) as caught:
            second.start(spec_of(tmp_path))
    finally:
        release.set()
        thread.join()

    assert caught.value.code == "in_use"
    assert spawned == ["first"]


def test_skips_pid_path_when_it_is_a_folder(tmp_path: Path) -> None:
    (web(tmp_path) / "run-1.pid").mkdir(parents=True)

    assert launcher(tmp_path).live_runs(str(tmp_path)) == {}
