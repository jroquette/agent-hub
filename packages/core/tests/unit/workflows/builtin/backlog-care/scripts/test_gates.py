"""The backlog-care pack's ``gates.py`` (AGH-489), in process: one planned item per iteration of
the ``decide`` group, so each issue gets its own approval, and each decision recorded.
"""

import importlib.util
import json
import sys
from importlib.resources import files
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/backlog-care/scripts/gates.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.backlog-care.scripts.gates"


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


def an_item(index: int, issue_id: str, label: str = "ready") -> dict[str, Any]:
    return {
        "index": index,
        "id": issue_id,
        "action": "draft",
        "label": label,
        "superseded_by": "",
        "draft": {"size": "fix", "context": f"Context of {issue_id}."},
        "message": f"{issue_id}: draft, label {label}.",
    }


PLANNED = {"count": 2, "items": [an_item(0, "DEM-3"), an_item(1, "DEM-4")], "ignored": []}


def call(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    *,
    stdin: str,
) -> dict[str, Any]:
    monkeypatch.setattr(sys, "stdin", StringIO(stdin))
    assert load().main(argv) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def record(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    item: dict[str, Any],
    *,
    decision: str,
    before: str = "",
) -> dict[str, Any]:
    argv = ["record", "--item", json.dumps(item), "--decision", decision]
    argv += ["--note", "Looks right.", "--approver", "Jo"]
    return call(capsys, monkeypatch, argv, stdin=before)


def test_opens_one_gate_per_item_when_queue_walked(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    planned = json.dumps(PLANNED)

    first = call(capsys, monkeypatch, ["next", "--after", ""], stdin=planned)
    second = call(capsys, monkeypatch, ["next", "--after", str(first["index"])], stdin=planned)

    assert (first["index"], first["last"], first["item"]["id"]) == (0, False, "DEM-3")
    assert first["message"] == "DEM-3: draft, label ready."
    assert (second["index"], second["last"], second["item"]["id"]) == (1, True, "DEM-4")
    # One item per iteration: the gate's message names one issue, never two.
    assert "DEM-4" not in first["message"]
    assert "DEM-3" not in second["message"]


def test_exits_two_when_after_past_last_item(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for after, planned in (("1", PLANNED), ("x", PLANNED), ("", {"items": []}), ("", [])):
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(planned)))
        assert load().main(["next", "--after", after]) == 2
        assert capsys.readouterr().err.startswith("gates.py: ")


def test_appends_decision_when_record_runs(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = record(capsys, monkeypatch, an_item(0, "DEM-3"), decision="apply")
    second = record(
        capsys,
        monkeypatch,
        an_item(1, "DEM-4"),
        decision="skip",
        before=json.dumps(first["decisions"]),
    )

    assert [(d["id"], d["decision"]) for d in second["decisions"]] == [
        ("DEM-3", "apply"),
        ("DEM-4", "skip"),
    ]
    assert second["decisions"][0] == {
        "id": "DEM-3",
        "decision": "apply",
        "action": "draft",
        "label": "ready",
        "superseded_by": "",
        "draft": {"size": "fix", "context": "Context of DEM-3."},
        "note": "Looks right.",
        "approver": "Jo",
    }


def test_counts_applied_when_decisions_recorded(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = record(capsys, monkeypatch, an_item(0, "DEM-3"), decision="skip")
    second = record(
        capsys,
        monkeypatch,
        an_item(1, "DEM-4"),
        decision="apply",
        before=json.dumps(first["decisions"]),
    )

    assert (first["applied"], second["applied"]) == (0, 1)


def test_cuts_owner_note_when_longer_than_limit(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["record", "--item", json.dumps(an_item(0, "DEM-3")), "--decision", "apply"]
    argv += ["--note", "a\x1b\x00\nb" + "n" * 3000, "--approver", "Jo\x07"]

    (decision,) = call(capsys, monkeypatch, argv, stdin="")["decisions"]

    assert decision["note"].startswith("a\nbn")
    assert len(decision["note"]) == 2000
    assert decision["approver"] == "Jo"
    # The note sits beside the draft, never inside it.
    assert decision["draft"] == {"size": "fix", "context": "Context of DEM-3."}


@pytest.mark.parametrize(
    ("argv", "stdin"),
    [
        (["record", "--item", "{}", "--decision", "apply"], ""),
        (["record", "--item", json.dumps(an_item(0, "DEM-3")), "--decision", "approve"], ""),
        (["record", "--item", json.dumps(an_item(0, "DEM-3")), "--decision", "skip"], "{}"),
        (["record", "--item", "x", "--decision", "skip"], ""),
        (["next"], "not json"),
        (["other"], ""),
    ],
    ids=["no-id", "bad-decision", "bad-before", "item-text", "next-text", "verb"],
)
def test_exits_two_when_input_unreadable(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    argv: list[str],
    stdin: str,
) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(stdin))

    assert load().main(argv) == 2
    assert capsys.readouterr().err.startswith("gates.py: ")
