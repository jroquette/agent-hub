"""The dry run: the real engine over stubbed node results, in memory (AC-213.11)."""

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.workflow_fakes import KeysOutputs, a_plan
from agent_hub.core.workflows.dry_run import (
    MAX_PLACEHOLDER_ITEMS,
    PLACEHOLDER_BUDGET,
    DryRunReport,
    Stub,
    Stubs,
    dry_run,
    placeholder,
    skeleton_stub,
)
from agent_hub.core.workflows.plan import WorkflowPlan

OBJECT = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "delivery": {"type": "string", "enum": ["a", "b"]}},
    "required": ["ok", "delivery"],
}
DONE = {"type": "object", "properties": {"done": {"type": "boolean"}}, "required": ["done"]}


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "shell", "command": ["true"], "depends_on": list(depends_on)}
    return node | keys


def loop(node_id: str, **keys: object) -> dict[str, object]:
    return {"id": node_id, "type": "loop", "prompt": "Go.", "max_iterations": 3} | keys


def stubs(**given: Any) -> dict[str, Stubs]:
    return {
        node: tuple(Stub.model_validate(s) for s in value)
        if isinstance(value, list)
        else Stub.model_validate(value)
        for node, value in given.items()
    }


def run(
    plan: WorkflowPlan, inputs: Mapping[str, JsonValue] | None = None, **given: Any
) -> DryRunReport:
    return dry_run(plan, inputs or {}, stubs(**given), outputs=KeysOutputs())


def output_of(report: DryRunReport, node: str) -> JsonValue:
    return report.run.state.nodes[node].output


def test_answers_each_node_from_its_stub_when_every_reached_node_has_one() -> None:
    plan = a_plan(
        shell("a", output_format=OBJECT),
        shell("b", "a", command=["echo", "$a.output.delivery"]),
    )

    report = run(plan, a={"output": {"ok": True, "delivery": "b"}}, b={"text": "said b"})

    assert (report.run.status, report.reached, report.failed) == ("done", ("a", "b"), ())
    assert output_of(report, "a") == {"ok": True, "delivery": "b"}
    assert output_of(report, "b") == "said b"


def test_fails_the_node_and_lists_it_missing_when_a_reached_node_has_no_stub() -> None:
    plan = a_plan(shell("a"), shell("b", "a"))

    report = run(plan, b={"text": "never"})

    assert report.missing == ("a",)
    assert (report.run.status, report.failed, report.reached) == ("failed", ("a",), ("a",))
    assert report.steps[-1].skip_cause == "upstream_failed"


def test_needs_no_stub_when_a_node_is_never_reached() -> None:
    plan = a_plan(shell("a"), shell("b", "a"))

    report = run(plan, a={"fail": "exec_failed"})

    assert (report.missing, report.failed, report.reached) == ((), ("a",), ("a",))


def test_gives_a_placeholder_that_fits_its_output_format_when_an_all_done_join_has_no_stub() -> (
    None
):
    plan = a_plan(
        shell("a"),
        shell("join", "a", trigger_rule="all_done", output_format=OBJECT),
        returns="join",
        outcome_field="ok",
    )

    report = run(plan, a={"fail": "exec_failed"})

    assert (report.missing, report.tolerated) == ((), ("join",))
    assert output_of(report, "join") == {"ok": False, "delivery": "a"}
    # A placeholder is not authored: it never sets the run's outcome.
    assert report.outcome is None


def test_fails_output_contract_when_a_stub_breaks_the_output_format() -> None:
    plan = a_plan(shell("a", output_format=OBJECT))

    report = run(plan, a={"output": {"ok": True}})

    assert report.failed == ("a",)
    assert report.steps[-1].failure_kind == "output_contract"


def test_answers_successive_attempts_from_the_list_when_a_stub_fails_transient() -> None:
    plan = a_plan(shell("a"))

    report = run(plan, a=[{"fail": "transient"}, {"text": "second"}])

    assert (report.run.status, output_of(report, "a")) == ("done", "second")
    assert [step.status for step in report.steps] == ["failed", "ok"]


def test_reuses_one_stub_every_iteration_when_a_loop_has_a_single_stub() -> None:
    plan = a_plan(loop("a", until_field="done", output_format=DONE))

    report = run(plan, a={"output": {"done": False}})

    assert report.failed == ("a",)
    assert report.steps[-1].failure_kind == "max_iterations"


def test_ends_the_loop_on_the_stub_that_says_done_when_a_loop_has_a_list() -> None:
    plan = a_plan(loop("a", until_field="done", output_format=DONE))

    report = run(plan, a=[{"output": {"done": False}}, {"output": {"done": True}}])

    assert (report.run.status, output_of(report, "a")) == ("done", {"done": True})


def test_decides_until_bash_from_until_exit_when_an_iteration_gives_one() -> None:
    plan = a_plan(loop("a", until_bash=["make", "check"]))

    report = run(plan, a=[{"text": "first", "until_exit": 1}, {"text": "second"}])

    assert (report.run.status, output_of(report, "a")) == ("done", "second")


def test_lists_a_missing_stub_when_a_stub_list_runs_out() -> None:
    plan = a_plan(loop("a", until="DONE"))

    report = run(plan, a=[{"text": "working"}])

    assert (report.missing, report.failed) == (("a",), ("a",))


def test_follows_when_and_trigger_rules_when_stubs_drive_a_branch() -> None:
    plan = a_plan(
        shell("route", output_format=OBJECT),
        shell("left", "route", when="$route.output.delivery == 'a'"),
        shell("right", "route", when="$route.output.delivery == 'b'"),
        shell("join", "left", "right", trigger_rule="none_failed_min_one_success"),
    )

    report = run(
        plan,
        route={"output": {"ok": True, "delivery": "b"}},
        right={"text": "r"},
        join={"text": "j"},
    )

    assert (report.run.status, report.reached) == ("done", ("route", "right", "join"))
    assert report.unused == ()


def test_ends_cancelled_and_reaches_the_halt_when_a_halt_node_runs() -> None:
    plan = a_plan(shell("a"), {"id": "stop", "type": "halt", "reason": "no"}, shell("b", "stop"))

    report = run(plan, a={"text": "x"}, b={"text": "never"})

    assert (report.run.status, report.reached, report.unused) == (
        "cancelled",
        ("a", "stop"),
        ("b",),
    )


def test_takes_the_outcome_from_the_returns_stub_when_it_completes() -> None:
    plan = a_plan(shell("a", output_format=OBJECT), returns="a", outcome_field="delivery")

    report = run(plan, a={"output": {"ok": True, "delivery": "b"}})

    assert report.outcome == "b"


GATES = (
    {"id": "ok", "type": "approval", "message": "Ship?", "capture_response": True},
    {"id": "nap", "type": "wait", "duration": "1h", "depends_on": ["ok"]},
    {"id": "ask", "type": "wait", "attention": "Why?", "depends_on": ["nap"]},
    {
        "id": "pick",
        "type": "wait",
        "attention": "Which?",
        "options": [{"id": "red", "label": "Red"}],
        "depends_on": ["ask"],
    },
)


def test_pauses_on_the_first_gate_when_it_has_no_stub() -> None:
    report = run(a_plan(shell("a"), {**GATES[0], "depends_on": ["a"]}), a={"text": "x"})

    assert (report.run.status, report.run.reason) == ("paused", "ok")
    assert (report.reached, report.missing, report.failed) == (("a", "ok"), (), ())


def test_answers_each_gate_from_its_stub_when_every_gate_has_one() -> None:
    report = run(
        a_plan(*GATES),
        ok={"decision": "approve", "text": "tests"},
        nap={},
        ask={"text": "because"},
        pick={"choice": "red"},
    )

    assert report.run.status == "done"
    assert output_of(report, "ok") == {"decision": "approve", "text": "tests"}
    assert output_of(report, "nap") == {"at": "2000-01-01T00:00:00+00:00"}
    assert output_of(report, "ask") == {"text": "because"}
    assert output_of(report, "pick") == {"choice": "red", "text": ""}


@pytest.mark.parametrize(
    ("node", "stub"),
    [("ok", {"decision": "maybe"}), ("ok", {"output": "x"}), ("a", {"decision": "approve"})],
)
def test_fails_config_when_a_stub_does_not_fit_its_node(node: str, stub: object) -> None:
    plan = a_plan(shell("a"), {**GATES[0], "depends_on": ["a"]})
    given: dict[str, object] = {"a": {"text": "x"}, "ok": {"decision": "approve"}} | {node: stub}

    report = run(plan, **given)

    assert report.failed == (node,)
    assert [step.failure_kind for step in report.steps if step.node == node] == ["config"]


@pytest.mark.parametrize(
    "stub",
    [
        {"text": "a", "output": "b"},
        {"fail": "nope"},
        {"until_exit": 1},
        {"why": 1},
        {"decision": "a", "choice": "b"},
        {"decision": "a", "output": 1},
        {"choice": "a", "fail": "exec_failed"},
        {"decision": "Not Kebab"},
    ],
)
def test_refuses_the_stub_when_it_gives_no_answer_or_more_than_one(stub: object) -> None:
    with pytest.raises(ValidationError):
        Stub.model_validate(stub)


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        ({"const": 3, "type": "string"}, 3),
        ({"default": "d", "enum": ["x"]}, "d"),
        ({"enum": ["x", "y"]}, "x"),
        ({"type": "boolean"}, False),
        ({"type": ["integer", "null"]}, 0),
        ({"type": "number", "minimum": 2.5}, 2.5),
        ({"type": "null"}, None),
        ({"type": "string"}, "TODO"),
        ({}, "TODO"),
        ({"type": "array", "items": {"type": "boolean"}, "minItems": 2}, [False, False]),
        (
            {"type": "object", "properties": {"a": {}}, "required": ["a", "b"]},
            {"a": "TODO", "b": "TODO"},
        ),
    ],
)
def test_builds_a_value_that_fits_when_the_schema_constrains_it(
    schema: dict[str, JsonValue], value: JsonValue
) -> None:
    assert placeholder(schema) == value


@pytest.mark.parametrize(
    ("node", "stub"),
    [
        (loop("a", until_field="done", output_format=DONE), {"output": {"done": True}}),
        (loop("a", until="DONE"), {"text": "DONE"}),
        (shell("a"), {"text": "TODO"}),
        (shell("a", output_format=OBJECT), {"output": {"ok": False, "delivery": "a"}}),
    ],
)
def test_gives_a_stub_that_completes_the_node_when_a_skeleton_is_asked(
    node: dict[str, object], stub: dict[str, JsonValue]
) -> None:
    [planned] = a_plan(node).document.nodes

    assert skeleton_stub(planned) == stub


def test_caps_the_items_when_min_items_is_past_the_cap() -> None:
    schema: dict[str, JsonValue] = {
        "type": "array",
        "items": {"type": "boolean"},
        "minItems": MAX_PLACEHOLDER_ITEMS + 1,
    }

    assert placeholder(schema) == [False] * MAX_PLACEHOLDER_ITEMS


def test_gives_minimal_values_when_the_schema_is_past_the_node_budget() -> None:
    # The root takes one node and each property two (the array and its item): property
    # ``PLACEHOLDER_BUDGET // 2`` is the first one past the budget, so it is the minimal [].
    names = [f"p{index:04}" for index in range(PLACEHOLDER_BUDGET // 2 + 1)]
    item: JsonValue = {"type": "array", "items": {"type": "string"}, "minItems": 1}
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": dict.fromkeys(names, item),
        "required": list(names),
    }

    value = placeholder(schema)

    assert value == {**{name: ["TODO"] for name in names[:-1]}, names[-1]: []}


def test_lists_the_failed_body_node_and_its_group_when_a_body_node_fails() -> None:
    group = {
        "id": "g",
        "type": "loop_group",
        "max_iterations": 2,
        "until_when": "$b.output == 'done'",
        "nodes": [{"id": "b", "type": "shell", "command": ["true"]}],
    }

    report = dry_run(a_plan(group), {}, {"g__b": Stub(fail="exec_failed")}, outputs=KeysOutputs())

    assert report.failed == ("g", "g__b")
    assert report.reached == ("g", "g__b")
