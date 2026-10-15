"""The engine: layers, trigger rules, skip causes, retries, outputs, resume, status, outcome."""

import threading
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
from agent_hub.core.workflows import plan as plan_module
from agent_hub.core.workflows.engine import (
    MAX_PARALLEL,
    EnginePorts,
    WorkflowEngineError,
    run_workflow,
)
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import CheckoutProbe, NodeCall, NodeReply
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
        checkout: CheckoutProbe | None = None,
        max_parallel: int = MAX_PARALLEL,
    ) -> None:
        self.runner = runner or ScriptedRunner()
        self.recorder = ListRecorder()
        self.clock = FakeClock()
        ports = EnginePorts(
            self.runner,
            self.recorder,
            self.clock,
            KeysOutputs(),
            lambda: 0.5,
            checkout,
            max_parallel,
        )
        self.report: RunReport = run_workflow(plan, inputs or {}, ports, prior=prior)

    def status_of(self, node: str) -> tuple[str, str | None, str | None, str | None]:
        end = self.recorder.end_of(node)
        return end.status, end.skip_cause, end.origin, end.failure_kind


def fails(kind: str = "exec_failed") -> NodeFailedError:
    return NodeFailedError(kind, "boom")  # type: ignore[arg-type]


def test_runs_layers_in_order_when_graph_has_layers() -> None:
    plan = plan_of(shell("c", "a", "b"), shell("a"), shell("b"), shell("d", "c"))

    run = Run(plan)

    # a and b share a layer and run concurrently; their records keep declaration order.
    assert sorted(run.runner.ran()[:2]) == ["a", "b"]
    assert run.runner.ran()[2:] == ["c", "d"]
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

    assert sorted(run.runner.ran()[:2]) == ["a", "b"]
    assert run.runner.ran()[2] == "c"
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
    assert sorted(run.runner.ran()) == ["a", "b"]
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


def completed(*node_ids: str) -> RunState:
    return RunState(nodes={n: NodeResult("completed", n.upper()) for n in node_ids})


def test_reruns_only_what_follows_a_change_when_a_chain_resumes() -> None:
    plan = plan_of(
        shell("a"), shell("b", "a", always_run=True), shell("c", "b"), shell("d", "c"), shell("e")
    )

    run = Run(plan, ScriptedRunner({"b": ["NEW"]}), prior=completed("a", "b", "c", "d", "e"))

    assert run.runner.ran() == ["b", "c", "d"]
    assert [n for n in "ae" if run.status_of(n)[1] == "prior_success"] == ["a", "e"]


@pytest.mark.parametrize(
    ("changed_value", "expected"),
    [("B", ["b"]), ("NEW", ["b", "d"])],
    ids=["same-value", "new-value"],
)
def test_reruns_the_join_only_when_a_branch_changed_when_a_diamond_resumes(
    changed_value: str, expected: list[str]
) -> None:
    plan = plan_of(
        shell("a"), shell("b", "a", always_run=True), shell("c", "a"), shell("d", "b", "c")
    )

    run = Run(plan, ScriptedRunner({"b": [changed_value]}), prior=completed("a", "b", "c", "d"))

    assert run.runner.ran() == expected


def test_fails_the_node_and_ends_the_run_when_jitter_raises() -> None:
    plan = plan_of(shell("a"), shell("b"))
    recorder = ListRecorder()

    def broken() -> float:
        raise RuntimeError

    runner = ScriptedRunner({"a": [fails("rate_limited"), "late"]})
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), broken)
    report = run_workflow(plan, {}, ports)

    assert sorted(runner.ran()) == ["a", "b"]
    assert (report.status, report.reason) == ("failed", "a")
    assert [end.status for end in recorder.run_ends] == ["failed"]
    assert recorder.retries == []


def test_fails_the_node_and_ends_the_run_when_the_clock_cannot_sleep() -> None:
    class StuckClock(FakeClock):
        def sleep(self, delay: timedelta) -> None:
            raise OSError

    plan = plan_of(shell("a"))
    recorder = ListRecorder()
    runner = ScriptedRunner({"a": [fails("transient"), "late"]})
    report = run_workflow(
        plan, {}, EnginePorts(runner, recorder, StuckClock(), KeysOutputs(), lambda: 0.5)
    )

    assert runner.ran() == ["a"]
    assert report.status == "failed"
    assert [end.status for end in recorder.run_ends] == ["failed"]


# Concurrent layers (task 8.3): threads, declaration-order records, the checkout check.


class GatedRunner(ScriptedRunner):
    """``first`` answers only once ``second`` has run: they can only both end concurrently."""

    def __init__(self, first: str, second: str, wait: float = 5.0) -> None:
        super().__init__()
        self.first, self.second, self.wait = first, second, wait
        self.second_ran = threading.Event()

    def run(self, call: NodeCall) -> NodeReply:
        if call.node.id == self.first and not self.second_ran.wait(timeout=self.wait):
            raise TimeoutError
        try:
            return super().run(call)
        finally:
            if call.node.id == self.second:
                self.second_ran.set()


def test_records_each_node_as_it_ends_when_parallel_nodes_end_out_of_order() -> None:
    runner = GatedRunner("a", "b")

    run = Run(plan_of(shell("a"), shell("b"), shell("c", "a", "b")), runner)

    assert runner.ran() == ["b", "a", "c"]
    assert {start.node for start in run.recorder.starts[:2]} == {"a", "b"}
    assert [end.node for end in run.recorder.ends] == ["b", "a", "c"]
    assert run.report.status == "done"


def test_runs_one_node_at_a_time_when_a_parallel_layer_holds_a_halt() -> None:
    halt = {"id": "stop", "type": "halt", "reason": "Stop."}

    run = Run(plan_of(halt, shell("b")))

    assert run.runner.ran() == []
    assert run.report.status == "cancelled"


def test_runs_one_node_at_a_time_when_parallel_is_bounded_to_one() -> None:
    runner = GatedRunner("a", "b", wait=0.05)

    run = Run(plan_of(shell("a"), shell("b")), runner, max_parallel=1)

    assert run.status_of("a") == ("failed", None, None, "unknown")
    assert run.recorder.end_of("a").detail == "TimeoutError"
    assert run.status_of("b") == ("ok", None, None, None)


class Checkout:
    """A checkout probe answering from a list, one status per call."""

    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses)

    def status(self) -> str:
        return self.statuses.pop(0)


def run_read_only(checkout: CheckoutProbe | None) -> Run:
    return Run(plan_of(shell("r", mutates_checkout=False)), checkout=checkout)


def test_passes_a_read_only_node_when_the_checkout_status_is_unchanged() -> None:
    run = run_read_only(Checkout(" M a.py", " M a.py"))

    assert run.status_of("r") == ("ok", None, None, None)


def test_fails_config_without_retry_when_a_read_only_node_changes_the_checkout() -> None:
    run = run_read_only(Checkout("", "?? new.py"))

    assert run.status_of("r") == ("failed", None, None, "config")
    assert "mutates_checkout" in run.recorder.end_of("r").detail
    assert run.report.status == "failed"


def test_fails_config_when_a_read_only_node_runs_without_a_checkout_probe() -> None:
    run = run_read_only(None)

    assert run.status_of("r") == ("failed", None, None, "config")


def test_splits_a_parallel_layer_when_read_only_and_writing_nodes_share_it() -> None:
    plan = plan_of(
        shell("r1", mutates_checkout=False), shell("w"), shell("r2", mutates_checkout=False)
    )

    assert plan.layers == (("r1", "r2"), ("w",))


def test_splits_a_parallel_layer_when_two_agents_resume_one_session() -> None:
    plan = plan_of(
        agent("plan"),
        agent("a", "plan", context={"resume": "plan"}),
        agent("b", "plan", context={"resume": "plan"}),
        agent("c", "plan"),
    )

    assert plan.layers == (("plan",), ("a", "c"), ("b",))


def test_names_the_first_failed_node_in_declaration_order_when_parallel_nodes_fail() -> None:
    runner = GatedRunner("a", "b")
    runner.replies = {"a": [fails()], "b": [fails()]}

    run = Run(plan_of(shell("a"), shell("b")), runner)

    assert (run.report.status, run.report.reason) == ("failed", "a")


def a_group(*body: dict[str, object], **keys: object) -> dict[str, object]:
    group = {"id": "g", "type": "loop_group", "max_iterations": 1, "nodes": list(body)}
    return group | {"until_when": "$INPUTS.mode == 'off'"} | keys


def test_runs_one_node_at_a_time_when_a_parallel_layer_holds_a_group_with_a_halt() -> None:
    halt = {"id": "stop", "type": "halt", "reason": "Stop."}

    run = Run(plan_of(a_group(halt), shell("b")))

    assert run.runner.ran() == []
    assert run.report.status == "cancelled"


def test_splits_a_parallel_layer_when_a_group_reads_and_a_node_writes() -> None:
    plan = plan_of(shell("w"), a_group(shell("r", mutates_checkout=False)))

    assert plan.layers == (("w",), ("g",))


class Counting(ScriptedRunner):
    """Keeps the most calls that ran at once."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.active = self.most = 0

    def run(self, call: NodeCall) -> NodeReply:
        with self.lock:
            self.active += 1
            self.most = max(self.most, self.active)
        try:
            threading.Event().wait(0.05)
            return super().run(call)
        finally:
            with self.lock:
                self.active -= 1


def test_runs_at_most_the_bound_at_once_when_parallel_groups_nest() -> None:
    runner = Counting()
    body = [shell(f"b{index}") for index in range(4)]
    plan = plan_of(*(shell(f"n{index}") for index in range(6)), a_group(*body))

    Run(plan, runner)

    assert len(runner.calls) == 10
    assert runner.most == MAX_PARALLEL


def test_interrupts_running_nodes_when_a_parallel_layer_is_interrupted() -> None:
    stopped = threading.Event()

    class Interrupted(ScriptedRunner):
        def run(self, call: NodeCall) -> NodeReply:
            if call.node.id == "a":
                raise KeyboardInterrupt
            if not stopped.wait(timeout=5):
                raise TimeoutError
            return super().run(call)

    ports = EnginePorts(
        Interrupted(),
        ListRecorder(),
        FakeClock(),
        KeysOutputs(),
        lambda: 0.5,
        interrupt=stopped.set,
    )

    with pytest.raises(KeyboardInterrupt):
        run_workflow(plan_of(shell("a"), shell("b")), {}, ports)

    assert stopped.is_set()


def test_splits_a_wide_layer_in_linear_work_when_read_only_and_writing_nodes_alternate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    fits = plan_module._Batch.fits

    def counted(batch: object, node: object) -> bool:
        calls.append(1)
        return fits(batch, node)  # type: ignore[arg-type]

    monkeypatch.setattr(plan_module._Batch, "fits", counted)
    nodes = [shell(f"n{i}", mutates_checkout=bool(i % 2)) for i in range(4000)]

    plan = plan_of(*nodes)

    assert len(plan.layers) == 2
    assert len(calls) <= 2 * len(nodes)
