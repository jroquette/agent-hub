"""Output references, canonical value text and single-pass substitution (AC-213.5)."""

import pytest

from agent_hub.core.workflows.substitution import (
    InputRef,
    LoopPrevRef,
    NodeRef,
    NodeResult,
    RefContext,
    SubstitutionError,
    WithRef,
    canonical_text,
    find_refs,
    parse_ref,
    render,
    render_argv,
)

PLAN = NodeResult(
    state="completed",
    output={"summary": "do it", "count": 3, "ok": True, "items": ["a", {"b": 1}], "gone": None},
)


def context(**overrides: object) -> RefContext:
    values: dict[str, object] = {
        "inputs": {"issue": "AGH-1", "depth": 2},
        "nodes": {
            "plan": PLAN,
            "fix-tests": NodeResult(state="completed", output="all green"),
            "lint": NodeResult(state="skipped"),
            "build": NodeResult(state="failed", output="boom"),
        },
    }
    values.update(overrides)
    return RefContext(**values)  # type: ignore[arg-type]


def error_code(template: str, ctx: RefContext | None = None) -> str:
    with pytest.raises(SubstitutionError) as caught:
        render(template, ctx or context())
    return caught.value.code


# --- canonical value text --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ('raw "text"\n', 'raw "text"\n'),
        (None, ""),
        (True, "true"),
        (False, "false"),
        (3, "3"),
        (1.5, "1.5"),
        ({"b": 1, "a": [1, "é"]}, '{"a":[1,"é"],"b":1}'),
        ([], "[]"),
    ],
)
def test_renders_compact_sorted_json_when_value_is_not_a_string(value: object, text: str) -> None:
    assert canonical_text(value) == text  # type: ignore[arg-type]


# --- the reference grammar -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("$INPUTS.issue", InputRef("issue")),
        ("$INPUTS.output", InputRef("output")),
        ("$WITH.plan_text", WithRef("plan_text")),
        ("$plan.output", NodeRef("plan", ())),
        ("$plan.output.items.0", NodeRef("plan", ("items", "0"))),
        ("$fix-tests.output", NodeRef("fix-tests", ())),
        ("$inc__step.output.Field_1", NodeRef("inc__step", ("Field_1",))),
        ("$LOOP_PREV.review.output.verdict", LoopPrevRef("review", ("verdict",))),
    ],
)
def test_parses_reference_when_text_is_one_whole_reference(text: str, ref: object) -> None:
    assert parse_ref(text) == ref


@pytest.mark.parametrize(
    "text",
    ["$plan.output.", "$plan.output x", "plan.output", "$$plan.output", "$Plan.output", "$plan"],
)
def test_refuses_text_when_parsed_as_reference_but_not_one(text: str) -> None:
    with pytest.raises(SubstitutionError) as caught:
        parse_ref(text)
    assert caught.value.code == "malformed"


def test_ends_reference_when_a_dot_ends_the_sentence() -> None:
    assert render("Read $plan.output.summary.", context()) == "Read do it."


def test_ends_reference_when_a_character_cannot_continue_it() -> None:
    assert render("[$fix-tests.output]-$INPUTS.issue, ok", context()) == "[all green]-AGH-1, ok"


def test_keeps_dollar_as_text_when_it_starts_no_reference() -> None:
    template = 'sh -c "echo $1 ${HOME} $PATH" costs $5 and $plan.outputs'
    assert render(template, context()) == template


def test_renders_one_dollar_when_dollar_is_doubled() -> None:
    assert render("$$plan.output costs $$5", context()) == "$plan.output costs $5"


@pytest.mark.parametrize(
    "template",
    [
        "$INPUTS.issue.title",  # inputs have no path
        "$INPUTS.",
        "$INPUTS.Issue",
        "$WITH",
        "$LOOP_PREV.review",
        "$plan.output[0]",  # array items are `.0`
        "$plan.output?.summary",
    ],
)
def test_errors_when_reference_is_malformed(template: str) -> None:
    assert error_code(template) == "malformed"


def test_lists_references_in_order_when_finding_without_resolving() -> None:
    refs = find_refs("$INPUTS.issue then $$x $nowhere.output.a and $WITH.y")
    assert refs == [InputRef("issue"), NodeRef("nowhere", ("a",)), WithRef("y")]


# --- resolution ------------------------------------------------------------------------------


def test_inserts_canonical_text_when_inputs_and_fields_resolve() -> None:
    template = (
        "$INPUTS.depth/$plan.output.count/$plan.output.ok/$plan.output.items/$plan.output.gone|"
    )
    assert render(template, context()) == '2/3/true/["a",{"b":1}]/|'


def test_renders_canonical_json_when_whole_output_is_structured() -> None:
    assert render("$plan.output", context()).startswith('{"count":3,"gone":null,"items":')


def test_reads_array_item_when_segment_is_numeric() -> None:
    assert render("$plan.output.items.1.b", context()) == "1"


def test_never_rescans_when_inserted_value_holds_references() -> None:
    ctx = context(inputs={"issue": "$plan.output and $INPUTS.issue and $$"})
    assert render("<$INPUTS.issue>", ctx) == "<$plan.output and $INPUTS.issue and $$>"


def test_errors_when_input_unknown() -> None:
    assert error_code("$INPUTS.nope") == "unknown_input"


def test_errors_when_producer_failed() -> None:
    assert error_code("$build.output") == "producer_failed"
    assert error_code("$build.output.summary") == "producer_failed"


def test_reads_empty_text_when_producer_skipped() -> None:
    assert render("[$lint.output][$lint.output.summary]", context()) == "[][]"


def test_errors_when_node_has_no_result() -> None:
    assert error_code("$ghost.output") == "unknown_node"


def test_reads_empty_text_when_key_or_item_absent() -> None:
    template = "[$plan.output.extra][$plan.output.items.9][$plan.output.gone.x]"
    assert render(template, context()) == "[][][]"


@pytest.mark.parametrize(
    "template", ["$plan.output.summary.deeper", "$fix-tests.output.field", "$plan.output.items.x"]
)
def test_errors_when_path_goes_through_a_scalar_or_misses_an_index(template: str) -> None:
    assert error_code(template) == "bad_path"


def test_resolves_with_value_when_context_provides_it() -> None:
    ctx = context(with_values={"plan_text": {"k": "v"}})
    assert render("$WITH.plan_text", ctx) == '{"k":"v"}'
    assert error_code("$WITH.other", ctx) == "unknown_with"


def test_reads_previous_iteration_when_loop_prev_referenced() -> None:
    previous = {"review": NodeResult(state="completed", output={"verdict": "rework"})}
    assert render("$LOOP_PREV.review.output.verdict", context(loop_prev=previous)) == "rework"
    assert render("[$LOOP_PREV.review.output]", context(loop_prev={})) == "[]"


def test_errors_when_loop_prev_outside_loop_group() -> None:
    assert error_code("$LOOP_PREV.review.output") == "not_in_loop"


def test_names_the_reference_when_resolution_fails() -> None:
    with pytest.raises(SubstitutionError) as caught:
        render("x $INPUTS.nope y", context())
    assert caught.value.ref == "$INPUTS.nope"
    assert "$INPUTS.nope" in str(caught.value)


# --- argv ------------------------------------------------------------------------------------


def test_fills_whole_elements_unquoted_when_rendering_argv() -> None:
    ctx = context(inputs={"issue": "a b'; rm -rf /", "depth": 2})
    argv = ["sh", "-c", 'gh pr view "$1" --json $$x', "sh", "$INPUTS.issue", "$INPUTS.depth"]
    assert render_argv(argv, ctx) == [
        "sh",
        "-c",
        'gh pr view "$1" --json $x',
        "sh",
        "a b'; rm -rf /",
        "2",
    ]


@pytest.mark.parametrize("element", ["--title=$INPUTS.issue", "echo $plan.output.summary"])
def test_refuses_reference_when_inside_argv_element(element: str) -> None:
    with pytest.raises(SubstitutionError) as caught:
        render_argv(["hub", element], context())
    assert caught.value.code == "partial_argv"


def test_errors_when_whole_argv_element_cannot_resolve() -> None:
    with pytest.raises(SubstitutionError) as caught:
        render_argv(["echo", "$build.output"], context())
    assert caught.value.code == "producer_failed"
