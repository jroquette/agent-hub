"""The retro pack's ``vet.py`` (AGH-488), in process: every change cites step 1's numbers."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/retro/scripts/vet.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.retro.scripts.vet"


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


STEP_ONE = {
    "workflow.deliver.runs": 3,
    "workflow.deliver.failed_at.rounds__check": 2,
    "workflow.implement.no_ship_rate": 0.25,
    "skills.idle": 4,
}


def a_change(title: str, *refs: tuple[str, float]) -> dict[str, Any]:
    return {
        "title": title,
        "kind": "workflow",
        "change": f"Do {title}.",
        "metrics": [{"key": key, "value": value} for key, value in refs],
        "links": [".agent-runs/workflows/deliver-1/"],
        "expected_effect": "Fewer failed checks.",
        "how_to_tell": "failed_at.rounds__check drops to 0.",
    }


def test_keeps_change_when_every_metric_matches_step_one() -> None:
    change = a_change("Run lint first", ("workflow.deliver.runs", 3), ("skills.idle", 4.0))

    found = load().vet([change], STEP_ONE)

    assert found["count"] == 1
    assert found["kept"] == [{"n": 1} | change]
    assert found["dropped"] == []


def test_drops_change_when_metric_key_not_in_step_one() -> None:
    changes = [
        a_change("Invented", ("workflow.deliver.runs", 3), ("workflow.x.runs", 1)),
        a_change("No numbers"),
    ]

    found = load().vet(changes, STEP_ONE)

    assert found["count"] == 0
    assert found["dropped"] == [
        {"title": "Invented", "reason": "cites workflow.x.runs, not in step 1"},
        {"title": "No numbers", "reason": "cites no step 1 number"},
    ]


def test_drops_change_when_value_differs_from_step_one() -> None:
    changes = [
        a_change("Close enough", ("workflow.implement.no_ship_rate", 0.254)),
        a_change("Wrong count", ("workflow.deliver.runs", 4)),
        a_change("Not a number", ("workflow.deliver.runs", "3")),  # type: ignore[arg-type]
    ]

    found = load().vet(changes, STEP_ONE)

    assert [change["title"] for change in found["kept"]] == ["Close enough"]
    assert found["dropped"] == [
        {"title": "Wrong count", "reason": "cites 4 for workflow.deliver.runs, step 1 has 3"},
        {"title": "Not a number", "reason": "cites '3' for workflow.deliver.runs, step 1 has 3"},
    ]


def test_cuts_to_five_when_more_changes_given() -> None:
    changes = [a_change(f"Change {n}", ("skills.idle", 4)) for n in range(1, 8)]

    found = load().vet(changes, STEP_ONE)

    assert found["count"] == 5
    assert [change["n"] for change in found["kept"]] == [1, 2, 3, 4, 5]
    assert found["dropped"] == [
        {"title": "Change 6", "reason": "over the five-change cap"},
        {"title": "Change 7", "reason": "over the five-change cap"},
    ]


def test_numbers_kept_changes_and_lists_dropped_in_message_when_vetted() -> None:
    changes = [
        a_change("Run lint first", ("workflow.deliver.failed_at.rounds__check", 2)),
        a_change("Invented", ("workflow.x.runs", 1)),
        a_change("Retire idle skills", ("skills.idle", 4), ("workflow.deliver.runs", 3)),
    ]

    message = load().vet(changes, STEP_ONE)["message"]

    assert "1. Run lint first (workflow)" in message
    assert "2. Retire idle skills (workflow)" in message
    assert message.index("1. Run lint first") < message.index("2. Retire idle skills")
    assert "   - workflow.deliver.failed_at.rounds__check = 2" in message
    assert "   - skills.idle = 4" in message
    assert "   - workflow.deliver.runs = 3" in message
    assert "- Invented: cites workflow.x.runs, not in step 1" in message
    assert "Expected effect: Fewer failed checks." in message
    assert ".agent-runs/workflows/deliver-1/" in message


def test_counts_zero_when_every_change_dropped() -> None:
    found = load().vet([a_change("Invented", ("workflow.x.runs", 1))], STEP_ONE)

    assert (found["count"], found["kept"]) == (0, [])
    assert "No change kept" in found["message"]

    assert load().vet([], STEP_ONE) == {
        "count": 0,
        "kept": [],
        "dropped": [],
        "message": "No change kept: the retro proposes nothing this time.",
    }


@pytest.mark.parametrize(
    "given",
    [
        ("not json", json.dumps(STEP_ONE)),
        ('{"changes": "x"}', json.dumps(STEP_ONE)),
        ("[]", json.dumps(STEP_ONE)),
        (json.dumps({"changes": []}), "not json"),
        (json.dumps({"changes": []}), "[1]"),
    ],
)
def test_exits_two_when_changes_not_json(
    given: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin, metrics = given
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    code = load().main(["--metrics", metrics])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.startswith("vet.py: ")


def test_prints_vetted_changes_when_stdin_holds_agent_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    change = a_change("Run lint first", ("workflow.deliver.runs", 3))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"changes": [change]})))

    code = load().main(["--metrics", json.dumps(STEP_ONE)])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
