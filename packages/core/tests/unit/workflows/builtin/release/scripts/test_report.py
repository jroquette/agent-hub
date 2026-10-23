"""The release pack's ``report.py`` (AGH-494), in process: the run's outcome."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/release/scripts/report.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.release.scripts.report"


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


LOG = "/work/temp/release-check-1.log"
PR = "https://github.com/acme/platform/pull/250"
PIN_PR = "https://github.com/acme/demo-hub/pull/30"
RELEASED = {
    "count": "3",
    "passed": "true",
    "log": LOG,
    "go": "approve",
    "pr": PR,
    "tagged": "tagged",
    "pin-go": "approve",
    "pin-pr": PIN_PR,
    "version": "0.21.0",
}


def report(capsys: pytest.CaptureFixture[str], given: dict[str, str]) -> dict[str, Any]:
    argv = [part for name, value in given.items() for part in (f"--{name}", value)]
    assert load().main(argv) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_reports_released_when_pin_pr_opened(capsys: pytest.CaptureFixture[str]) -> None:
    found = report(capsys, RELEASED)

    assert found == {
        "outcome": "released",
        "version": "0.21.0",
        "pr": PR,
        "pin_pr": PIN_PR,
        "reason": f"v0.21.0 is tagged; the hub pin PR is open: {PIN_PR}",
    }


def test_reports_blocked_when_check_red(capsys: pytest.CaptureFixture[str]) -> None:
    skipped = dict.fromkeys(("go", "pr", "tagged", "pin-go", "pin-pr"), "")
    found = report(capsys, RELEASED | {"passed": "false"} | skipped)

    assert found["outcome"] == "blocked"
    assert LOG in found["reason"]
    assert (found["pr"], found["pin_pr"]) == ("", "")


@pytest.mark.parametrize(
    ("given", "outcome"),
    [
        ({"count": "0", "passed": "", "log": "", "go": "", "pr": "", "tagged": ""}, "nothing"),
        ({"go": "reject", "pr": "", "tagged": ""}, "declined"),
        ({"tagged": "stop"}, "stopped"),
        ({"pin-go": "reject"}, "unpinned"),
    ],
)
def test_reports_outcome_when_run_ends_early(
    capsys: pytest.CaptureFixture[str], *, given: dict[str, str], outcome: str
) -> None:
    rest = {"pin-go": "", "pin-pr": ""} if outcome != "unpinned" else {"pin-pr": ""}
    found = report(capsys, RELEASED | rest | given)

    assert found["outcome"] == outcome
    assert found["reason"]
    assert found["pin_pr"] == ""


def test_exits_two_when_count_not_a_number(capsys: pytest.CaptureFixture[str]) -> None:
    argv = [part for name, value in RELEASED.items() for part in (f"--{name}", value)]
    argv[argv.index("--count") + 1] = "many"

    assert load().main(argv) == 2


def test_reads_values_starting_with_a_dash_when_given(capsys: pytest.CaptureFixture[str]) -> None:
    # Every value is data (AGH-480): a leading dash is never read as an option.
    found = report(capsys, RELEASED | {"log": "-check.log"})

    assert found["outcome"] == "released"
