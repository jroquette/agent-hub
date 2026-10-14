"""The agent output checks: a review or eval JSON document's shape, every problem at its path."""

import json
from collections.abc import Callable, Iterator
from importlib.resources import files
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from agent_hub.core.features.agent_outputs import (
    OUTPUT_SCHEMA_FILES,
    OUTPUT_SCHEMA_PACKAGE,
    OutputKind,
    eval_problems,
    export_output_schema_text,
    read_shipped_output_schema,
    review_problems,
)
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.output_models import (
    MAX_OUTPUT_BYTES,
    AcResult,
    EvalOutput,
    OutputProblem,
    ReviewFinding,
    ReviewOutput,
)
from agent_hub.core.features.output_shape import output_path
from agent_hub.core.hub_config.versions import ECHO_LIMIT

REVIEW_FILE = "spec-r1.json"
REVIEW_FOLDER = "AGH-7"
EVAL_FILE = "agh-7.json"


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


# One row per shape rule a review breaks, and the path of its one problem.
REVIEW_SHAPE_BROKEN: list[tuple[dict[str, object], str]] = [
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
]
REVIEW_SHAPE_BROKEN_IDS = [
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
]


@pytest.mark.parametrize(("document", "path"), REVIEW_SHAPE_BROKEN, ids=REVIEW_SHAPE_BROKEN_IDS)
def test_reports_one_problem_when_review_shape_broken(
    document: dict[str, object], path: str
) -> None:
    problems = problems_of(document)

    assert [problem.path for problem in problems] == [path]
    assert all("\n" not in problem.message for problem in problems)


@pytest.mark.parametrize(
    ("key", "path"),
    [
        ("k" * 200, '["' + "k" * 79 + '…"]'),
        ("k" * 80, "k" * 80),
        ("a\n\x1b[31m", '["a\\n\\u001b[31m"]'),
        ("é" * 80, '["' + "\\u00e9" * 13 + '…"]'),
    ],
    ids=["plain key over the limit", "plain key at the limit", "control characters", "80 accents"],
)
def test_cuts_long_key_when_review_shape_has_unknown_key(key: str, path: str) -> None:
    problems = problems_of(a_review_document(**{key: 1}))

    assert problems == (OutputProblem(path, "Extra inputs are not permitted"),)


def test_escapes_key_once_within_limit_when_review_shape_has_unknown_key() -> None:
    (problem,) = problems_of(a_review_document(**{"é" * 80: 1}))

    inner = problem.path.removeprefix('["').removesuffix('"]')
    assert len(inner) <= 80
    assert "\\\\" not in inner


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (a_review_document(findings=[0] * 101), "findings"),
        (a_review_document(findings=[a_finding(acs=["a b"] * 51)]), "findings[0].acs"),
    ],
    ids=["101 bad findings", "51 bad acs"],
)
def test_reports_overlong_list_when_review_shape_has_bad_items(
    document: dict[str, object], path: str
) -> None:
    paths = [problem.path for problem in problems_of(document)]

    assert paths.count(path) == 1
    assert len(paths) > 1


def test_reports_every_unknown_key_when_review_shape_has_many_extra_keys() -> None:
    extra = {f"x{index}": 0 for index in range(1000)}

    problems = problems_of(a_review_document(**extra))

    assert [problem.path for problem in problems] == list(extra)


def named_review_problems(
    document: object, *, file_name: str = REVIEW_FILE, folder_name: str = REVIEW_FOLDER
) -> tuple[OutputProblem, ...]:
    return review_problems(review_bytes(document), file_name=file_name, folder_name=folder_name)


@pytest.mark.parametrize(
    ("document", "problem"),
    [
        (
            a_review_document(verdict="FAIL"),
            OutputProblem("verdict", "the verdict is FAIL but no finding is blocking"),
        ),
        (
            a_review_document(findings=[a_finding(), a_finding(id="F2", severity="blocking")]),
            OutputProblem("verdict", "the verdict is PASS but findings[1] is blocking"),
        ),
    ],
    ids=["fail with only minor findings", "pass with a blocking finding"],
)
def test_reports_verdict_when_review_verdict_contradicts_findings(
    document: dict[str, object], problem: OutputProblem
) -> None:
    assert problems_of(document) == (problem,)


@pytest.mark.parametrize(
    "document",
    [
        a_review_document(verdict="FAIL", findings=[a_finding(severity="blocking")]),
        a_review_document(verdict="PASS", findings=[a_finding()]),
        a_review_document(verdict="PASS", findings=[]),
    ],
    ids=["fail with a blocking finding", "pass with a minor finding", "pass with none"],
)
def test_accepts_review_verdict_when_it_matches_findings(document: dict[str, object]) -> None:
    assert problems_of(document) == ()


def test_reports_repeated_finding_id_when_review_verdict_checked() -> None:
    document = a_review_document(findings=[a_finding(), a_finding(line=13)])

    assert problems_of(document) == (
        OutputProblem("findings[1].id", "the id F1 repeats findings[0].id"),
    )


@pytest.mark.parametrize(
    ("ticket", "file_name", "folder_name", "problem"),
    [
        (
            "AGH-7",
            "quality-r1.json",
            "AGH-7",
            OutputProblem("reviewer", "the reviewer is spec but the file name says quality"),
        ),
        (
            "AGH-7",
            "spec-r2.json",
            "AGH-7",
            OutputProblem("round", "the round is 1 but the file name says 2"),
        ),
        (
            "AGH-7",
            "spec-r1.json",
            "AGH-8",
            OutputProblem("ticket", "the ticket is AGH-7 but the folder is AGH-8"),
        ),
        (
            "AGS-7",
            "spec-r1.json",
            "agſ-7",
            OutputProblem("ticket", "the ticket is AGS-7 but the folder is agſ-7"),
        ),
        (
            "AGI-7",
            "spec-r1.json",
            "agı-7",
            OutputProblem("ticket", "the ticket is AGI-7 but the folder is agı-7"),
        ),
    ],
    ids=["other reviewer", "other round", "other folder", "long s folder", "dotless i folder"],
)
def test_reports_mismatch_when_review_file_name_differs(
    *, ticket: str, file_name: str, folder_name: str, problem: OutputProblem
) -> None:
    problems = named_review_problems(
        a_review_document(ticket=ticket), file_name=file_name, folder_name=folder_name
    )

    assert problems == (problem,)


@pytest.mark.parametrize(
    ("document", "file_name", "folder_name"),
    [
        (a_review_document(), "spec-r1.json", "agh-7"),
        (a_review_document(ticket="agh-7"), "spec-r1.json", "AGH-7"),
        (a_review_document(reviewer="quality", round=9999), "quality-r9999.json", "AGH-7"),
    ],
    ids=["lower-case folder", "lower-case ticket", "quality round 9999"],
)
def test_accepts_folder_case_when_review_file_name_matches(
    document: dict[str, object], file_name: str, folder_name: str
) -> None:
    assert named_review_problems(document, file_name=file_name, folder_name=folder_name) == ()


@pytest.mark.parametrize(
    ("file_name", "echo"),
    [
        ("spec.json", "spec.json"),
        ("spec-r0.json", "spec-r0.json"),
        ("style-r1.json", "style-r1.json"),
        ("spec-r01.json", "spec-r01.json"),
        ("spec-r1.md", "spec-r1.md"),
        ("spec-r10000.json", "spec-r10000.json"),
        ("spec-r1\n.json", "spec-r1\\n.json"),
        ("x" * 100 + ".json", "x" * 79 + "…"),
    ],
    ids=[
        "no round",
        "round 0",
        "unknown reviewer",
        "leading zero",
        "not json",
        "round 10000",
        "control character",
        "long name",
    ],
)
def test_reports_root_when_review_file_name_unknown(file_name: str, echo: str) -> None:
    problems = named_review_problems(
        a_review_document(reviewer="quality", round=3), file_name=file_name
    )

    message = (
        f"the file name {echo} is not spec-r<N>.json or quality-r<N>.json"
        " (N from 1 to 9999, no leading zero)"
    )
    assert problems == (OutputProblem("$", message),)


def review_check(content: bytes) -> tuple[OutputProblem, ...]:
    return review_problems(content, file_name=REVIEW_FILE, folder_name=REVIEW_FOLDER)


def eval_check(content: bytes) -> tuple[OutputProblem, ...]:
    return eval_problems(content, file_name=EVAL_FILE, sibling_head=a_sibling_head(), record=None)


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
@pytest.mark.parametrize("check", [review_check, eval_check], ids=["review", "eval"])
def test_reports_one_root_problem_when_bytes_unusable(
    content: bytes, check: Callable[[bytes], tuple[OutputProblem, ...]]
) -> None:
    problems = check(content)

    assert [problem.path for problem in problems] == ["$"]
    assert "\n" not in problems[0].message
    assert problems[0].message


def a_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "ac": "AC-139.1",
        "command": "uv run pytest packages/core/tests/unit/features -q",
        "exit_code": 0,
        "status": "pass",
        "summary": "Every case passes.",
    }
    return result | overrides


def a_gate(**overrides: object) -> dict[str, object]:
    gate: dict[str, object] = {
        "repo": "agent-hub",
        "name": "check-fast",
        "exit_code": 0,
        "status": "pass",
    }
    return gate | overrides


def an_eval_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "agent-hub/eval/1",
        "delivery": "agh-7",
        "verdict": "SHIP",
        "commit": "feb9c4c",
        "tickets": ["AGH-7"],
        "acs": ["AC-139.1"],
        "results": [a_result()],
        "gates": [a_gate()],
        "red_on_parent": [{"test": "tests/unit/test_x.py::test_y_when_z", "failed_on_base": True}],
        "owner_steps": [],
    }
    return document | overrides


def a_sibling_head(**fields: str) -> bytes:
    """The head of ``evals/agh-7.md`` whose frontmatter matches ``an_eval_document()``."""
    frontmatter = {
        "type": "eval",
        "delivery": "agh-7",
        "verdict": "SHIP",
        "commit": "feb9c4c",
        "tickets": "[AGH-7]",
        "acs": "[AC-139.1]",
    } | fields
    lines = "".join(f"{name}: {value}\n" for name, value in frontmatter.items())
    return f"---\n{lines}---\n# Eval\n".encode()


def eval_problems_of(
    document: object, *, sibling_head: bytes | None = None
) -> tuple[OutputProblem, ...]:
    head = a_sibling_head() if sibling_head is None else sibling_head
    return eval_problems(
        review_bytes(document), file_name=EVAL_FILE, sibling_head=head, record=None
    )


@pytest.mark.parametrize(
    ("document", "sibling_head"),
    [
        (an_eval_document(), a_sibling_head()),
        (
            an_eval_document(acs="all", owner_steps=["Rotate the token."]),
            a_sibling_head(acs="all"),
        ),
        (an_eval_document(acs=[]), a_sibling_head(acs="[]")),
        (
            an_eval_document(
                verdict="NO-SHIP",
                results=[a_result(exit_code=None, status="not-run")],
                gates=[a_gate(exit_code=None, status="not-run")],
                red_on_parent=[{"test": "t", "failed_on_base": None}],
            ),
            a_sibling_head(verdict="NO-SHIP"),
        ),
    ],
    ids=["ac list", "all acs with owner steps", "tickets only", "nulls"],
)
def test_accepts_valid_eval_when_sibling_matches(
    document: dict[str, object], sibling_head: bytes
) -> None:
    assert eval_problems_of(document, sibling_head=sibling_head) == ()


def test_freezes_models_when_valid_eval_parsed() -> None:
    evaluation = EvalOutput.model_validate(an_eval_document())

    with pytest.raises(ValidationError):
        evaluation.verdict = "NO-SHIP"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        evaluation.results[0].status = "fail"  # type: ignore[misc]
    assert isinstance(evaluation.results[0], AcResult)
    assert evaluation.schema_id == "agent-hub/eval/1"
    assert evaluation.acs == ("AC-139.1",)


# One row per shape rule an eval breaks, and the path of its one problem.
EVAL_SHAPE_BROKEN: list[tuple[dict[str, object], str]] = [
    (an_eval_document(schema="agent-hub/eval/2"), "schema"),
    (an_eval_document(verdict="MAYBE"), "verdict"),
    (an_eval_document(results=[a_result(status="skipped")]), "results[0].status"),
    (an_eval_document(results=[a_result(exit_code="1")]), "results[0].exit_code"),
    (an_eval_document(results=[a_result(exit_code=True)]), "results[0].exit_code"),
    (an_eval_document(gates=[a_gate(exit_code=256)]), "gates[0].exit_code"),
    (an_eval_document(acs="some"), "acs"),
    (an_eval_document(acs=3), "acs"),
    (an_eval_document(acs=["a b"]), "acs[0]"),
    (an_eval_document(delivery="ABC 12"), "delivery"),
    (
        an_eval_document(results=[a_result(ac=f"A{index}") for index in range(301)]),
        "results",
    ),
    (an_eval_document(results=[a_result(command="c" * 2001)]), "results[0].command"),
    (without(an_eval_document(), "gates"), "gates"),
    (
        an_eval_document(red_on_parent=[{"test": "t", "failed_on_base": 1}]),
        "red_on_parent[0].failed_on_base",
    ),
    (an_eval_document(owner_steps=["one\ntwo"]), "owner_steps[0]"),
    (an_eval_document(acs={}), "acs"),
    (an_eval_document(acs=None), "acs"),
    (an_eval_document(acs=True), "acs"),
    (an_eval_document(acs=[["AC-1"]]), "acs[0]"),
]
EVAL_SHAPE_BROKEN_IDS = [
    "schema version 2",
    "verdict maybe",
    "status skipped",
    "exit code string",
    "exit code true",
    "gate exit code 256",
    "acs some",
    "acs a number",
    "acs id with a space",
    "delivery with a space",
    "301 results",
    "command of 2001",
    "missing gates",
    "failed on base a number",
    "owner step with a newline",
    "acs an object",
    "acs null",
    "acs true",
    "acs a nested list",
]


@pytest.mark.parametrize(("document", "path"), EVAL_SHAPE_BROKEN, ids=EVAL_SHAPE_BROKEN_IDS)
def test_reports_one_problem_when_eval_shape_broken(document: dict[str, object], path: str) -> None:
    problems = eval_problems_of(document)

    assert [problem.path for problem in problems] == [path]
    assert all("\n" not in problem.message for problem in problems)


@pytest.mark.parametrize(
    ("document", "path"),
    [
        (an_eval_document(results=[0] * 301), "results"),
        (an_eval_document(acs=["a b"] * 301), "acs"),
        (an_eval_document(tickets=["a b"] * 101), "tickets"),
        (an_eval_document(gates=[0] * 51), "gates"),
        (an_eval_document(red_on_parent=[0] * 301), "red_on_parent"),
        (an_eval_document(owner_steps=[""] * 51), "owner_steps"),
    ],
    ids=[
        "301 bad results",
        "301 bad acs",
        "101 bad tickets",
        "51 bad gates",
        "301 bad red tests",
        "51 bad owner steps",
    ],
)
def test_reports_overlong_list_when_eval_shape_has_bad_items(
    document: dict[str, object], path: str
) -> None:
    paths = [problem.path for problem in eval_problems_of(document)]

    assert paths.count(path) == 1
    assert len(paths) > 1


def a_matching_head(document: dict[str, object]) -> bytes:
    """The head of a sibling whose verdict and ``acs`` match ``document``'s."""
    acs = document["acs"]
    acs_text = "[" + ", ".join(acs) + "]" if isinstance(acs, list) else str(acs)
    return a_sibling_head(verdict=str(document["verdict"]), acs=acs_text)


def verdict_problems_of(document: dict[str, object]) -> tuple[OutputProblem, ...]:
    return eval_problems_of(document, sibling_head=a_matching_head(document))


TWO_ACS = ["AC-139.1", "AC-139.2"]
THREE_ACS = ["AC-139.1", "AC-139.2", "AC-139.3"]


@pytest.mark.parametrize(
    "document",
    [an_eval_document(), an_eval_document(owner_steps=["Rotate the token."])],
    ids=["without owner steps", "with owner steps"],
)
def test_accepts_ship_when_eval_verdict_all_pass(document: dict[str, object]) -> None:
    assert verdict_problems_of(document) == ()


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            an_eval_document(
                acs=TWO_ACS,
                results=[a_result(), a_result(ac="AC-139.2", exit_code=1, status="fail")],
            ),
            "SHIP needs every result to pass, but results[1] is fail",
        ),
        (
            an_eval_document(
                acs=TWO_ACS,
                results=[a_result(), a_result(ac="AC-139.2", exit_code=None, status="not-run")],
            ),
            "SHIP needs every result to pass, but results[1] is not-run",
        ),
        (
            an_eval_document(gates=[a_gate(), a_gate(name="check", exit_code=1, status="fail")]),
            "SHIP needs every gate to pass, but gates[1] is fail",
        ),
        (
            an_eval_document(
                gates=[a_gate(), a_gate(name="check", exit_code=None, status="not-run")]
            ),
            "SHIP needs every gate to pass, but gates[1] is not-run",
        ),
    ],
    ids=["result fail", "result not-run", "gate fail", "gate not-run"],
)
def test_reports_verdict_when_eval_verdict_ship_rests_on_failure(
    document: dict[str, object], message: str
) -> None:
    assert verdict_problems_of(document) == (OutputProblem("verdict", message),)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (an_eval_document(acs=[], results=[]), "SHIP needs at least one result"),
        (an_eval_document(gates=[]), "SHIP needs at least one gate"),
    ],
    ids=["no results", "no gates"],
)
def test_reports_verdict_when_eval_verdict_ship_has_empty_lists(
    document: dict[str, object], message: str
) -> None:
    assert verdict_problems_of(document) == (OutputProblem("verdict", message),)


def test_reports_owner_steps_when_eval_verdict_needs_steps() -> None:
    document = an_eval_document(verdict="SHIP-WITH-OWNER-STEPS", owner_steps=[])

    assert verdict_problems_of(document) == (
        OutputProblem("owner_steps", "SHIP-WITH-OWNER-STEPS needs at least one owner step"),
    )


def test_accepts_owner_steps_verdict_when_eval_verdict_has_fail() -> None:
    document = an_eval_document(
        verdict="SHIP-WITH-OWNER-STEPS",
        results=[a_result(exit_code=1, status="fail")],
        gates=[a_gate(exit_code=2, status="fail")],
        owner_steps=["Rotate the token."],
    )

    assert verdict_problems_of(document) == ()


@pytest.mark.parametrize(
    "document",
    [
        an_eval_document(
            verdict="NO-SHIP",
            acs=THREE_ACS,
            results=[
                a_result(),
                a_result(ac="AC-139.2", exit_code=1, status="fail"),
                a_result(ac="AC-139.3", exit_code=None, status="not-run"),
            ],
            gates=[
                a_gate(),
                a_gate(name="check", exit_code=2, status="fail"),
                a_gate(name="e2e", exit_code=None, status="not-run"),
            ],
        ),
        an_eval_document(verdict="NO-SHIP", acs=[], results=[], gates=[]),
    ],
    ids=["every status", "empty lists"],
)
def test_accepts_no_ship_when_eval_verdict_mixes_statuses(document: dict[str, object]) -> None:
    assert verdict_problems_of(document) == ()


def test_ignores_red_on_parent_when_eval_verdict_checked() -> None:
    document = an_eval_document(red_on_parent=[{"test": "t", "failed_on_base": False}])

    assert verdict_problems_of(document) == ()


@pytest.mark.parametrize(
    ("document", "problem"),
    [
        (
            an_eval_document(verdict="NO-SHIP", results=[a_result(exit_code=1)]),
            OutputProblem("results[0].exit_code", "a pass needs exit code 0, not 1"),
        ),
        (
            an_eval_document(verdict="NO-SHIP", results=[a_result(exit_code=None)]),
            OutputProblem("results[0].exit_code", "a pass needs exit code 0, not null"),
        ),
        (
            an_eval_document(verdict="NO-SHIP", results=[a_result(status="not-run")]),
            OutputProblem("results[0].exit_code", "a not-run needs exit code null, not 0"),
        ),
        (
            an_eval_document(verdict="NO-SHIP", gates=[a_gate(exit_code=2)]),
            OutputProblem("gates[0].exit_code", "a pass needs exit code 0, not 2"),
        ),
        (
            an_eval_document(verdict="NO-SHIP", gates=[a_gate(status="not-run", exit_code=-1)]),
            OutputProblem("gates[0].exit_code", "a not-run needs exit code null, not -1"),
        ),
    ],
    ids=[
        "result pass exit 1",
        "result pass exit null",
        "result not-run exit 0",
        "gate pass exit 2",
        "gate not-run exit -1",
    ],
)
def test_reports_exit_code_when_eval_verdict_status_disagrees(
    document: dict[str, object], problem: OutputProblem
) -> None:
    assert verdict_problems_of(document) == (problem,)


def test_accepts_any_exit_code_when_eval_verdict_result_fails() -> None:
    document = an_eval_document(
        verdict="NO-SHIP",
        acs=TWO_ACS,
        results=[
            a_result(exit_code=0, status="fail"),
            a_result(ac="AC-139.2", exit_code=None, status="fail"),
        ],
    )

    assert verdict_problems_of(document) == ()


@pytest.mark.parametrize(
    ("loc", "path"),
    [
        (("findings", 0, "acs", "ids"), "findings[0].acs.ids"),
        (("ids",), "ids"),
        (("acs", "ids", 0), "acs[0]"),
        (("acs", "all"), "acs"),
    ],
    ids=["ids key inside a finding", "top-level ids key", "eval acs list tag", "eval acs all tag"],
)
def test_drops_only_eval_acs_tag_when_output_path_built(
    loc: tuple[int | str, ...], path: str
) -> None:
    assert output_path(loc) == path


KINDS: tuple[OutputKind, ...] = ("review", "eval")
MODELS: dict[OutputKind, type[BaseModel]] = {"review": ReviewOutput, "eval": EvalOutput}


def object_nodes(node: object) -> Iterator[dict[str, Any]]:
    """Every schema node with ``type: object``, root included."""
    if isinstance(node, list):
        for item in node:
            yield from object_nodes(item)
    elif isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from object_nodes(value)


def resolved(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """``node``, or the ``$defs`` entry its local ``$ref`` names."""
    reference = node.get("$ref")
    if reference is None:
        return node
    found: dict[str, Any] = schema["$defs"][reference.removeprefix("#/$defs/")]
    return found


def field(schema: dict[str, Any], owner: str | None, name: str) -> dict[str, Any]:
    """Property ``name`` of the root (``owner`` None) or of a ``$defs`` model, resolved."""
    model = schema if owner is None else schema["$defs"][owner]
    return resolved(schema, model["properties"][name])


@pytest.mark.parametrize("kind", KINDS)
def test_matches_export_when_shipped_schema_read(kind: OutputKind) -> None:
    shipped = files(OUTPUT_SCHEMA_PACKAGE).joinpath(OUTPUT_SCHEMA_FILES[kind]).read_bytes()

    assert shipped == export_output_schema_text(kind).encode()
    assert read_shipped_output_schema(kind) == MODELS[kind].model_json_schema()
    assert OUTPUT_SCHEMA_FILES == {"review": "review.v1.json", "eval": "eval.v1.json"}
    assert OUTPUT_SCHEMA_PACKAGE == "agent_hub.core.features"


@pytest.mark.parametrize(
    ("kind", "schema_id"), [("review", "agent-hub/review/1"), ("eval", "agent-hub/eval/1")]
)
def test_states_schema_const_when_schema_exported(kind: OutputKind, schema_id: str) -> None:
    schema = read_shipped_output_schema(kind)

    assert schema["properties"]["schema"]["const"] == schema_id
    assert "schema_id" not in json.dumps(schema)


@pytest.mark.parametrize(("kind", "objects"), [("review", 2), ("eval", 4)])
def test_forbids_extra_keys_when_schema_object_nodes_walked(kind: OutputKind, objects: int) -> None:
    nodes = list(object_nodes(read_shipped_output_schema(kind)))

    assert len(nodes) == objects
    assert all(node.get("additionalProperties") is False for node in nodes)


@pytest.mark.parametrize("kind", KINDS)
def test_requires_every_key_when_schema_exported(kind: OutputKind) -> None:
    for node in object_nodes(read_shipped_output_schema(kind)):
        assert node["required"] == list(node["properties"])


def test_states_bounds_as_literals_when_schema_exported() -> None:
    review = read_shipped_output_schema("review")
    evaluation = read_shipped_output_schema("eval")
    eval_acs = resolved(evaluation, evaluation["properties"]["acs"])["oneOf"]

    assert review["properties"]["findings"]["maxItems"] == 100
    assert review["$defs"]["ReviewFinding"]["properties"]["acs"]["maxItems"] == 50
    assert evaluation["properties"]["tickets"]["maxItems"] == 100
    assert [arm.get("maxItems") for arm in eval_acs] == [None, 300]
    assert evaluation["properties"]["results"]["maxItems"] == 300
    assert evaluation["properties"]["gates"]["maxItems"] == 50
    assert evaluation["properties"]["red_on_parent"]["maxItems"] == 300
    assert evaluation["properties"]["owner_steps"]["maxItems"] == 50
    assert field(review, "ReviewFinding", "what")["maxLength"] == 1000
    assert field(evaluation, "AcResult", "command")["maxLength"] == 2000
    assert field(review, "ReviewFinding", "path")["maxLength"] == 512
    assert field(evaluation, "GateResult", "name")["maxLength"] == 64
    assert MAX_OUTPUT_BYTES == 524_288
    assert MAX_RECORD_BYTES == 1_048_576
    assert ECHO_LIMIT == 80


def test_requires_text_when_schema_exported() -> None:
    review = read_shipped_output_schema("review")
    evaluation = read_shipped_output_schema("eval")
    owner_step = resolved(evaluation, evaluation["properties"]["owner_steps"]["items"])
    texts = [
        field(review, "ReviewFinding", "what"),
        field(review, "ReviewFinding", "expected"),
        field(review, "ReviewFinding", "path"),
        field(evaluation, "AcResult", "command"),
        field(evaluation, "AcResult", "summary"),
        owner_step,
        field(evaluation, "RedOnParent", "test"),
        field(evaluation, "GateResult", "repo"),
        field(evaluation, "GateResult", "name"),
    ]

    assert [text["minLength"] for text in texts] == [1] * 9


@pytest.mark.parametrize("kind", KINDS)
def test_passes_meta_schema_when_shipped_schemas_checked(kind: OutputKind) -> None:
    schema = read_shipped_output_schema(kind)

    Draft202012Validator.check_schema(schema)
    assert "$schema" not in schema


@pytest.mark.parametrize(
    ("kind", "sample"),
    [
        ("review", a_review_document()),
        ("review", a_review_document(verdict="FAIL", findings=[a_finding(line=None)])),
        ("eval", an_eval_document()),
        ("eval", an_eval_document(acs="all")),
        ("eval", an_eval_document(acs=[])),
    ],
    ids=["review", "review with a null line", "eval", "eval all acs", "eval by tickets"],
)
def test_validates_sample_when_meta_schema_checked(
    kind: OutputKind, sample: dict[str, object]
) -> None:
    validator = Draft202012Validator(read_shipped_output_schema(kind))

    assert list(validator.iter_errors(sample)) == []
    errors = list(validator.iter_errors(sample | {"colour": "red"}))
    assert [error.validator for error in errors] == ["additionalProperties"]


# Every broken-shape row above, which the shipped schema must refuse as the models do. No row is
# skipped: none is a case JSON Schema cannot state (an integer-valued float such as 1.0, a pattern
# field ending in one "\n" that re.search lets through, a lone surrogate, a duplicate key or NaN).
SCHEMA_REJECTS: list[tuple[OutputKind, dict[str, object]]] = [
    *(("review", document) for document, _ in REVIEW_SHAPE_BROKEN),
    *(("eval", document) for document, _ in EVAL_SHAPE_BROKEN),
]
SCHEMA_REJECTS_IDS = [
    *(f"review {name}" for name in REVIEW_SHAPE_BROKEN_IDS),
    *(f"eval {name}" for name in EVAL_SHAPE_BROKEN_IDS),
]


@pytest.mark.parametrize(("kind", "document"), SCHEMA_REJECTS, ids=SCHEMA_REJECTS_IDS)
def test_rejects_broken_shape_when_shipped_schema_validates(
    kind: OutputKind, document: dict[str, object]
) -> None:
    validator = Draft202012Validator(read_shipped_output_schema(kind))

    assert list(validator.iter_errors(json.loads(review_bytes(document)))) != []


def a_head_for(document: dict[str, object], **fields: str) -> bytes:
    """The head of a sibling whose verdict, tickets and ``acs`` match ``document``'s."""
    lists = {
        name: "[" + ", ".join(map(str, value)) + "]" if isinstance(value, list) else str(value)
        for name, value in document.items()
        if name in {"tickets", "acs"}
    }
    return a_sibling_head(verdict=str(document["verdict"]), **lists | fields)


def scope_problems_of(
    document: dict[str, object], *, record: bytes | None = None, file_name: str = EVAL_FILE
) -> tuple[OutputProblem, ...]:
    """The problems of ``document`` beside a matching sibling, with ``record`` as features.json."""
    head = a_head_for(document, delivery=file_name.removesuffix(".json"))
    content = review_bytes(document)
    return eval_problems(content, file_name=file_name, sibling_head=head, record=record)


def results_for(*acs: str) -> list[dict[str, object]]:
    return [a_result(ac=ac) for ac in acs]


@pytest.mark.parametrize(
    ("results", "problem"),
    [
        (
            results_for("A1"),
            OutputProblem("results", "no result for A2, which the scope names"),
        ),
        (
            results_for("A1", "A2", "A3"),
            OutputProblem("results", "the result for A3 is outside the scope"),
        ),
        (
            results_for("A1", "A2", "A1"),
            OutputProblem("results", "more than one result for A1"),
        ),
    ],
    ids=["missing", "extra", "repeated"],
)
def test_reports_results_when_eval_scope_not_covered_without_record(
    results: list[dict[str, object]], problem: OutputProblem
) -> None:
    document = an_eval_document(acs=["A1", "A2"], results=results)

    assert scope_problems_of(document) == (problem,)


@pytest.mark.parametrize("acs", ["all", []], ids=["all acs", "tickets only"])
def test_accepts_distinct_results_when_eval_scope_all_without_record(acs: object) -> None:
    document = an_eval_document(acs=acs, results=results_for("A1", "A2", "A9"))

    assert scope_problems_of(document) == ()


@pytest.mark.parametrize("acs", ["all", []], ids=["all acs", "tickets only"])
def test_reports_repeated_result_when_eval_scope_all_without_record(acs: object) -> None:
    document = an_eval_document(acs=acs, results=results_for("A1", "A2", "A1", "A1"))

    assert scope_problems_of(document) == (OutputProblem("results", "more than one result for A1"),)


@pytest.mark.parametrize(
    ("document", "head", "problem"),
    [
        (
            an_eval_document(),
            a_sibling_head(verdict="NO-SHIP"),
            OutputProblem("verdict", "the verdict is SHIP but evals/agh-7.md says NO-SHIP"),
        ),
        (
            an_eval_document(delivery="agh-8"),
            a_sibling_head(),
            OutputProblem("delivery", "the delivery is agh-8 but the file name says agh-7"),
        ),
        (
            an_eval_document(),
            a_sibling_head(tickets="[AGH-7, AGH-8]"),
            OutputProblem(
                "tickets", "the tickets are [AGH-7] but evals/agh-7.md says [AGH-7, AGH-8]"
            ),
        ),
        (
            an_eval_document(),
            a_sibling_head(acs="all"),
            OutputProblem("acs", "the acs are [AC-139.1] but evals/agh-7.md says all"),
        ),
        (
            an_eval_document(),
            a_sibling_head(commit="1234567"),
            OutputProblem("commit", "the commit is feb9c4c but evals/agh-7.md says 1234567"),
        ),
        (
            an_eval_document(),
            a_sibling_head(commit=""),
            OutputProblem("commit", "the commit is feb9c4c but evals/agh-7.md has none"),
        ),
    ],
    ids=["verdict", "delivery", "tickets", "acs", "commit", "no commit"],
)
def test_reports_field_when_eval_sibling_differs(
    document: dict[str, object], head: bytes, problem: OutputProblem
) -> None:
    assert eval_problems_of(document, sibling_head=head) == (problem,)


def test_accepts_reordered_lists_when_eval_sibling_matches() -> None:
    document = an_eval_document(
        tickets=["AGH-7", "AGH-8"], acs=["A1", "A2"], results=results_for("A2", "A1")
    )
    head = a_sibling_head(tickets="[AGH-8, AGH-7]", acs="[A2, A1]")

    assert eval_problems_of(document, sibling_head=head) == ()


def test_reports_root_when_eval_sibling_missing() -> None:
    content = review_bytes(an_eval_document())

    problems = eval_problems(content, file_name=EVAL_FILE, sibling_head=None, record=None)

    assert problems == (OutputProblem("$", "evals/agh-7.md is missing"),)


@pytest.mark.parametrize(
    ("head", "message"),
    [
        (b"# Eval\n", "evals/agh-7.md: no frontmatter"),
        (
            a_sibling_head(verdict="MAYBE"),
            "evals/agh-7.md: verdict must be one of SHIP, SHIP-WITH-OWNER-STEPS, NO-SHIP",
        ),
        (a_sibling_head(type="note"), "evals/agh-7.md: type is note, not eval"),
        (
            a_sibling_head(delivery="agh-8"),
            "evals/agh-7.md: delivery agh-8 does not match the file name",
        ),
    ],
    ids=["no frontmatter", "verdict maybe", "another type", "another delivery"],
)
def test_reports_root_when_eval_sibling_malformed(head: bytes, message: str) -> None:
    assert eval_problems_of(an_eval_document(), sibling_head=head) == (OutputProblem("$", message),)


def test_reads_head_only_when_eval_sibling_long() -> None:
    head = a_sibling_head() + b"x" * 100_000 + b"\xff"

    assert eval_problems_of(an_eval_document(), sibling_head=head) == ()


def test_reports_delivery_when_eval_sibling_stem_differs() -> None:
    document = an_eval_document(delivery="abc-13")
    head = a_head_for(document, delivery="abc-12")
    content = review_bytes(document)

    problems = eval_problems(content, file_name="abc-12.json", sibling_head=head, record=None)

    assert problems == (
        OutputProblem("delivery", "the delivery is abc-13 but the file name says abc-12"),
    )


def test_accepts_rerun_pair_when_eval_sibling_matches() -> None:
    document = an_eval_document(delivery="abc-12-r2")

    assert scope_problems_of(document, file_name="abc-12-r2.json") == ()


def test_reports_duplicates_when_eval_sibling_lists_repeat() -> None:
    document = an_eval_document(tickets=["AGH-7", "AGH-8", "AGH-7"], acs=["AC-139.1", "AC-139.1"])
    head = a_sibling_head(tickets="[AGH-7, AGH-8]")

    assert eval_problems_of(document, sibling_head=head) == (
        OutputProblem("tickets[2]", "the ticket AGH-7 repeats tickets[0]"),
        OutputProblem("acs[1]", "the AC AC-139.1 repeats acs[0]"),
    )


@pytest.mark.parametrize(
    ("file_name", "echo"),
    [
        ("AGH-7.json", "AGH-7.json"),
        ("agh-7.md", "agh-7.md"),
        ("agh-7", "agh-7"),
        ("agh-7\n.json", "agh-7\\n.json"),
        ("agh_7.json", "agh_7.json"),
        ("a" * 64 + ".json", "a" * 64 + ".json"),
        ("a" * 100 + ".json", "a" * 79 + "…"),
    ],
    ids=["upper case", "not json", "no suffix", "control character", "underscore", "64", "long"],
)
def test_reports_root_when_eval_sibling_stem_not_delivery(file_name: str, echo: str) -> None:
    content = review_bytes(an_eval_document(delivery="agh-9"))

    problems = eval_problems(
        content, file_name=file_name, sibling_head=a_sibling_head(), record=None
    )

    message = f"the file name {echo} is not <delivery>.json ([a-z0-9][a-z0-9-]{{0,62}})"
    assert problems == (OutputProblem("$", message),)


def a_record_ac(ac_id: str, **overrides: object) -> dict[str, object]:
    return {"id": ac_id, "description": "A criterion.", "passes": False} | overrides


def record_bytes(acs: list[dict[str, object]]) -> bytes:
    tickets = [{"key": "T1"}, {"key": "T2", "id": "AGH-9"}]
    return json.dumps({"linear": ["AGH-9"], "tickets": tickets, "acs": acs}).encode()


# Live A1 (no ticket), A2 (ticket T1), A3 (ticket T2, plan key of AGH-9); withdrawn A4 (T1).
RECORD = record_bytes(
    [
        a_record_ac("A1"),
        a_record_ac("A2", ticket="T1"),
        a_record_ac("A3", ticket="T2"),
        a_record_ac("A4", ticket="T1", withdrawn=True),
    ]
)


def test_covers_live_acs_when_eval_record_scope_all() -> None:
    document = an_eval_document(acs="all", results=results_for("A1", "A2", "A3"))

    assert scope_problems_of(document, record=RECORD) == ()


@pytest.mark.parametrize(
    ("results", "problem"),
    [
        (
            results_for("A1", "A2"),
            OutputProblem("results", "no result for A3, which the scope names"),
        ),
        (
            results_for("A1", "A2", "A3", "A4"),
            OutputProblem("results", "the result for A4 names a withdrawn AC"),
        ),
        (
            results_for("A1", "A2", "A3", "A9"),
            OutputProblem("results", "the result for A9 is outside the scope"),
        ),
    ],
    ids=["missing A3", "adding withdrawn A4", "adding unknown A9"],
)
def test_reports_results_when_eval_record_scope_misses_or_adds(
    results: list[dict[str, object]], problem: OutputProblem
) -> None:
    document = an_eval_document(acs="all", results=results)

    assert scope_problems_of(document, record=RECORD) == (problem,)


@pytest.mark.parametrize(
    ("tickets", "results", "problems"),
    [
        (["T1"], results_for("A2"), ()),
        (["AGH-9"], results_for("A3"), ()),
        (["agh-9"], results_for("A3"), ()),
        (["T2"], results_for("A3"), ()),
        (
            ["T1"],
            results_for("A1", "A2"),
            (OutputProblem("results", "the result for A1 is outside the scope"),),
        ),
        (
            ["AGH-9"],
            results_for("A2"),
            (
                OutputProblem("results", "no result for A3, which the scope names"),
                OutputProblem("results", "the result for A2 is outside the scope"),
            ),
        ),
    ],
    ids=["T1 is A2", "tracker id is A3", "id in lower case", "plan key is A3", "A1", "A2"],
)
def test_expands_tickets_when_eval_record_scope_by_ticket(
    tickets: list[str], results: list[dict[str, object]], problems: tuple[OutputProblem, ...]
) -> None:
    document = an_eval_document(tickets=tickets, acs=[], results=results)

    assert scope_problems_of(document, record=RECORD) == problems


@pytest.mark.parametrize(
    ("acs", "results", "problem"),
    [
        (["A1", "A4"], ["A1"], OutputProblem("acs", "A4 is withdrawn in features.json")),
        (["A1", "A4"], ["A1", "A4"], OutputProblem("acs", "A4 is withdrawn in features.json")),
        (["A9"], ["A9"], OutputProblem("acs", "A9 is not an AC of features.json")),
    ],
    ids=["withdrawn", "withdrawn with its result", "unknown"],
)
def test_reports_acs_when_eval_record_names_withdrawn_or_unknown(
    acs: list[str], results: list[str], problem: OutputProblem
) -> None:
    document = an_eval_document(acs=acs, results=results_for(*results))

    assert scope_problems_of(document, record=RECORD) == (problem,)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (b"{not json", "features.json could not be parsed (not valid JSON: "),
        (b"[]", "features.json could not be parsed ("),
        (b'{"linear": []}', "features.json could not be parsed (acs: Field required)"),
        (b"\xff", "features.json could not be parsed (not UTF-8 text: "),
    ],
    ids=["not json", "an array", "not a record", "not utf-8"],
)
def test_reports_one_problem_when_eval_record_unparseable(record: bytes, message: str) -> None:
    document = an_eval_document(acs="all", results=results_for("A1", "A2", "A9"))

    problems = scope_problems_of(document, record=record)

    assert [problem.path for problem in problems] == ["$"]
    assert problems[0].message.startswith(message)
    assert "\n" not in problems[0].message


@pytest.mark.parametrize(
    ("size", "problems"),
    [
        (MAX_RECORD_BYTES, ()),
        (MAX_RECORD_BYTES + 1, (OutputProblem("$", "features.json is over 1048576 bytes"),)),
    ],
    ids=["at the bound", "one byte over"],
)
def test_refuses_record_when_eval_record_over_bound(
    size: int, problems: tuple[OutputProblem, ...]
) -> None:
    record = RECORD.ljust(size)
    document = an_eval_document(acs="all", results=results_for("A1", "A2", "A3"))

    assert scope_problems_of(document, record=record) == problems


def test_cuts_echoed_id_when_eval_record_names_long_id() -> None:
    record = record_bytes([a_record_ac("x" * 100)])
    document = an_eval_document(verdict="NO-SHIP", acs="all", results=[], gates=[])

    assert scope_problems_of(document, record=record) == (
        OutputProblem("results", "no result for " + "x" * 79 + "…, which the scope names"),
    )


def test_reports_all_problems_in_order_when_review_breaks_many_rules() -> None:
    document = a_review_document(
        round=0, commit="XYZ", verdict="FAIL", findings=[a_finding(kind="typo")]
    )

    problems = problems_of(document)

    assert [problem.path for problem in problems] == [
        "round",
        "commit",
        "findings[0].kind",
        "verdict",
    ]
    assert problems[-1] == OutputProblem(
        "verdict", "the verdict is FAIL but no finding is blocking"
    )


def test_reports_all_problems_in_order_when_eval_breaks_many_rules() -> None:
    document = an_eval_document(
        tickets=["T1"],
        acs="all",
        results=[
            a_result(ac="A1", summary=""),
            a_result(ac="A2", exit_code=1, status="fail"),
            *results_for("A3", "A4"),
        ],
        gates=[a_gate(name="")],
    )
    head = a_head_for(document, tickets="[T2]", commit="1234567")
    content = review_bytes(document)

    problems = eval_problems(content, file_name=EVAL_FILE, sibling_head=head, record=RECORD)

    assert [problem.path for problem in problems] == [
        "results[0].summary",
        "gates[0].name",
        "verdict",
        "tickets",
        "commit",
        "results",
    ]
    assert problems[2:] == (
        OutputProblem("verdict", "SHIP needs every result to pass, but results[1] is fail"),
        OutputProblem("tickets", "the tickets are [T1] but evals/agh-7.md says [T2]"),
        OutputProblem("commit", "the commit is feb9c4c but evals/agh-7.md says 1234567"),
        OutputProblem("results", "the result for A4 names a withdrawn AC"),
    )


def json_values() -> st.SearchStrategy[object]:
    scalars = st.none() | st.booleans() | st.integers() | st.text(max_size=20)
    floats = st.floats(allow_nan=False, allow_infinity=False)
    return st.recursive(
        scalars | floats,
        lambda children: (
            st.lists(children, max_size=4)
            | st.dictionaries(st.text(max_size=8), children, max_size=4)
        ),
        max_leaves=20,
    )


OUTPUT_KEYS = sorted({*a_review_document(), *an_eval_document(), *a_finding(), *a_result()})
RECORDS = [None, RECORD, b"{}", b"[]"]


@settings(max_examples=200, deadline=None)
@given(
    content=st.binary(max_size=400),
    file_name=st.text(max_size=40),
    sibling_head=st.none() | st.binary(max_size=200),
    record=st.none() | st.binary(max_size=200),
)
def test_never_raises_when_arbitrary_bytes_given_property(
    *, content: bytes, file_name: str, sibling_head: bytes | None, record: bytes | None
) -> None:
    review = review_problems(content, file_name=file_name, folder_name=file_name)
    evaluation = eval_problems(
        content, file_name=file_name, sibling_head=sibling_head, record=record
    )

    assert all("\n" not in problem.message for problem in (*review, *evaluation))


@settings(max_examples=300, deadline=None)
@given(
    overrides=st.dictionaries(
        st.sampled_from(OUTPUT_KEYS) | st.text(max_size=8), json_values(), max_size=6
    ),
    record=st.sampled_from(RECORDS),
)
def test_never_raises_when_arbitrary_object_given_property(
    overrides: dict[str, object], record: bytes | None
) -> None:
    review = problems_of(a_review_document(**overrides))
    evaluation = scope_problems_of(an_eval_document(**overrides), record=record)
    raw = eval_problems(
        review_bytes(overrides), file_name=EVAL_FILE, sibling_head=a_sibling_head(), record=record
    )

    assert all("\n" not in problem.message for problem in (*review, *evaluation, *raw))
