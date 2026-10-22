"""The spike pack's ``budget.py`` (AGH-492), in process: the agent-time budget kept between the
spike's agent steps, and how the owner's pick ends the rounds of options."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/spike/scripts/budget.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.spike.scripts.budget"

START = 1_000_000.0
QUESTION = "Should the session brief be cached between sessions?"


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


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, Any, str]:
    code = load().main(list(argv))
    out, err = capsys.readouterr()
    return code, json.loads(out) if code == 0 else out, err


def a_state(**changes: Any) -> dict[str, Any]:
    state = {
        "slug": "brief-cache",
        "timebox_s": 7200,
        "spent_s": 0,
        "at": START,
        "over": False,
        "left_m": 120,
        "round": 0,
    }
    return state | changes


def options(*ids: str) -> str:
    listed = [{"id": i, "title": f"Option {i}", "summary": "", "pros": [], "cons": []} for i in ids]
    return json.dumps({"options": listed, "recommendation": ids[0], "reason": "", "brief": ""})


def settle(
    capsys: pytest.CaptureFixture[str],
    state: dict[str, Any],
    *,
    listed: str,
    decision: str,
    note: str = "",
    now: float = START,
    approver: str = "Dana Owner",
) -> tuple[int, Any, str]:
    return run(
        capsys,
        "settle",
        "--state",
        json.dumps(state),
        "--options",
        listed,
        "--decision",
        decision,
        "--note",
        note,
        "--approver",
        approver,
        "--max-rounds",
        "3",
        "--now",
        str(now),
    )


def test_starts_with_zero_spent_when_inputs_are_valid(capsys: pytest.CaptureFixture[str]) -> None:
    code, state, _ = run(
        capsys,
        "start",
        "--question",
        QUESTION,
        "--timebox",
        "2h",
        "--slug",
        "brief-cache",
        "--now",
        str(START),
    )

    assert code == 0
    assert state == a_state()


def test_derives_slug_from_question_when_slug_is_blank(capsys: pytest.CaptureFixture[str]) -> None:
    long = "Can the Brief, cached per-session, beat 2 seconds? " + "word " * 20

    code, state, _ = run(capsys, "start", "--question", long, "--timebox", "90m", "--slug", "")
    _, dashed, _ = run(
        capsys, "start", "--question", "-x starts with a dash", "--timebox", "2h", "--slug", ""
    )

    assert code == 0
    assert state["slug"] == "can-the-brief-cached-per-session-beat-2-seconds"
    assert len(state["slug"]) <= 48
    assert (state["timebox_s"], state["left_m"]) == (5400, 90)
    assert dashed["slug"] == "x-starts-with-a-dash"
    assert load().derive_slug("a" * 60) == "a" * 48


@pytest.mark.parametrize("question", ["", "x" * 2001, "a\x00b"])
def test_exits_two_when_question_is_empty_or_too_long(
    capsys: pytest.CaptureFixture[str], question: str
) -> None:
    code, out, err = run(capsys, "start", "--question", question, "--timebox", "2h", "--slug", "s")

    assert (code, out) == (2, "")
    assert err.startswith("budget.py: question")


@pytest.mark.parametrize("timebox", ["2", "0h", "5m", "9h", "2d", "02h", " 2h"])
def test_exits_two_when_timebox_is_malformed_or_out_of_range(
    capsys: pytest.CaptureFixture[str], timebox: str
) -> None:
    code, out, err = run(
        capsys, "start", "--question", QUESTION, "--timebox", timebox, "--slug", "s"
    )

    assert (code, out) == (2, "")
    assert err.startswith("budget.py: timebox")


@pytest.mark.parametrize(
    ("question", "slug"),
    [(QUESTION, "../x"), (QUESTION, "A_B"), (QUESTION, "-x"), (QUESTION, "a" * 65), ("?! ...", "")],
)
def test_exits_two_when_slug_is_invalid_or_cannot_be_derived(
    capsys: pytest.CaptureFixture[str], question: str, slug: str
) -> None:
    code, out, err = run(capsys, "start", "--question", question, "--timebox", "2h", "--slug", slug)

    assert (code, out) == (2, "")
    assert err.startswith("budget.py: slug")


def test_adds_elapsed_time_when_tick_follows_a_step(capsys: pytest.CaptureFixture[str]) -> None:
    given = json.dumps(a_state(spent_s=600))

    code, state, _ = run(
        capsys, "tick", "--state", given, "--cap", "60m", "--now", str(START + 1500)
    )

    assert code == 0
    assert state == a_state(spent_s=2100, at=START + 1500, left_m=85)


def test_says_over_when_spent_reaches_timebox(capsys: pytest.CaptureFixture[str]) -> None:
    given = json.dumps(a_state(spent_s=6000))

    _, under, _ = run(capsys, "tick", "--state", given, "--cap", "60m", "--now", str(START + 1199))
    _, over, _ = run(capsys, "tick", "--state", given, "--cap", "60m", "--now", str(START + 1200))

    assert (under["over"], under["left_m"]) == (False, 0)
    assert (over["over"], over["left_m"], over["spent_s"]) == (True, 0, 7200)


def test_caps_elapsed_time_at_the_step_timeout_when_clock_jumped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    given = json.dumps(a_state())
    three_days = 3 * 24 * 3600

    _, state, _ = run(
        capsys, "tick", "--state", given, "--cap", "20m", "--now", str(START + three_days)
    )
    _, back, _ = run(capsys, "tick", "--state", given, "--cap", "20m", "--now", str(START - 50))

    assert state["spent_s"] == 1200
    assert back["spent_s"] == 0


def test_reads_loop_prev_over_state_when_loop_prev_is_given(
    capsys: pytest.CaptureFixture[str],
) -> None:
    research = json.dumps(a_state(spent_s=3000))
    previous = a_state(spent_s=3600, at=START + 5000, round=1) | {
        "picked": "",
        "go": False,
        "done": False,
        "note": "Add an option without a cache.",
        "approver": "Dana Owner",
        "option": {},
    }
    now = str(START + 5600)

    _, first, _ = run(
        capsys,
        "tick",
        "--state",
        research,
        "--loop-prev",
        "",
        "--cap",
        "20m",
        "--round",
        "--now",
        str(START + 600),
    )
    _, second, _ = run(
        capsys,
        "tick",
        "--state",
        research,
        "--loop-prev",
        json.dumps(previous),
        "--cap",
        "20m",
        "--round",
        "--now",
        now,
    )

    assert first == a_state(spent_s=3600, at=START + 600, left_m=60, round=1)
    assert second == a_state(spent_s=4200, at=START + 5600, left_m=50, round=2)


@pytest.mark.parametrize(
    "given",
    ["not json", "[]", json.dumps({"slug": "s"}), json.dumps(a_state(spent_s="1")), ""],
)
def test_exits_two_when_state_is_not_a_state_object(
    capsys: pytest.CaptureFixture[str], given: str
) -> None:
    code, out, err = run(capsys, "tick", "--state", given, "--cap", "20m")

    assert (code, out) == (2, "")
    assert err.startswith("budget.py: state")
