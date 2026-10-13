"""The agent output checks: a review or eval JSON document's shape, every problem at its path."""

import json

import pytest
from pydantic import ValidationError

from agent_hub.core.features.agent_outputs import review_problems
from agent_hub.core.features.output_models import (
    MAX_OUTPUT_BYTES,
    OutputProblem,
    ReviewFinding,
    ReviewOutput,
)

REVIEW_FILE = "spec-r1.json"
REVIEW_FOLDER = "AGH-7"


def a_finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "id": "F1",
        "kind": "quality",
        "severity": "minor",
        "path": "packages/core/src/agent_hub/core/features/scope_rules.py",
        "line": 12,
        "acs": ["AC-139.1"],
        "what": "The helper name says what, not why.",
        "expected": "A name that reveals intent.",
    }
    return finding | overrides


def a_review_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "agent-hub/review/1",
        "reviewer": "spec",
        "ticket": "AGH-7",
        "task": "T2",
        "round": 1,
        "commit": "feb9c4c",
        "verdict": "PASS",
        "findings": [a_finding()],
    }
    return document | overrides


def review_bytes(document: object) -> bytes:
    return json.dumps(document).encode()


def problems_of(document: object) -> tuple[OutputProblem, ...]:
    return review_problems(review_bytes(document), file_name=REVIEW_FILE, folder_name=REVIEW_FOLDER)


def without(document: dict[str, object], key: str) -> dict[str, object]:
    return {name: value for name, value in document.items() if name != key}


def test_accepts_valid_review_when_every_field_valid() -> None:
    assert problems_of(a_review_document()) == ()


def test_freezes_models_when_valid_review_parsed() -> None:
    review = ReviewOutput.model_validate(a_review_document())

    with pytest.raises(ValidationError):
        review.verdict = "FAIL"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        review.findings[0].severity = "blocking"  # type: ignore[misc]
    assert isinstance(review.findings[0], ReviewFinding)
    assert review.schema_id == "agent-hub/review/1"


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (a_review_document(colour="red"), "colour"),
        (a_review_document(findings=[a_finding(colour="red")]), "findings[0].colour"),
        (a_review_document(schema_id="agent-hub/review/1"), "schema_id"),
    ],
    ids=["top level", "inside a finding", "python name of schema"],
)
def test_reports_unknown_key_when_valid_review_gains_colour(
    document: dict[str, object], path: str
) -> None:
    problems = problems_of(document)

    assert [problem.path for problem in problems] == [path]


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (a_review_document(schema="agent-hub/review/2"), "schema"),
        (without(a_review_document(), "schema"), "schema"),
        (a_review_document(reviewer="style"), "reviewer"),
        (a_review_document(findings=[a_finding(kind="typo")]), "findings[0].kind"),
        (a_review_document(findings=[a_finding(severity="nit")]), "findings[0].severity"),
        (a_review_document(findings=[a_finding(severity="should-fix")]), "findings[0].severity"),
        (a_review_document(findings=[a_finding(severity="blocker")]), "findings[0].severity"),
        (a_review_document(round=0), "round"),
        (a_review_document(round=10000), "round"),
        (a_review_document(round=True), "round"),
        (a_review_document(findings=[a_finding(line=0)]), "findings[0].line"),
        (a_review_document(commit="XYZ"), "commit"),
        (a_review_document(ticket="T" * 33), "ticket"),
        (a_review_document(findings=[a_finding(acs=["AC 1"])]), "findings[0].acs[0]"),
        (a_review_document(findings=[a_finding(what="w" * 1001)]), "findings[0].what"),
        (a_review_document(findings=[a_finding(what="one\ntwo")]), "findings[0].what"),
        (
            a_review_document(findings=[a_finding(id=f"F{index}") for index in range(101)]),
            "findings",
        ),
        (a_review_document(findings=[without(a_finding(), "what")]), "findings[0].what"),
    ],
    ids=[
        "schema version 2",
        "schema absent",
        "reviewer style",
        "kind typo",
        "severity nit",
        "severity should-fix",
        "severity blocker",
        "round 0",
        "round 10000",
        "round true",
        "line 0",
        "commit XYZ",
        "ticket over 32",
        "ac id with a space",
        "what of 1001",
        "what with a newline",
        "101 findings",
        "missing what",
    ],
)
def test_reports_one_problem_when_review_shape_broken(
    document: dict[str, object], path: str
) -> None:
    problems = problems_of(document)

    assert [problem.path for problem in problems] == [path]
    assert all("\n" not in problem.message for problem in problems)


def test_cuts_long_key_when_review_shape_has_unknown_key() -> None:
    problems = problems_of(a_review_document(**{"k" * 200: 1}))

    assert problems == (
        OutputProblem('["' + "k" * 79 + '\\u2026"]', "Extra inputs are not permitted"),
    )


def test_reports_every_unknown_key_when_review_shape_has_many_extra_keys() -> None:
    extra = {f"x{index}": 0 for index in range(1000)}

    problems = problems_of(a_review_document(**extra))

    assert [problem.path for problem in problems] == list(extra)


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe{}",
        b"{not json",
        b'{"verdict": "PASS", "verdict": "FAIL"}',
        b'{"round": NaN}',
        b"[]",
        b"",
        b" " * (MAX_OUTPUT_BYTES + 1),
    ],
    ids=["not utf-8", "not json", "duplicate key", "nan", "array", "empty", "over the bound"],
)
def test_reports_one_root_problem_when_bytes_unusable(content: bytes) -> None:
    problems = review_problems(content, file_name=REVIEW_FILE, folder_name=REVIEW_FOLDER)

    assert [problem.path for problem in problems] == ["$"]
    assert "\n" not in problems[0].message
    assert problems[0].message
