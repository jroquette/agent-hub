"""The sdlc pack's ``pass_outcome.py`` (AGH-404), in process: how one ticket pass ended."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/pass_outcome.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.pass_outcome"


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
EMPTY = {
    "status": "",
    "question": "",
    "verdict": "",
    "next_input": "",
    "next_text": "",
    "superseded": "",
    "path": "",
    "base": "",
    "target": None,
}


def a_rounds(*, status: str = "done", discovery: str = "", verdict: str | None = "PASS") -> str:
    rounds: dict[str, Any] = {
        "verdict": {"status": status, "question": "which endpoint?", "discovery": discovery},
        "review": None if verdict is None else {"verdict": verdict},
    }
    return json.dumps(rounds)


@pytest.mark.parametrize(
    ("rounds", "superseded", "expected"),
    [
        (
            "",
            "",
            {
                "status": "blocked",
                "question": "plan drift remains after the owner's decision on the plan change:"
                " the next /implement opens a new change request",
            },
        ),
        (
            "",
            SUPERSEDED,
            {
                "status": "blocked",
                "question": f"{SUPERSEDED}; the next /implement opens a new change request",
                "superseded": SUPERSEDED,
            },
        ),
        (
            a_rounds(status="blocked", verdict=None),
            "",
            {"status": "blocked", "question": "which endpoint?", **WORKTREE},
        ),
        (
            a_rounds(discovery="T3 lists.", verdict=None),
            "",
            {
                "status": "discovery",
                "next_input": "discovery",
                "next_text": "T3 lists.",
                **WORKTREE,
            },
        ),
        (
            a_rounds(),
            SUPERSEDED,
            {"status": "done", "verdict": "PASS", "superseded": SUPERSEDED, **WORKTREE},
        ),
    ],
)
def test_says_how_the_pass_ended_when_its_rounds_are_read(
    capsys: pytest.CaptureFixture[str], *, rounds: str, superseded: str, expected: dict[str, Any]
) -> None:
    worktree = json.dumps(WORKTREE) if rounds else ""
    argv = ["--rounds", rounds, "--worktree", worktree, "--superseded", superseded]

    assert load().main(argv) == 0

    assert json.loads(capsys.readouterr().out) == EMPTY | expected


@pytest.mark.parametrize("argv", [["--rounds", "not json"], ["--worktree", "[1]"]])
def test_exits_two_when_an_output_is_not_a_json_object(argv: list[str]) -> None:
    assert load().main(argv) == 2
