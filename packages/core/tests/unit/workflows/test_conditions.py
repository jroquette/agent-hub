"""The `when:` grammar and its evaluation (AC-213.4)."""

from decimal import Decimal

import pytest

from agent_hub.core.workflows.conditions import (
    Atom,
    ConditionParseError,
    WhenFail,
    WhenSkip,
    WhenValue,
    evaluate_when,
    parse_condition,
)
from agent_hub.core.workflows.substitution import InputRef, NodeRef, NodeResult, RefContext

CONTEXT = RefContext(
    inputs={"mode": "fast", "count": 3, "ratio": "1.0", "flag": True, "none": None, "word": "it's"},
    nodes={
        "plan": NodeResult(state="completed", output={"score": 80, "verdict": "Pass ", "n": "080"}),
        "triage-step": NodeResult(state="completed", output="bug"),
        "lint": NodeResult(state="skipped"),
        "build": NodeResult(state="failed", output="boom"),
    },
)


def holds(expr: str, context: RefContext = CONTEXT) -> bool:
    result = evaluate_when(expr, context)
    assert isinstance(result, WhenValue), result
    return result.holds


# --- parsing ---------------------------------------------------------------------------------


def test_parses_atom_when_reference_operator_and_literal_given() -> None:
    condition = parse_condition("$plan.output.score >= 80 && $INPUTS.mode == 'fast'")
    assert condition.clauses == (
        (
            Atom(NodeRef("plan", ("score",)), "$plan.output.score", ">=", Decimal(80)),
            Atom(InputRef("mode"), "$INPUTS.mode", "==", "fast"),
        ),
    )


def test_splits_on_or_first_when_and_and_or_mix() -> None:
    condition = parse_condition("$INPUTS.a == 1 && $INPUTS.b == 2 || $INPUTS.c == 3")
    assert [len(clause) for clause in condition.clauses] == [2, 1]


def test_reads_longest_operator_when_operators_share_a_prefix() -> None:
    condition = parse_condition("$INPUTS.count<=3&&$INPUTS.count!=4")
    assert [atom.op for atom in condition.clauses[0]] == ["<=", "!="]


@pytest.mark.parametrize(
    ("literal", "value"),
    [
        ("'a && b || c'", "a && b || c"),
        ("'$plan.output'", "$plan.output"),
        ("''", ""),
        ("'it''s'", "it's"),
        ("''''", "'"),
        ("true", "true"),
        ("false", "false"),
        ("-2.50", Decimal("-2.50")),
    ],
)
def test_reads_literal_as_data_when_quoted_number_or_boolean(literal: str, value: object) -> None:
    (atom,) = parse_condition(f"$INPUTS.mode == {literal}").clauses[0]
    assert atom.literal == value


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "   ",
        "$INPUTS.mode",
        "$INPUTS.mode ==",
        "$INPUTS.mode == 'fast' &&",
        "|| $INPUTS.mode == 'fast'",
        "($INPUTS.mode == 'fast')",
        "!$INPUTS.flag == true",
        "$INPUTS.count + 1 > 3",
        "len($INPUTS.mode) > 3",
        "'fast' == $INPUTS.mode",
        "$INPUTS.mode == fast",
        "$INPUTS.mode == 'fast",
        "$INPUTS.mode = 'fast'",
        "$INPUTS.mode == 'a' 'b'",
        "$INPUTS.mode == 1.",
        "$INPUTS.mode == 1e3",
        "$INPUTS.mode == truey",
        "$INPUTS.mode.deep == 'x'",
        "$plan.output[0] == 'x'",
        "$plan.score == 80",
        "$INPUTS.count > 'high'",
        "$INPUTS.count <= true",
        "$INPUTS.count > ''",
        "$INPUTS.count > '80'",
    ],
)
def test_refuses_expression_when_outside_the_grammar(expr: str) -> None:
    with pytest.raises(ConditionParseError):
        parse_condition(expr)


# --- evaluation ------------------------------------------------------------------------------


def test_binds_and_tighter_when_or_follows() -> None:
    assert holds("$INPUTS.mode == 'slow' && $INPUTS.count == 3 || $INPUTS.count == 3")
    assert not holds("$INPUTS.mode == 'slow' && $INPUTS.count == 3 || $INPUTS.count == 4")


def test_compares_exact_text_when_literal_is_quoted() -> None:
    assert holds("$plan.output.verdict == 'Pass '")
    assert not holds("$plan.output.verdict == 'pass '")
    assert not holds("$plan.output.verdict == 'Pass'")
    assert holds("$triage-step.output != 'feature'")
    assert holds("$INPUTS.word == 'it''s'")


def test_compares_numerically_when_literal_is_a_number() -> None:
    assert holds("$INPUTS.ratio == 1")
    assert holds("$INPUTS.count == 3.0")
    assert holds("$plan.output.score > 79.5 && $plan.output.score <= 80")
    assert holds("$INPUTS.count >= 3 && $INPUTS.count < 4 && $INPUTS.count != 2")


def test_compares_canonical_text_when_value_is_boolean_or_null() -> None:
    assert holds("$INPUTS.flag == true")
    assert holds("$INPUTS.flag == 'true'")
    assert holds("$INPUTS.none == ''")


def test_reads_empty_text_when_producer_skipped() -> None:
    assert holds("$lint.output == '' && $lint.output.field == ''")


def test_skips_with_parse_error_when_value_is_not_a_number() -> None:
    for expr in ("$INPUTS.mode > 3", "$INPUTS.mode == 3", "$plan.output.n == 80"):
        result = evaluate_when(expr, CONTEXT)
        assert isinstance(result, WhenSkip)
        assert result.cause == "condition_parse_error"


def test_skips_with_parse_error_when_expression_malformed() -> None:
    result = evaluate_when("$INPUTS.mode == fast", CONTEXT)
    assert isinstance(result, WhenSkip)
    assert result.cause == "condition_parse_error"


def test_skips_with_parse_error_when_bad_atom_would_be_short_circuited() -> None:
    result = evaluate_when("$INPUTS.count == 3 || $INPUTS.mode > 'x'", CONTEXT)
    assert isinstance(result, WhenSkip)


@pytest.mark.parametrize(
    ("expr", "code"),
    [
        ("$INPUTS.missing == 'x'", "unknown_input"),
        ("$build.output == 'boom'", "producer_failed"),
        ("$ghost.output == 'x'", "unknown_node"),
    ],
)
def test_fails_when_reference_cannot_resolve(expr: str, code: str) -> None:
    result = evaluate_when(expr, CONTEXT)
    assert isinstance(result, WhenFail)
    assert result.error.code == code


def test_never_resolves_reference_when_its_clause_is_short_circuited() -> None:
    assert holds("$INPUTS.count == 3 || $INPUTS.missing == 'x'")
    assert not holds("$INPUTS.count == 4 && $build.output == 'x'")


def test_compares_canonical_json_when_field_is_an_object_or_array() -> None:
    context = RefContext(
        inputs={},
        nodes={"plan": NodeResult(state="completed", output={"a": [1, {"z": 1, "b": 2}]})},
    )
    assert holds("""$plan.output.a == '[1,{"b":2,"z":1}]'""", context)
    assert holds("""$plan.output == '{"a":[1,{"b":2,"z":1}]}'""", context)


def test_refuses_expression_when_left_side_is_a_with_value() -> None:
    with pytest.raises(ConditionParseError):
        parse_condition("$WITH.plan == 'x'")


def test_refuses_number_when_digits_are_not_ascii() -> None:
    with pytest.raises(ConditionParseError):
        parse_condition("$INPUTS.count == \u0663")
    context = RefContext(inputs={"count": "1\u0663"}, nodes={})
    assert isinstance(evaluate_when("$INPUTS.count == 1", context), WhenSkip)


def test_fails_when_value_is_not_finite() -> None:
    context = RefContext(inputs={"big": float("inf")}, nodes={})
    result = evaluate_when("$INPUTS.big == 'x'", context)
    assert isinstance(result, WhenFail)
    assert result.error.code == "non_finite"


def test_bounds_echoed_expression_when_parse_fails() -> None:
    expr = "$INPUTS.mode == fast " + "x" * 2000
    result = evaluate_when(expr, CONTEXT)
    assert isinstance(result, WhenSkip)
    assert len(result.detail) < 200
    with pytest.raises(ConditionParseError) as caught:
        parse_condition("$" + "a" * 2000 + ".outpu == 1")
    assert len(str(caught.value)) < 200


def test_bounds_echoed_reference_when_evaluation_fails() -> None:
    long_ref = "$INPUTS." + "n" * 5000
    failed = evaluate_when(long_ref + " == 'x'", CONTEXT)
    assert isinstance(failed, WhenFail)
    assert len(str(failed.error)) < 300
    context = RefContext(inputs={"n" * 5000: "word"}, nodes={})
    skipped = evaluate_when(long_ref + " == 1", context)
    assert isinstance(skipped, WhenSkip)
    assert len(skipped.detail) < 300
