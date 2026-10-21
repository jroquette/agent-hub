"""A scenario run's findings as texts for others (AC-350.27; docs/design/scenarios.md)."""

from datetime import date
from typing import Any

import pytest

from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.scenarios.findings import (
    FindingsError,
    finding_of,
    inbox_note,
    issue_draft,
)
from agent_hub.core.scenarios.run_record import fold_records

GATE = "order-held__investigation"
RECORD = ".agent-runs/workflows/walk-1/records.jsonl"
DAY = date(2026, 10, 21)
# A secret shape built at run time: a finding that kept one is redacted again.
KEY = "AKIA" + "SYNTHETIC0000000"


def a_record(**header: Any) -> list[dict[str, Any]]:
    """A scenario run paused at its first investigation, with two findings."""
    start = {"event": "start", "run": "walk-1", "scenario": "order-walk", "environment": "staging"}
    return [
        start | {"mode": "interactive", "kind": "scenario"} | header,
        {"event": "investigation", "step": "order-held", "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
        {
            "event": "proposal",
            "gate": GATE,
            "number": 1,
            "proposal": 1,
            "findings": [
                {
                    "finding_id": "f1",
                    "title": "Order stays\non hold",
                    "text": "The hold flag is set after the send.\nIt never clears.",
                    "evidence": f"status ON_HOLD after 5 polls; key {KEY}",
                },
                {"finding_id": "f2", "title": "Queue is slow", "text": "", "evidence": ""},
            ],
            "options": [],
        },
    ]


def test_writes_plain_draft_when_findings_issue_built() -> None:
    view = fold_records(a_record())
    finding = finding_of(view, "f1")
    assert finding is not None

    draft = issue_draft(view, finding, record=RECORD)

    assert draft.title == "Scenario order-walk: Order stays on hold"
    assert draft.description.splitlines() == [
        "The scenario order-walk found this in run walk-1, at step order-held, in environment"
        " staging.",
        "",
        "The hold flag is set after the send.",
        "It never clears.",
        "",
        "Evidence: status ON_HOLD after 5 polls; key [redacted: AWS access key]",
        "",
        "Record: /scenarios/order-walk/runs/walk-1 in hub web, or the file"
        f" {RECORD} in the hub (finding f1).",
    ]
    assert KEY not in draft.title + draft.description
    plain = issue_draft(view, view.findings[1], record=RECORD).description
    assert "Evidence: none recorded" in plain
    assert "(no description was recorded)" in plain


def test_writes_external_provenance_when_findings_inbox_built() -> None:
    view = fold_records(a_record())
    finding = finding_of(view, "f1")
    assert finding is not None

    note = inbox_note(view, finding, record=RECORD, day=DAY)

    assert note.name == "2026-10-21-scenario-order-walk-f1.md"
    front = split_frontmatter(note.text)
    assert front.fields == {
        "type": "scenario-finding",
        "repos": [],
        "status": "proposed",
        "last_verified": "2026-10-21",
        "sources": ["scenario run walk-1", "finding f1"],
        "provenance": "agent-from-external",
    }
    assert front.body.startswith("## Order stays on hold\n\n")
    assert "The hold flag is set after the send.\nIt never clears." in front.body
    assert "in environment staging" in front.body
    assert f"Record: /scenarios/order-walk/runs/walk-1 in hub web, or the file {RECORD}" in (
        front.body
    )
    assert KEY not in note.text


def test_finds_nothing_when_finding_id_unknown() -> None:
    view = fold_records(a_record())

    assert finding_of(view, "f9") is None
    assert finding_of(view, "f1") == view.findings[0]


@pytest.mark.parametrize(
    "header",
    [{"scenario": "../order-walk"}, {"run": "walk 1"}, {"scenario": None}],
    ids=["scenario-path", "run-space", "scenario-missing"],
)
def test_refuses_when_findings_record_names_unsafe_header(header: dict[str, Any]) -> None:
    view = fold_records(a_record(**header))

    with pytest.raises(FindingsError):
        inbox_note(view, view.findings[0], record=RECORD, day=DAY)
    with pytest.raises(FindingsError):
        issue_draft(view, view.findings[0], record=RECORD)
