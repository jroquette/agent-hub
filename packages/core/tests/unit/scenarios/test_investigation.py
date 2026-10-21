"""An investigation's names and the proposal an agent records (P-5, P-8, AM-3, AM-11;
docs/design/scenarios.md § Investigation, § Events and bounds)."""

import json
from typing import Any

import pytest

import agent_hub.core.scenarios.investigation as investigation
from agent_hub.core.scenarios.investigation import (
    Finding,
    ProposalError,
    ProposedStep,
    investigation_gate,
    parse_proposal,
)

# An AWS access key's shape, built at run time: never a literal in the repo.
AWS_SHAPE = "AKIA" + "ABCDEFGHIJKLMNOP"


def a_proposal(**overrides: Any) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "findings": [
            {"title": "Order stays on hold", "text": "The queue never drains.", "evidence": "x"}
        ],
        "options": [
            {
                "summary": "Release the hold, then look again",
                "steps": [{"action": "demo/release-hold", "with": {"target": "api", "count": 2}}],
            }
        ],
    }
    return proposal | overrides


def encoded(value: object) -> bytes:
    return json.dumps(value).encode()


def test_names_gate_and_choices_when_investigation_constants_read() -> None:
    assert investigation_gate("order-held") == "order-held__investigation"
    assert investigation_gate("walk__order-held") == "walk__order-held__investigation"
    assert investigation.CHOICES == ("pick", "retry", "stop")
    assert investigation.MAX_INVESTIGATIONS == 10
    assert investigation.MAX_PROPOSAL_BYTES == 256 * 1024
    assert (investigation.MAX_FINDINGS, investigation.MAX_OPTIONS) == (20, 5)
    assert (investigation.MAX_TITLE_CHARS, investigation.MAX_TEXT_CHARS) == (120, 2000)
    assert (investigation.MAX_SUMMARY_CHARS, investigation.MAX_STEPS) == (300, 10)


def test_reads_findings_and_options_when_investigation_proposal_valid() -> None:
    proposal = parse_proposal(encoded(a_proposal()))

    assert proposal.findings == (
        Finding(title="Order stays on hold", text="The queue never drains.", evidence="x"),
    )
    (option,) = proposal.options
    assert option.summary == "Release the hold, then look again"
    assert option.steps == (
        ProposedStep(action="demo/release-hold", inputs={"target": "api", "count": 2}),
    )


def test_redacts_secret_shape_when_proposal_parsed() -> None:
    finding = {"title": f"key {AWS_SHAPE}", "text": f"seen {AWS_SHAPE}", "evidence": AWS_SHAPE}
    step = {"action": "demo/get-order", "with": {"ref": AWS_SHAPE}}
    given = a_proposal(
        findings=[finding], options=[{"summary": f"use {AWS_SHAPE}", "steps": [step]}]
    )

    proposal = parse_proposal(encoded(given))

    shown = repr(proposal)
    assert AWS_SHAPE not in shown
    assert proposal.findings[0].title == "key [redacted: AWS access key]"
    assert proposal.findings[0].evidence == "[redacted: AWS access key]"
    assert proposal.options[0].summary == "use [redacted: AWS access key]"
    assert proposal.options[0].steps[0].inputs == {"ref": "[redacted: AWS access key]"}


def over_bounds() -> list[tuple[bytes, str]]:
    """Each bound one past its constant, and the first problem it reports."""
    limits = investigation
    finding = {"title": "t", "text": "x"}
    step = {"action": "demo/get-order"}
    option = {"summary": "s", "steps": [step]}
    return [
        (b" " * (limits.MAX_PROPOSAL_BYTES + 1), "larger than 262144 bytes"),
        (b"[]", "the proposal must be an object"),
        (b"{nope", "not one JSON value"),
        (encoded({"findings": []}), "the proposal needs options"),
        (encoded(a_proposal(extra=1)), "unknown key 'extra'"),
        (
            encoded(a_proposal(findings=[finding] * (limits.MAX_FINDINGS + 1))),
            "findings: at most 20",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t" * 121, "text": "x"}])),
            "finding 1: title must be text of 1 to 120 characters",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t", "text": "x" * 2001}])),
            "finding 1: text must be text of 0 to 2000 characters",
        ),
        (
            encoded(a_proposal(findings=[{"title": "t", "text": "x", "evidence": "e" * 2001}])),
            "finding 1: evidence must be text of 0 to 2000 characters",
        ),
        (encoded(a_proposal(options=[option] * (limits.MAX_OPTIONS + 1))), "options: at most 5"),
        (
            encoded(a_proposal(options=[{"summary": "s" * 301, "steps": []}])),
            "option 1: summary must be text of 1 to 300 characters",
        ),
        (
            encoded(a_proposal(options=[{"summary": "s", "steps": [step] * 11}])),
            "option 1: steps: at most 10",
        ),
        (
            encoded(a_proposal(options=[{"summary": "s", "steps": [{"action": "a", "with": []}]}])),
            "option 1 step 1: with must map names to text, numbers or booleans",
        ),
    ]


@pytest.mark.parametrize(("data", "problem"), over_bounds())
def test_refuses_proposal_when_over_bounds(data: bytes, problem: str) -> None:
    with pytest.raises(ProposalError) as raised:
        parse_proposal(data)

    assert problem in str(raised.value)


def test_takes_bounds_exactly_when_proposal_at_limits() -> None:
    finding = {"title": "t" * 120, "text": "x" * 2000, "evidence": "e" * 2000}
    steps = [{"action": "demo/get-order"}] * 10
    given = a_proposal(
        findings=[finding] * 20, options=[{"summary": "s" * 300, "steps": steps}] * 5
    )

    proposal = parse_proposal(encoded(given))

    assert (len(proposal.findings), len(proposal.options)) == (20, 5)
