"""The agent output checks: a review or eval JSON document's shape, every problem at its path."""

import json
from collections.abc import Callable, Iterator
from importlib.resources import files
from typing import Any

import pytest
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
    ticket: str, file_name: str, folder_name: str, problem: OutputProblem
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
