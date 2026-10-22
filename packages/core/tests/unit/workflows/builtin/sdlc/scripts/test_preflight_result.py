"""The sdlc pack's ``preflight_result.py`` (AGH-473), in process: how one preflight check ended."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/preflight_result.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.preflight_result"
SUPERSEDED = "change request 1 approved but superseded by plan v2: not applied"


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


@pytest.mark.parametrize(
    ("first", "recheck", "superseded", "expected"),
    [
        ("none", "", "", {"status": "passed"}),
        ("local", "", "", {"status": "passed"}),
        # Plan drift with no re-check: a declined change given as input that still finds it.
        ("plan", "", "", {"status": "blocked"}),
        # After the owner's decision, the re-check decides.
        ("plan", "none", "", {"status": "passed"}),
        ("plan", "local", SUPERSEDED, {"status": "passed"}),
        ("plan", "plan", SUPERSEDED, {"status": "blocked"}),
    ],
)
def test_says_whether_a_preflight_passed_when_its_checks_are_read(
    capsys: pytest.CaptureFixture[str],
    *,
    first: str,
    recheck: str,
    superseded: str,
    expected: dict[str, str],
) -> None:
    argv = ["--first", first, "--recheck", recheck, "--superseded", superseded]

    assert load().main(argv) == 0

    assert json.loads(capsys.readouterr().out) == expected | {"superseded": superseded}


@pytest.mark.parametrize(
    "argv", [["--first", ""], ["--first", "global"], ["--first", "none", "--recheck", "x"]]
)
def test_exits_two_when_a_drift_is_unknown(
    capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert load().main(argv) == 2
    assert capsys.readouterr().out == ""
