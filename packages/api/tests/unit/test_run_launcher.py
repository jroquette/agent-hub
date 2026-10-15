"""hub web's run launcher without a child: pid files, links, input text (AC-213.19)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.run_launcher import ProcessRunLauncher, input_text
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


def test_lists_run_when_pid_file_process_has_recorded_start(tmp_path: Path) -> None:
    pid_file(tmp_path, "run-1", STARTED, issue="DEM-7")
    pid_file(tmp_path, "run-2", "Thu Jan  1 00:00:00 1970")

    assert launcher(tmp_path).live_runs(str(tmp_path)) == {"run-1": "DEM-7"}


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
        live=False,
        issue=None,
    )

    with pytest.raises(RunLaunchError, match="not a folder of the hub"):
        launcher(tmp_path).start(spec)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("value", "text"), [(True, "true"), (False, "false"), (2, "2"), (0.5, "0.5"), ("a=b", "a=b")]
)
def test_writes_cli_text_when_input_typed(value: Any, text: str) -> None:
    assert input_text(value) == text
