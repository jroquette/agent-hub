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


@pytest.mark.parametrize(
    ("document", "path"),
    [
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
    ],
    ids=[
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
    ],
)
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
