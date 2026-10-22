"""A scenario run folded from its record (P-16; docs/design/scenarios.md § Investigation)."""

import json
from typing import Any

import pytest

from agent_hub.core.scenarios.run_record import (
    RunRecordError,
    fold_records,
    record_lines,
)

GATE = "order-held__investigation"


def a_record() -> list[dict[str, Any]]:
    """A scenario run paused at its first investigation, with one proposal."""
    return [
        {"event": "start", "run": "walk-1", "scenario": "order-walk", "environment": "local"}
        | {"mode": "interactive", "kind": "scenario", "ts": "2026-10-21T10:00:00+00:00"},
        {"event": "inputs", "inputs": {"ref": "T-1"}},
        {"event": "step_start", "node": "order-held", "attempt": 1},
        {"event": "step_end", "node": "order-held", "attempt": 1, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": "order-held", "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
        a_proposal(1, "Order stays on hold", "o1"),
    ]


def a_proposal(proposal: int, title: str, *options: str) -> dict[str, Any]:
    return {
        "event": "proposal",
        "gate": GATE,
        "number": 1,
        "proposal": proposal,
        "findings": [{"finding_id": f"f{proposal}", "title": title, "text": "x", "evidence": ""}],
        "options": [
            {
                "option_id": option,
                "summary": "Release the hold",
                "steps": [{"action": "demo/release-hold", "with": {}}],
                "plan": [{"index": 1, "decision": "allow"}],
            }
            for option in options
        ],
    }


def test_folds_timeline_when_records_given() -> None:
    view = fold_records(a_record())

    assert (view.run, view.scenario, view.environment, view.mode, view.status) == (
        "walk-1",
        "order-walk",
        "local",
        "interactive",
        None,
    )
    assert [(item.event, item.node, item.attempt) for item in view.timeline] == [
        ("start", None, None),
        ("step_start", "order-held", 1),
        ("step_end", "order-held", 1),
        ("investigation", "order-held", 1),
        ("gate", GATE, 1),
        ("proposal", GATE, 1),
    ]
    assert view.timeline[0].at == "2026-10-21T10:00:00+00:00"
    (investigation,) = view.investigations
    assert (investigation.step, investigation.gate, investigation.failure_kind) == (
        "order-held",
        GATE,
        "timeout",
    )
    assert view.open_investigation == investigation
    assert [finding.finding_id for finding in view.findings] == ["f1"]


def test_closes_investigation_with_answer_when_decided_and_ended() -> None:
    records = [
        *a_record(),
        {"event": "decision", "node": GATE, "attempt": 1, "choice": "stop", "text": None}
        | {"approver": "dev"},
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"},
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "option": "o1"}
        | {"steps": 1, "approver": "dev"},
        {"event": "workaround_end", "workaround_id": "w1", "number": 1, "status": "ok"},
        {"event": "end", "status": "cancelled"},
    ]

    view = fold_records(records)

    (investigation,) = view.investigations
    assert (investigation.choice, investigation.approver, investigation.closed) == (
        "stop",
        "dev",
        True,
    )
    assert view.status == "cancelled"
    assert view.open_investigation is None
    assert [(item.workaround_id, item.option, item.status) for item in view.workarounds] == [
        ("w1", "o1", "ok")
    ]
    # Stop keeps the findings.
    assert [finding.title for finding in view.findings] == ["Order stays on hold"]


def test_keeps_latest_proposal_when_proposed_twice() -> None:
    records = [*a_record(), a_proposal(2, "The hold is a config flag", "o1", "o2")]

    view = fold_records(records)

    proposal = view.investigations[0].proposal
    assert proposal is not None
    assert proposal.proposal == 2
    assert [option.option_id for option in proposal.options] == ["o1", "o2"]
    assert proposal.option("o2") is not None
    assert proposal.option("o3") is None
    assert [finding.title for finding in view.findings] == ["The hold is a config flag"]


def test_drops_torn_line_when_record_cut() -> None:
    lines = [json.dumps(record) for record in a_record()]
    data = ("\n".join(lines) + "\n").encode() + b'{"event": "proposal", "gate": "order-he'

    parsed = record_lines(data)

    assert parsed == a_record()
    assert fold_records(parsed).investigations[0].proposal is not None


def test_refuses_line_when_record_holds_non_object() -> None:
    with pytest.raises(RunRecordError):
        record_lines(b'{"event": "start"}\n[1, 2]\n')


def test_keeps_polls_captures_and_decisions_when_records_folded() -> None:
    record = [
        *a_record(),
        {"event": "expect.poll", "node": "order-held", "attempt": 2, "poll": 1, "held": True}
        | {"output": {"status": "ON_HOLD"}, "ts": "2026-10-21T10:01:00+00:00"},
        {"event": "context.capture", "node": "order-held", "attempt": 2, "name": "order_id"}
        | {"value": "o-1"},
        {"event": "decision", "node": GATE, "attempt": 1, "choice": "retry", "text": None}
        | {"approver": "demo", "where": "web", "ts": "2026-10-21T10:02:00+00:00"},
    ]

    view = fold_records(record)

    (poll,) = view.polls
    assert (poll.node, poll.attempt, poll.poll, poll.held) == ("order-held", 2, 1, True)
    assert "output" not in repr(poll)
    (capture,) = view.captures
    assert (capture.name, capture.value) == ("order_id", "o-1")
    (decision,) = view.decisions
    assert (decision.node, decision.choice, decision.approver, decision.where) == (
        GATE,
        "retry",
        "demo",
        "web",
    )
