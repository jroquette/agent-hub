"""The sdlc pack's ``last_pass.py`` (AGH-404), in process: how the implement run's passes ended."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/last_pass.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.last_pass"


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


SUPERSEDED = "change request 1 approved but superseded by plan v2: not applied"
WORKTREE = {"path": "/ws/dem-1", "base": "0a1b2c3d", "target": {"path": "/ws/dem-1"}}


def a_pass(status: str, *, text: str = "", verdict: str = "", superseded: str = "") -> str:
    found = {
        "status": status,
        "question": "",
        "verdict": verdict,
        "next_input": "discovery" if status == "discovery" else "",
        "next_text": text,
        "superseded": superseded,
    }
    return json.dumps(found | WORKTREE)


@pytest.mark.parametrize(
    ("pending", "passes", "expected"),
    [
        (
            "",
            (a_pass("done", verdict="PASS"), "", ""),
            {"status": "done", "verdict": "PASS", "pass": 1},
        ),
        (
            SUPERSEDED,
            (a_pass("discovery", text="A.", superseded=SUPERSEDED), a_pass("done"), ""),
            {"status": "done", "pass": 2, "superseded": f"{SUPERSEDED}; {SUPERSEDED}"},
        ),
        (
            "",
            (a_pass("discovery"), a_pass("discovery"), a_pass("discovery", text="C.")),
            {"status": "blocked", "question": "a discovery in pass 3, the last one: C.", "pass": 3},
        ),
    ],
)
def test_reads_the_last_pass_and_blocks_a_third_discovery_when_passes_are_read(
    capsys: pytest.CaptureFixture[str],
    *,
    pending: str,
    passes: tuple[str, ...],
    expected: dict[str, Any],
) -> None:
    argv = ["--superseded", pending, *(item for text in passes for item in ("--pass", text))]

    assert load().main(argv) == 0

    empty = {"question": "", "verdict": "", "superseded": "", **WORKTREE}
    assert json.loads(capsys.readouterr().out) == empty | expected


@pytest.mark.parametrize("passes", [[""], ["not json"], ["[1]"]])
def test_exits_two_when_no_pass_ran_or_one_is_not_a_json_object(passes: list[str]) -> None:
    assert load().main([item for text in passes for item in ("--pass", text)]) == 2
