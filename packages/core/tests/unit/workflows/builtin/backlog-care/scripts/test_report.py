"""The backlog-care pack's ``report.py`` (AGH-489), in process: the run's report and the list of
approved decisions ``/triage --backlog`` applies after the run, and only those.
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
    str(files("agent_hub.core").joinpath("workflows/builtin/backlog-care/scripts/report.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.backlog-care.scripts.report"


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


HYGIENE = "Hygiene of 7 issues read: 1 orphan, 1 stale, 1 duplicate group, 1 cycle."
UNREAD = "13 open issues were left unread (50 of 63 read, oldest first)"
DRAFT_A = {"context": "Context of A.", "size": "fix", "acceptance_criteria": ["AC-1 ..."]}


def a_decision(issue_id: str, decision: str, **fields: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "id": issue_id,
        "decision": decision,
        "action": "draft",
        "label": "ready",
        "superseded_by": "",
        "draft": DRAFT_A,
        "note": "",
        "approver": "Jo",
    }
    return found | fields


def report(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    stdin: str,
    *extra: str,
) -> dict[str, Any]:
    monkeypatch.setattr(sys, "stdin", StringIO(stdin))
    argv = ["--summary", HYGIENE, "--unread-line", UNREAD, *extra]
    assert load().main(argv) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_lists_only_approved_items_when_one_applied_one_skipped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = [
        a_decision("DEM-3", "apply"),
        a_decision("DEM-4", "skip", label="needs-human", note="Not now."),
    ]

    found = report(capsys, monkeypatch, json.dumps(decisions))

    assert found["outcome"] == "apply"
    assert found["apply"] == [
        {
            "id": "DEM-3",
            "action": "draft",
            "label": "ready",
            "superseded_by": "",
            "draft": DRAFT_A,
            "note": "",
            "approver": "Jo",
        }
    ]
    assert found["skipped"] == [{"id": "DEM-4", "note": "Not now.", "approver": "Jo"}]
    assert "DEM-4" not in json.dumps(found["apply"])
    assert "- DEM-3: apply (write the draft, label ready) by Jo" in found["summary"]
    assert "- DEM-4: skipped, left as it is by Jo; note: Not now." in found["summary"]


def test_reports_only_when_decide_skipped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = report(capsys, monkeypatch, "")

    assert (found["outcome"], found["apply"], found["skipped"]) == ("report_only", [], [])
    assert "No draft reached a gate." in found["summary"]
    assert "Nothing to apply: the tracker stays as it is." in found["summary"]


def test_reports_only_when_every_draft_skipped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = report(capsys, monkeypatch, json.dumps([a_decision("DEM-3", "skip")]))

    assert (found["outcome"], found["apply"]) == ("report_only", [])


def test_keeps_unread_line_and_hygiene_in_summary_when_report_built(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = report(capsys, monkeypatch, "")["summary"]

    assert UNREAD in summary
    assert HYGIENE in summary
    assert summary.index(UNREAD) < summary.index(HYGIENE)


def test_names_ignored_waiting_and_skipped_entries_when_report_built(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    supersede = a_decision(
        "DEM-4", "apply", action="supersede", label="close", superseded_by="DEM-3"
    )
    extra = (
        "--waiting",
        json.dumps(["DEM-8", "DEM-9"]),
        "--ignored",
        json.dumps([{"id": "DEM-12", "reason": "not picked for a draft"}]),
        "--undrafted",
        json.dumps(["DEM-5"]),
        "--skipped-entries",
        json.dumps([{"index": 3, "reason": "id missing or malformed"}]),
        "--descriptions-dropped",
        "2",
    )

    summary = report(capsys, monkeypatch, json.dumps([supersede]), *extra)["summary"]

    for shown in (
        "Waiting for a later run: DEM-8, DEM-9.",
        "Drafts ignored: DEM-12 (not picked for a draft).",
        "Picked, but not drafted: DEM-5.",
        "Entries of the issues file skipped: 3 (id missing or malformed).",
        "Descriptions dropped to fit the read budget, newest first: 2.",
        "- DEM-4: apply (close as a duplicate of DEM-3) by Jo",
        "To apply after the run: 1, one issue at a time (/triage step 5).",
    ):
        assert shown in summary, shown


def test_reads_blank_lists_as_none_when_producers_skipped(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    extra = ("--waiting", "", "--ignored", "", "--undrafted", "", "--descriptions-dropped", "0")

    summary = report(capsys, monkeypatch, "", *extra)["summary"]

    assert "Waiting" not in summary
    assert "Descriptions dropped" not in summary


def test_cuts_summary_when_longer_than_limit(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(""))
    argv = ["--summary", "h" * 30_000, "--unread-line", UNREAD]

    assert load().main(argv) == 0

    summary = json.loads(capsys.readouterr().out)["summary"]
    assert len(summary) == 24_000
    assert summary.endswith("(cut)")


@pytest.mark.parametrize(
    ("argv", "stdin"),
    [([], "not json"), ([], "{}"), (["--waiting", "{"], ""), (["--ignored", "{}"], "")],
    ids=["stdin-text", "stdin-object", "waiting-text", "ignored-object"],
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
    assert capsys.readouterr().err.startswith("report.py: ")
