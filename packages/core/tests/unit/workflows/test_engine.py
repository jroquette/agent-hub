"""The engine: layers, trigger rules, skip causes, retries, outputs, resume, status, outcome."""

from collections.abc import Mapping
from datetime import timedelta

import pytest

from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.workflow_fakes import (
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.engine import EnginePorts, WorkflowEngineError, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import NodeReply
from agent_hub.core.workflows.run_state import RunReport, RunState
from agent_hub.core.workflows.substitution import NodeResult

INPUTS = {"mode": {"default": "off"}, "issue": {}}
# Skips its node with cause ``condition``: ``mode`` is ``off`` unless a test gives it.
NEVER = "$INPUTS.mode == 'on'"


def plan_of(*nodes: dict[str, object], **top: object) -> WorkflowPlan:
    return a_plan(*nodes, **({"inputs": INPUTS} | top))


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    return {
        "id": node_id,
        "type": "shell",
        "command": ["true"],
        "depends_on": list(depends_on),
    } | keys


def agent(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "agent", "prompt": "Go.", "depends_on": list(depends_on)}
    return node | keys


OBJECT = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "delivery": {"type": "string", "enum": ["a", "b"]}},
    "required": ["ok", "delivery"],
}


class Run:
    """One run of ``plan`` over the fakes, and what it recorded."""

    def __init__(
        self,
        plan: WorkflowPlan,
        runner: ScriptedRunner | None = None,
        *,
        inputs: Mapping[str, JsonValue] | None = None,
        prior: RunState | None = None,
    ) -> None:
        self.runner = runner or ScriptedRunner()
        self.recorder = ListRecorder()
        self.clock = FakeClock()
        ports = EnginePorts(self.runner, self.recorder, self.clock, KeysOutputs(), lambda: 0.5)
        self.report: RunReport = run_workflow(plan, inputs or {}, ports, prior=prior)

    def status_of(self, node: str) -> tuple[str, str | None, str | None, str | None]:
        end = self.recorder.end_of(node)
        return end.status, end.skip_cause, end.origin, end.failure_kind


def fails(kind: str = "exec_failed") -> NodeFailedError:
    return NodeFailedError(kind, "boom")  # type: ignore[arg-type]


def test_runs_layers_in_order_one_node_at_a_time_when_graph_has_layers() -> None:
    plan = plan_of(shell("c", "a", "b"), shell("a"), shell("b"), shell("d", "c"))

    run = Run(plan)

    assert run.runner.ran() == ["a", "b", "c", "d"]
    assert [start.node for start in run.recorder.starts] == ["a", "b", "c", "d"]
    assert run.report.status == "done"


@pytest.mark.parametrize(
    ("rule", "upstream", "expected"),
    [
        ("all_success", ["ok", "ok"], "ok"),
        ("all_success", ["ok", "skip"], "skipped"),
        ("all_success", ["ok", "fail"], "skipped"),
        ("one_success", ["fail", "ok"], "ok"),
        ("one_success", ["fail", "skip"], "skipped"),
        ("none_failed_min_one_success", ["ok", "skip"], "ok"),
        ("none_failed_min_one_success", ["ok", "fail"], "skipped"),
        ("none_failed_min_one_success", ["skip", "skip"], "skipped"),
        ("all_done", ["fail", "skip"], "ok"),
    ],
)
def test_applies_trigger_rule_when_upstream_ends_vary(
    rule: str, upstream: list[str], expected: str
) -> None:
    nodes = []
    replies: dict[str, list[object]] = {}
    for index, end in enumerate(upstream):
        node_id = f"u{index}"
        nodes.append(shell(node_id, when=NEVER) if end == "skip" else shell(node_id))
        if end == "fail":
            replies[node_id] = [fails()]
    nodes.append(shell("join", "u0", "u1", trigger_rule=rule))

    run = Run(plan_of(*nodes), ScriptedRunner(replies))  # type: ignore[arg-type]

    assert run.status_of("join")[0] == expected


def test_carries_the_failed_origin_down_the_chain_when_a_node_fails() -> None:
    plan = plan_of(
        shell("a"), shell("b", "a"), shell("c", "b"), shell("d", "c", trigger_rule="one_success")
    )

    run = Run(plan, ScriptedRunner({"a": [fails()]}))

    assert run.status_of("b") == ("skipped", "upstream_failed", "a", None)
    assert run.status_of("c") == ("skipped", "upstream_failed", "a", None)
    assert run.status_of("d") == ("skipped", "upstream_failed", "a", None)


def test_carries_the_skipped_origin_down_the_chain_when_a_condition_skips() -> None:
    plan = plan_of(shell("a", when=NEVER), shell("b", "a"), shell("c", "b"))

    run = Run(plan)

    assert run.status_of("a") == ("skipped", "condition", None, None)
    assert run.status_of("b") == ("skipped", "upstream_skipped", "a", None)
    assert run.status_of("c") == ("skipped", "upstream_skipped", "a", None)


def test_prefers_upstream_failed_when_upstreams_failed_and_skipped() -> None:
    plan = plan_of(shell("s", when=NEVER), shell("f"), shell("j", "s", "f"))

    run = Run(plan, ScriptedRunner({"f": [fails()]}))

    assert run.status_of("j") == ("skipped", "upstream_failed", "f", None)


def test_runs_later_layers_when_a_node_fails() -> None:
    plan = plan_of(shell("a"), shell("b"), shell("c", "b"))

    run = Run(plan, ScriptedRunner({"a": [fails()]}))

    assert run.runner.ran() == ["a", "b", "c"]
    assert run.report.status == "failed"
    assert run.report.reason == "a"


def test_skips_with_a_cause_when_condition_is_false_or_does_not_parse() -> None:
    plan = plan_of(shell("a", when="$INPUTS.mode == 'x'"), shell("b", when="$INPUTS.mode < 3"))

    run = Run(plan, inputs={"mode": "y"})

    assert run.status_of("a") == ("skipped", "condition", None, None)
    assert run.status_of("b") == ("skipped", "condition_parse_error", None, None)
    assert run.recorder.starts == []
    assert run.report.status == "done"


def test_fails_config_when_condition_reads_a_failed_producer() -> None:
    plan = plan_of(shell("a"), shell("b", "a", trigger_rule="all_done", when="$a.output == 'x'"))

    run = Run(plan, ScriptedRunner({"a": [fails()]}))

    assert run.status_of("b") == ("failed", None, None, "config")
    assert run.runner.ran() == ["a"]
    assert [(start.node, start.attempt) for start in run.recorder.starts] == [("a", 1), ("b", 1)]


def test_renders_references_when_a_node_reads_upstream_outputs() -> None:
    plan = plan_of(
        agent("plan", output_format=OBJECT),
        shell("use", "plan", command=["echo", "$plan.output.delivery", "$INPUTS.issue"]),
    )
    runner = ScriptedRunner({"plan": ['{"ok": true, "delivery": "b"}']})

    run = Run(plan, runner, inputs={"issue": "AGH-1"})

    assert runner.calls[1].argv == ("echo", "b", "AGH-1")
    assert run.recorder.end_of("plan").output == {"ok": True, "delivery": "b"}


def test_retries_and_records_each_retry_when_failure_is_transient() -> None:
    plan = plan_of(shell("a", retry={"max_attempts": 2, "delay": "3s"}))
    runner = ScriptedRunner({"a": [fails("transient"), fails("timeout"), "done"]})

    run = Run(plan, runner)

    assert [(end.attempt, end.status, end.failure_kind) for end in run.recorder.ends] == [
        (1, "failed", "transient"),
        (2, "failed", "timeout"),
        (3, "ok", None),
    ]
    assert run.recorder.retries == [
        ("a", RetryRecord(1, "transient", timedelta(seconds=3))),
        ("a", RetryRecord(2, "timeout", timedelta(seconds=6))),
    ]
    assert run.clock.sleeps == [timedelta(seconds=3), timedelta(seconds=6)]
    assert run.report.status == "done"


@pytest.mark.parametrize("kind", ["config", "auth", "cancelled", "fatal", "exec_failed"])
def test_never_retries_when_kind_is_not_retried_by_default(kind: str) -> None:
    run = Run(plan_of(shell("a")), ScriptedRunner({"a": [fails(kind), "late"]}))

    assert run.runner.ran() == ["a"]
    assert run.recorder.retries == []
    assert run.status_of("a") == ("failed", None, None, kind)


def test_fails_output_contract_without_retry_when_stdout_is_not_json() -> None:
    plan = plan_of(shell("a", output_format=OBJECT, retry={"on_error": "all"}))

    run = Run(plan, ScriptedRunner({"a": ["not json", "{}"]}))

    assert run.status_of("a") == ("failed", None, None, "output_contract")
    assert run.runner.ran() == ["a"]


def test_retries_output_contract_when_agent_opts_in() -> None:
    plan = plan_of(agent("a", output_format=OBJECT, retry={"on_error": "all"}))

    run = Run(plan, ScriptedRunner({"a": ['{"ok": true}', '{"ok": true, "delivery": "a"}']}))

    assert [end.failure_kind for end in run.recorder.ends] == ["output_contract", None]


def test_refuses_a_non_finite_number_when_output_is_parsed() -> None:
    plan = plan_of(agent("a", output_format={"type": "number"}))

    run = Run(plan, ScriptedRunner({"a": ["NaN"]}))

    assert run.status_of("a") == ("failed", None, None, "output_contract")


def test_passes_the_resumed_session_when_context_names_an_upstream_agent() -> None:
    plan = plan_of(agent("a"), agent("b", "a", context={"resume": "a"}), agent("c", "b"))
    runner = ScriptedRunner({"a": [NodeReply("x", session="s-a")]})

    Run(plan, runner)

    assert [call.resume_session for call in runner.calls] == [None, "s-a", None]


def test_reuses_completed_nodes_and_keeps_counting_attempts_when_resumed() -> None:
    plan = plan_of(shell("a"), shell("b", "a"), shell("c", "b", always_run=True))
    prior = RunState(
        nodes={
            "a": NodeResult("completed", "A"),
            "b": NodeResult("failed"),
            "c": NodeResult("completed", "C"),
        },
        attempts={"a": 1, "b": 2, "c": 1},
    )

    run = Run(plan, ScriptedRunner({"b": ["B"]}), prior=prior)

    assert run.runner.ran() == ["b", "c"]
    assert run.status_of("a") == ("skipped", "prior_success", None, None)
    assert [(end.node, end.attempt) for end in run.recorder.ends] == [("a", 2), ("b", 3), ("c", 2)]
    assert run.report.state.nodes["a"] == NodeResult("completed", "A")
    assert run.report.state.attempts == {"a": 2, "b": 3, "c": 2}
    assert run.report.status == "done"


def test_runs_a_cached_node_again_when_its_dependency_changed_on_resume() -> None:
    plan = plan_of(shell("a", always_run=True), shell("b", "a"), shell("c"))
    prior = RunState(
        nodes={n: NodeResult("completed", n.upper()) for n in ("a", "b", "c")},
        attempts={"a": 1, "b": 1, "c": 1},
    )

    run = Run(plan, ScriptedRunner({"a": ["changed"]}), prior=prior)

    assert run.runner.ran() == ["a", "b"]
    assert run.status_of("c")[1] == "prior_success"


def test_keeps_the_cache_when_a_rerun_dependency_gives_the_same_value() -> None:
    plan = plan_of(shell("a", always_run=True), shell("b", "a"))
    prior = RunState(nodes={"a": NodeResult("completed", "A"), "b": NodeResult("completed", "B")})

    run = Run(plan, ScriptedRunner({"a": ["A"]}), prior=prior)

    assert run.runner.ran() == ["a"]


def test_reports_status_apart_from_outcome_when_returns_node_completes() -> None:
    plan = plan_of(
        agent("report", output_format=OBJECT),
        shell("after", "report"),
        returns="report",
        outcome_field="delivery",
    )
    runner = ScriptedRunner({"report": ['{"ok": false, "delivery": "b"}'], "after": [fails()]})

    run = Run(plan, runner)

    assert (run.report.status, run.report.outcome) == ("failed", "b")
    end = run.recorder.run_ends[0]
    assert (end.status, end.outcome, end.reason) == ("failed", "b", "after")


def test_reads_a_boolean_outcome_when_outcome_field_is_boolean() -> None:
    plan = plan_of(agent("r", output_format=OBJECT), returns="r", outcome_field="ok")

    run = Run(plan, ScriptedRunner({"r": ['{"ok": false, "delivery": "a"}']}))

    assert (run.report.status, run.report.outcome) == ("done", False)


def test_leaves_no_outcome_when_returns_node_did_not_complete() -> None:
    plan = plan_of(agent("r", output_format=OBJECT, when=NEVER), returns="r", outcome_field="ok")

    run = Run(plan)

    assert (run.report.status, run.report.outcome) == ("done", None)


def test_ends_cancelled_without_running_later_nodes_when_halt_is_reached() -> None:
    plan = plan_of(
        shell("a"),
        {"id": "stop", "type": "halt", "reason": "Stopped on $a.output", "depends_on": ["a"]},
        shell("b", "stop"),
        shell("c", "a"),
    )

    run = Run(plan, ScriptedRunner({"a": ["red"]}))

    assert run.runner.ran() == ["a"]
    assert run.recorder.end_of("stop").detail == "Stopped on red"
    assert (run.report.status, run.report.reason) == ("cancelled", "stop")
    assert [end.node for end in run.recorder.ends] == ["a", "stop"]


def test_refuses_to_start_when_document_holds_an_approval_node() -> None:
    plan = plan_of(
        shell("a"), {"id": "gate", "type": "approval", "message": "Ok?", "depends_on": ["a"]}
    )
    runner = ScriptedRunner()

    with pytest.raises(WorkflowEngineError, match='"gate".*approval'):
        Run(plan, runner)
    assert runner.calls == []


def test_fills_defaults_when_inputs_are_left_out() -> None:
    plan = plan_of(
        shell("a", command=["echo", "$INPUTS.mode"]),
        inputs={"mode": {"default": "fast"}},
    )

    run = Run(plan)

    assert run.runner.calls[0].argv == ("echo", "fast")


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({}, 'the input "issue" is required'),
        ({"issue": "x", "other": 1}, 'no input is named "other"'),
    ],
)
def test_refuses_to_start_when_inputs_do_not_fit(given: dict[str, JsonValue], message: str) -> None:
    plan = plan_of(shell("a"), inputs={"issue": {"required": True}})

    with pytest.raises(WorkflowEngineError, match=message):
        Run(plan, inputs=given)


def test_resolves_with_values_when_an_agent_binds_upstream_outputs() -> None:
    plan = plan_of(
        shell("a"),
        shell("s", when=NEVER),
        agent(
            "b",
            "a",
            "s",
            trigger_rule="all_done",
            prompt="Use $WITH.got and $WITH.missing!",
            **{
                "with": {
                    "got": {"from": "$a.output"},
                    "missing": {"from": "$s.output", "if_skipped": "none"},
                    "issue": ["for $INPUTS.issue"],
                    "limits": {"n": 2, "who": "$INPUTS.issue"},
                }
            },
        ),
    )
    runner = ScriptedRunner({"a": ["A"]})

    Run(plan, runner, inputs={"issue": "AGH-1"})

    call = runner.calls[1]
    assert call.context.with_values == {
        "got": "A",
        "missing": "none",
        "issue": ["for AGH-1"],
        "limits": {"n": 2, "who": "AGH-1"},
    }
    assert call.prompt == "Use A and none!"


def test_fails_config_without_running_when_argv_reads_a_failed_producer() -> None:
    plan = plan_of(
        shell("a"), shell("b", "a", trigger_rule="all_done", command=["echo", "$a.output"])
    )
    runner = ScriptedRunner({"a": [fails()]})

    run = Run(plan, runner)

    assert run.status_of("b") == ("failed", None, None, "config")
    assert runner.ran() == ["a"]


def test_records_the_error_as_detail_when_a_halt_reason_cannot_render() -> None:
    plan = plan_of(
        shell("a"),
        {
            "id": "stop",
            "type": "halt",
            "reason": "On $a.output",
            "depends_on": ["a"],
            "trigger_rule": "all_done",
        },
    )

    run = Run(plan, ScriptedRunner({"a": [fails()]}))

    assert "its producer failed" in run.recorder.end_of("stop").detail
    assert run.report.status == "cancelled"


def test_runs_the_node_when_its_condition_holds() -> None:
    run = Run(plan_of(shell("a", when="$INPUTS.mode == 'off'")))

    assert run.runner.ran() == ["a"]


def test_ends_the_step_unknown_and_the_run_failed_when_a_port_raises() -> None:
    plan = plan_of(shell("a"), shell("b"))
    runner = ScriptedRunner({"a": [OSError("the output text")]})

    run = Run(plan, runner)

    assert run.status_of("a") == ("failed", None, None, "unknown")
    assert run.recorder.end_of("a").detail == "OSError"
    assert run.runner.ran() == ["a", "b"]
    assert [end.status for end in run.recorder.run_ends] == ["failed"]
    assert run.report.state.attempts == {"a": 1, "b": 1}


def test_runs_a_cached_node_again_when_an_ancestor_it_reads_changed() -> None:
    plan = plan_of(
        shell("a", always_run=True),
        shell("b", "a"),
        shell("c", "b", command=["echo", "$a.output"]),
    )
    prior = RunState(nodes={n: NodeResult("completed", n.upper()) for n in ("a", "b", "c")})

    run = Run(plan, ScriptedRunner({"a": ["NEW"], "b": ["B"]}), prior=prior)

    assert run.runner.ran() == ["a", "b", "c"]
    assert run.runner.calls[2].argv == ("echo", "NEW")


def test_skips_a_join_when_an_upstream_was_skipped_for_a_failure() -> None:
    plan = plan_of(
        shell("f"),
        shell("s", "f"),
        shell("ok"),
        shell("j", "s", "ok", trigger_rule="none_failed_min_one_success"),
    )

    run = Run(plan, ScriptedRunner({"f": [fails()]}))

    assert run.status_of("j") == ("skipped", "upstream_failed", "f", None)


def test_ends_cancelled_when_a_halt_follows_a_failed_node() -> None:
    plan = plan_of(
        shell("a"),
        {
            "id": "stop",
            "type": "halt",
            "reason": "Stop.",
            "depends_on": ["a"],
            "trigger_rule": "all_done",
        },
    )

    run = Run(plan, ScriptedRunner({"a": [fails()]}))

    assert (run.report.status, run.report.reason) == ("cancelled", "stop")
