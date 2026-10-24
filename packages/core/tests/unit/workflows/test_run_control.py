"""Run control: a run paused before a node by a breakpoint or by Step, which no gate holds
(AC-507.9, .10, .11, .14; docs/design/workflow-engine-rules.md § Run control)."""

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.policy_gates import PolicyAsk, gated_plan
from agent_hub.core.scenarios.tree_translate import block_map
from agent_hub.core.testing.workflow_fakes import (
    AnswerBook,
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ListTrace,
    Scripted,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.gates import GateAnswer, OpenGate
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import NodeCall, NodeReply
from agent_hub.core.workflows.run_control import DebugPause, DebugReason, PauseReason, RunControl
from agent_hub.core.workflows.run_state import RunReport, RunState
from agent_hub.core.workflows.substitution import NodeResult

TREES = Path(__file__).parents[2] / "data" / "scenarios" / "blocks" / "tree"
# The tree samples' inputs: synthetic values.
ORDER_INPUTS = {"webshop_order_id": "w-1", "personal_name": "dev-a", "aws_account_id": "0" * 12}
APPROVE = GateAnswer("approve", approver="Ada")
ASK = PolicyAsk(action="fixture/queue-send", effect="write", environment="staging")
# What each sample's polled and captured nodes answer, poll after poll; every other action
# answers ``{}``.
REPLIES: Mapping[str, Mapping[str, list[JsonValue]]] = {
    "b2b-credit-order": {
        "fetch-order--2": [
            {"order_status": "ON_HOLD", "cover_status": "NONE", "order_id": "o-1"},
            {"order_status": "ON_HOLD", "cover_status": "PENDING", "order_id": "o-1"},
        ],
        "quote--2": [
            {"cover_status": "QUOTED", "payment_status": "CREDIT_CONFIRMED", "open_tasks": 2}
        ],
        "switch-to-fedex--5": [{"order_status": "PROCESSING_COMPLETED"}],
        "dispatch--2": [{"invoice_status": "CREATED", "invoice_number": "inv-1"}],
        "send-invoice--2": [
            {"invoice_status": "CREATED_ON_PLATFORM", "invoice_update_job_id": "j-2"}
        ],
        "activation--2": [{"activation_job_id": "j-3"}],
        "activation--4": [{"cover_status": "ACTIVATED"}],
        "payment--2": [{"paid": True, "payment_job_id": "j-4"}],
        "payment--4": [{"cover_status": "PENDING"}, {"cover_status": "SETTLED"}],
    },
    "blocks-together": {"fix-shipping--1": [{"order_id": "o-1"}]},
    "blocks-repeat": {
        "poll-cover--1": [{"order_id": "o-1"}],
        "poll-cover--2__poll": [
            {"activation_job_id": "j-1", "cover_status": "QUOTED"},
            {"activation_job_id": "j-1", "cover_status": "ACTIVATED"},
        ],
    },
    "blocks-nested": {
        "route-order--1": [
            {"order_status": "ON_HOLD", "order_id": "o-1", "cover_status": "QUOTED"},
        ],
    },
}
# The approvals the samples may reach, approved at once.
ANSWERS = {
    ("invoice-pdf--1", 1): APPROVE,
    ("payment--1", 1): APPROVE,
    ("route-order--2-then-1-else-1", 1): APPROVE,
}


@dataclass
class Breakpoints:
    """A ``RunControl`` that pauses before each node of ``at``, for the block it names; ``asked``
    keeps every node it was asked about, in order."""

    at: Mapping[str, str] = field(default_factory=dict)
    reason: DebugReason = "breakpoint"
    asked: list[str] = field(default_factory=list)

    def debugging(self) -> bool:
        return bool(self.at)

    def pause_before(self, node: str) -> PauseReason | None:
        self.asked.append(node)
        block = self.at.get(node)
        return None if block is None else PauseReason(block, self.reason)


class Stepping:
    """Step mode: a pause before every node, each its own block. The resume that follows runs
    the node it paused before and pauses before the next."""

    def debugging(self) -> bool:
        return True

    def pause_before(self, node: str) -> PauseReason:
        return PauseReason(node, "step")


class Replies(ScriptedRunner):
    """``ScriptedRunner`` whose node with nothing left answers ``{}``, an action's JSON."""

    def run(self, call: NodeCall) -> NodeReply:
        reply = super().run(call)
        return reply if reply.text else NodeReply("{}")


class Passes:
    """One run over the fakes, pass after pass: each resume starts from the state the pass
    before left, with the run control ``next`` is given (a debug command changes it)."""

    def __init__(
        self,
        plan: WorkflowPlan,
        runner: ScriptedRunner | None = None,
        *,
        inputs: Mapping[str, JsonValue] | None = None,
        answers: Mapping[tuple[str, int], GateAnswer] | None = None,
    ) -> None:
        self.plan, self.inputs = plan, dict(inputs or {})
        self.runner = runner or ScriptedRunner()
        self.recorder, self.trace, self.clock = ListRecorder(), ListTrace(), FakeClock()
        self.answers = dict(answers or {})
        self.reports: list[RunReport] = []
        self.ran: list[list[str]] = []

    def next(self, control: RunControl | None) -> RunReport:
        prior = self.reports[-1].state if self.reports else None
        ports = EnginePorts(
            self.runner,
            self.recorder,
            self.clock,
            KeysOutputs(),
            lambda: 0.5,
            gates=AnswerBook(self.answers),
            trace=self.trace,
            control=control,
        )
        done = len(self.runner.calls)
        report = run_workflow(self.plan, self.inputs, ports, prior=prior)
        self.reports.append(report)
        self.ran.append(self.runner.ran()[done:])
        return report

    def to_end(self, control: RunControl | None, *, most: int = 200) -> RunReport:
        """Resume with ``control`` until the run ends, at most ``most`` passes."""
        for _ in range(most):
            report = self.next(control)
            if report.status != "paused":
                return report
        pytest.fail(f"the run did not end in {most} passes")

    def started(self) -> list[str]:
        return [start.node for start in self.recorder.starts]


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "shell", "command": ["true"], "depends_on": list(depends_on)}
    return node | keys


def tree(name: str) -> dict[str, Any]:
    content = yaml.safe_load((TREES / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def tree_run(name: str, failing: str | None = None) -> Passes:
    """A run of the tree sample ``name`` over its replies, ``failing``'s first attempt failed."""
    replies: dict[str, list[Scripted]] = {
        node: [json.dumps(output) for output in outputs] for node, outputs in REPLIES[name].items()
    }
    if failing is not None:
        replies[failing] = [NodeFailedError("exec_failed", "exit 1")]
    plan = plan_workflow(parse_workflow(tree(name)))
    return Passes(plan, Replies(replies), inputs=ORDER_INPUTS, answers=ANSWERS)


# AC-507.9: a breakpoint on each block of the reference scenario.
REFERENCE_ADDRESSES = [block.address for block in block_map(tree("b2b-credit-order")).blocks]


@pytest.mark.parametrize("address", REFERENCE_ADDRESSES)
def test_pauses_before_the_block_when_a_breakpoint_holds_its_address(address: str) -> None:
    run = tree_run("b2b-credit-order")
    blocks = block_map(tree("b2b-credit-order"))
    block = blocks.block(address)
    assert block is not None
    entries = blocks.run_entries(run.plan)[address]
    order = [node.id for node in run.plan.all_nodes()]
    before = order[: order.index(entries[0])]

    report = run.next(Breakpoints(dict.fromkeys(entries, address)))

    assert (report.status, report.reason) == ("paused", entries[0])
    assert report.state.pause == DebugPause(entries[0], address, "breakpoint")
    assert report.state.gates == {}
    assert not set(block.nodes) & set(run.started())
    assert run.started() == before
    assert [end.status for end in run.recorder.ends] == ["ok"] * len(before)
    assert {request.node for request in run.recorder.gates} <= set(before)
    assert run.recorder.run_ends == []


def test_runs_the_block_and_goes_on_when_a_breakpoint_pause_is_continued() -> None:
    run = tree_run("b2b-credit-order")
    control = Breakpoints({"quote--2": "2.2", "payment--3": "8.3"})

    first = run.next(control)
    second = run.next(control)
    last = run.next(control)

    assert first.state.pause == DebugPause("quote--2", "2.2", "breakpoint")
    assert run.ran[1][0] == "quote--2"
    assert second.state.pause == DebugPause("payment--3", "8.3", "breakpoint")
    assert run.ran[2] == ["payment--3", "payment--4", "payment--4"]
    assert (last.status, last.state.pause) == ("done", None)


def test_runs_every_entry_of_the_block_when_a_breakpoint_on_an_if_is_continued() -> None:
    run = tree_run("blocks-nested")
    entries = block_map(tree("blocks-nested")).run_entries(run.plan)["1.2"]
    control = Breakpoints(dict.fromkeys(entries, "1.2"))

    first = run.next(control)
    last = run.next(control)

    assert len(entries) == 3
    assert (first.reason, first.state.pause) == (
        entries[0],
        DebugPause(entries[0], "1.2", "breakpoint"),
    )
    assert run.ran[0] == ["route-order--1"]
    assert last.status == "done"
    assert run.ran[1] == [
        "route-order--2-then-1-then-1",
        "route-order--2-then-2",
        "route-order--2-then-3-then-1",
        "route-order--3",
    ]


def test_runs_the_layer_in_order_and_stops_when_it_holds_a_node_to_pause_at() -> None:
    plan = a_plan(shell("a"), shell("b", "a"), shell("c", "a"), shell("d", "a"), shell("e", "b"))
    run = Passes(plan)

    report = run.next(Breakpoints({"c": "1.3"}))

    assert plan.layers[1] == ("b", "c", "d")
    assert (report.status, report.reason) == ("paused", "c")
    assert report.state.pause == DebugPause("c", "1.3", "breakpoint")
    assert run.runner.ran() == ["a", "b"]
    assert run.started() == ["a", "b"]
    assert run.recorder.gates == []


class GatedRunner(ScriptedRunner):
    """``first`` answers only once ``second`` has run: they can only both end concurrently."""

    def __init__(self, first: str, second: str) -> None:
        super().__init__()
        self.first, self.second = first, second
        self.second_ran = threading.Event()

    def run(self, call: NodeCall) -> NodeReply:
        if call.node.id == self.first and not self.second_ran.wait(timeout=5):
            raise TimeoutError
        try:
            return super().run(call)
        finally:
            if call.node.id == self.second:
                self.second_ran.set()


def test_runs_a_layer_concurrently_when_it_holds_no_node_to_pause_at() -> None:
    plan = a_plan(shell("a"), shell("b", "a"), shell("c", "a"), shell("d", "b", "c"))
    control = Breakpoints({"d": "1.4"})
    run = Passes(plan, GatedRunner("b", "c"))

    report = run.next(control)

    assert (report.reason, run.runner.ran()) == ("d", ["a", "c", "b"])
    assert control.asked == ["a", "b", "c", "d"]


def test_asks_nothing_and_runs_as_before_when_no_breakpoint_or_step_is_on() -> None:
    plan = a_plan(shell("a"), shell("b", "a"), shell("c", "a"), shell("d", "b", "c"))
    control = Breakpoints()
    run = Passes(plan, GatedRunner("b", "c"))

    report = run.next(control)

    assert (report.status, report.state.pause) == ("done", None)
    assert control.asked == []


def test_never_pauses_before_a_node_when_the_resume_reuses_it() -> None:
    plan = a_plan(shell("a"), shell("b", "a"))
    prior = RunState({"a": NodeResult("completed", "")}, {"a": 1})
    control = Breakpoints({"a": "1.1"})
    ports = EnginePorts(
        ScriptedRunner(), ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5, control=control
    )

    report = run_workflow(plan, {}, ports, prior=prior)

    assert report.status == "done"
    assert control.asked == ["b"]


REPEAT = {
    "id": "g",
    "type": "loop_group",
    "max_iterations": 3,
    "until_when": "$x.output == 'done'",
    "nodes": [shell("w"), shell("x", "w")],
}


def test_holds_the_iteration_and_resumes_in_it_when_a_body_node_pauses() -> None:
    plan = a_plan(shell("a"), REPEAT | {"depends_on": ["a"]}, shell("after", "g"))
    run = Passes(plan, ScriptedRunner({"g__x": ["again", "done"]}))
    control = Breakpoints({"g__x": "1.2.2"})

    first = run.next(control)
    second = run.next(control)
    last = run.next(control)

    assert (first.status, first.reason) == ("paused", "g__x")
    assert first.state.pause == DebugPause("g__x", "1.2.2", "breakpoint")
    held = first.state.groups["g"]
    assert (held.attempt, held.iteration, list(held.current)) == (1, 1, ["g__w"])
    assert run.ran[:2] == [["a", "g__w"], ["g__x", "g__w"]]
    assert (second.reason, second.state.groups["g"].iteration) == ("g__x", 2)
    assert (last.status, run.ran[2]) == ("done", ["g__x", "after"])
    assert [start.node for start in run.recorder.starts].count("g") == 1
    assert [(end.attempt, end.status) for end in run.recorder.ends if end.node == "g"] == [
        (1, "ok")
    ]


def test_pauses_before_the_group_when_a_breakpoint_holds_its_node() -> None:
    plan = a_plan(shell("a"), REPEAT | {"depends_on": ["a"]})
    run = Passes(plan, ScriptedRunner({"g__x": ["done"]}))
    control = Breakpoints({"g": "1.2"})

    first = run.next(control)
    started = run.started()
    last = run.next(control)

    assert first.state.pause == DebugPause("g", "1.2", "breakpoint")
    assert (first.state.groups, started) == ({}, ["a"])
    assert (last.status, run.ran[1]) == ("done", ["g__w", "g__x"])


def test_opens_the_ask_and_waits_for_its_answer_when_a_breakpoint_before_it_is_continued() -> None:
    # AC-507.10: the pause never answers the gate; only a person's approval runs the step.
    document = parse_workflow(
        {"version": 1, "name": "demo", "revision": 1, "nodes": [shell("a"), shell("b", "a")]}
    )
    plan = gated_plan(document, includes=None, asks={"b": ASK})
    run = Passes(plan)
    control = Breakpoints({"b__ask": "1.2"})

    paused = run.next(control)
    asked = run.next(control)
    waiting = run.next(control)
    run.answers[("b__ask", 1)] = APPROVE
    done = run.next(control)

    assert (paused.reason, paused.state.pause) == (
        "b__ask",
        DebugPause("b__ask", "1.2", "breakpoint"),
    )
    assert paused.state.gates == {}
    assert run.ran[0] == ["a"]
    assert (asked.status, asked.reason, asked.state.pause) == ("paused", "b__ask", None)
    assert asked.state.gates == {"b__ask": OpenGate(1)}
    assert [request.node for request in run.recorder.gates] == ["b__ask"]
    assert (waiting.status, waiting.state.gates, waiting.state.pause) == (
        "paused",
        {"b__ask": OpenGate(1)},
        None,
    )
    assert run.ran[1:3] == [[], []]
    assert done.status == "done"
    assert run.ran[3] == ["b"]
    assert run.recorder.end_of("b__ask").output == {"decision": "approve", "approver": "Ada"}


def test_runs_one_node_per_resume_when_the_run_is_stepped() -> None:
    # AC-507.11 (core): each Step resumes and runs only the node the run paused before; a
    # Continue runs to the next breakpoint, then to the end.
    plan = a_plan(shell("a"), shell("b", "a"), shell("c", "a"), shell("d", "b", "c"))
    run = Passes(plan)

    stepped = [run.next(Stepping()) for _ in range(3)]
    to_break = run.next(Breakpoints({"d": "1.4"}))
    last = run.next(Breakpoints({"d": "1.4"}))

    assert [report.state.pause for report in stepped] == [
        DebugPause("a", "a", "step"),
        DebugPause("b", "b", "step"),
        DebugPause("c", "c", "step"),
    ]
    assert run.ran[:3] == [[], ["a"], ["b"]]
    assert to_break.state.pause == DebugPause("d", "1.4", "breakpoint")
    assert run.ran[3] == ["c"]
    assert (last.status, run.ran[4]) == ("done", ["d"])


def test_steps_into_every_iteration_when_a_stepped_run_reaches_a_group() -> None:
    plan = a_plan(REPEAT)
    run = Passes(plan, ScriptedRunner({"g__x": ["again", "done"]}))

    report = run.to_end(Stepping())

    assert report.status == "done"
    assert run.ran == [[], [], ["g__w"], ["g__x"], ["g__w"], ["g__x"]]
    assert [r.state.pause for r in run.reports[:-1]] == [
        DebugPause(node, node, "step") for node in ("g", "g__w", "g__x", "g__w", "g__x")
    ]


def test_lets_the_gate_pause_win_when_a_gate_opens_in_the_pass_that_stops_before_a_node() -> None:
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["a"]}
    plan = a_plan(shell("a"), gate, shell("side", "a"), shell("after", "ok", "side"))
    run = Passes(plan)
    control = Breakpoints({"side": "1.3"})

    gated = run.next(control)
    started = run.started()
    run.answers[("ok", 1)] = APPROVE
    stopped = run.next(control)
    last = run.next(control)

    assert (gated.reason, gated.state.gates, gated.state.pause) == ("ok", {"ok": OpenGate(1)}, None)
    assert started == ["a", "ok"]
    assert stopped.state.pause == DebugPause("side", "1.3", "breakpoint")
    assert (last.status, run.ran[2]) == ("done", ["side", "after"])


def test_keeps_the_failure_and_runs_nothing_again_when_a_pause_after_it_is_continued() -> None:
    plan = a_plan(
        shell("a"), shell("b", "a"), shell("c", "b"), shell("d", "c", trigger_rule="all_done")
    )
    run = Passes(plan, ScriptedRunner({"b": [NodeFailedError("exec_failed", "exit 1")]}))
    control = Breakpoints({"d": "1.4"})

    paused = run.next(control)
    last = run.next(control)

    assert (paused.reason, run.ran[0]) == ("d", ["a", "b"])
    assert paused.state.nodes["c"] == NodeResult("skipped")
    assert run.recorder.end_of("c").skip_cause == "upstream_failed"
    assert (last.status, last.reason, run.ran[1]) == ("failed", "b", ["d"])
    assert [(end.node, end.status) for end in run.recorder.ends if end.node == "b"] == [
        ("b", "failed")
    ]
    assert last.state.nodes["b"] == NodeResult("failed")


def test_runs_an_always_run_node_once_when_a_pause_after_it_is_continued() -> None:
    plan = a_plan(shell("a", always_run=True), shell("b", "a"))
    run = Passes(plan)

    run.next(Breakpoints({"b": "1.2"}))
    last = run.next(Breakpoints({"b": "1.2"}))

    assert last.status == "done"
    assert run.ran == [["a"], ["b"]]


def end_of(run: Passes, report: RunReport) -> tuple[object, ...]:
    captures = [(c.node, c.name, c.value) for c in run.trace.captures]
    return report.status, report.outcome, dict(report.state.nodes), captures


@pytest.mark.parametrize(
    ("name", "failing"),
    [
        ("b2b-credit-order", None),
        ("b2b-credit-order", "quote--2"),
        ("blocks-together", None),
        ("blocks-together", "fix-shipping--2-p2-1"),
        ("blocks-repeat", None),
        ("blocks-nested", None),
    ],
    ids=["reference", "reference-failed", "together", "together-failed", "repeat", "nested"],
)
def test_ends_with_the_same_results_when_a_run_pauses_before_every_block_or_is_stepped(
    name: str, failing: str | None
) -> None:
    # AC-507.14: pauses change when a run stops, never its path or results.
    straight = tree_run(name, failing)
    every = tree_run(name, failing)
    # Each block's entry nodes break for it; a node entering nested blocks, for the outermost.
    every_block: dict[str, str] = {}
    for address, entries in block_map(tree(name)).run_entries(every.plan).items():
        for entry in entries:
            every_block.setdefault(entry, address)
    stepped = tree_run(name, failing)

    plain = straight.to_end(None)
    broken = every.to_end(Breakpoints(every_block))
    steps = stepped.to_end(Stepping())

    assert plain.status == ("done" if failing is None else "failed")
    assert len(straight.reports) == 1
    assert len(every.reports) > len(set(every_block.values())) // 2
    assert len(stepped.reports) >= len(every.reports)
    assert {r.state.pause.reason for r in every.reports[:-1] if r.state.pause} == {"breakpoint"}
    assert end_of(every, broken) == end_of(straight, plain)
    assert end_of(stepped, steps) == end_of(straight, plain)
    assert (
        sorted(every.runner.ran()) == sorted(stepped.runner.ran()) == sorted(straight.runner.ran())
    )


def test_pauses_before_the_rerun_node_when_a_gate_resume_runs_a_failed_node_again() -> None:
    # The gate's resume reruns the failure and its stale skipped descendant: each is asked again,
    # so answering the gate never passes a breakpoint, and the answer waits for the resume.
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["c"]}
    plan = a_plan(
        shell("a"),
        shell("b", "a"),
        shell("c", "b"),
        gate | {"trigger_rule": "all_done"},
        shell("after", "ok"),
    )
    run = Passes(plan, ScriptedRunner({"b": [NodeFailedError("exec_failed", "exit 1"), ""]}))
    control = Breakpoints({"c": "1.3"})

    first = run.next(control)
    gated = run.next(control)
    run.answers[("ok", 1)] = APPROVE
    rerun = run.next(control)
    last = run.next(control)

    assert first.state.pause == DebugPause("c", "1.3", "breakpoint")
    assert run.ran[:2] == [["a", "b"], []]
    assert (gated.reason, gated.state.gates, gated.state.pause) == ("ok", {"ok": OpenGate(1)}, None)
    assert (rerun.status, rerun.reason) == ("paused", "c")
    assert rerun.state.pause == DebugPause("c", "1.3", "breakpoint")
    assert run.ran[2] == ["b"]
    assert rerun.state.gates == {"ok": OpenGate(1)}
    assert (last.status, run.ran[3]) == ("done", ["c", "after"])
    assert [request.node for request in run.recorder.gates] == ["ok"]
    assert run.recorder.end_of("ok").output == {"decision": "approve", "approver": "Ada"}


def test_asks_again_about_an_always_run_node_when_a_gate_resume_runs_it_again() -> None:
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["a"]}
    plan = a_plan(shell("a"), shell("b", "a", always_run=True), gate, shell("after", "ok", "b"))
    run = Passes(plan)

    gated = run.next(Breakpoints({"after": "1.4"}))
    run.answers[("ok", 1)] = APPROVE
    control = Breakpoints({"b": "1.2"})
    rerun = run.next(control)
    last = run.next(control)

    assert (gated.reason, run.ran[0]) == ("ok", ["a", "b"])
    assert rerun.state.pause == DebugPause("b", "1.2", "breakpoint")
    assert (last.status, run.ran[2]) == ("done", ["b", "after"])


def test_runs_the_stale_child_again_when_a_gate_resume_changes_its_ancestor_and_it_pauses() -> None:
    # The gate's resume reruns the always_run ancestor, whose output changes: its completed child
    # is stale, so the resume from the pause before it runs it again, as an unpaused one does.
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["b"]}
    plan = a_plan(shell("a", always_run=True), shell("b", "a"), gate, shell("after", "ok"))

    def a_run() -> Passes:
        return Passes(plan, ScriptedRunner({"a": ["one", "two"], "b": ["b1", "b2"]}))

    straight, paused = a_run(), a_run()
    for run in (straight, paused):
        assert run.next(None).reason == "ok"
        run.answers[("ok", 1)] = APPROVE
    plain = straight.to_end(None)
    control = Breakpoints({"b": "1.2"})
    stopped = paused.next(control)
    last = paused.to_end(control)

    assert straight.ran[1] == ["a", "b", "after"]
    assert stopped.state.pause == DebugPause("b", "1.2", "breakpoint")
    assert "b" in stopped.state.rerun
    assert paused.ran[1:] == [["a"], ["b", "after"]]
    assert last.state.nodes["b"] == plain.state.nodes["b"] != straight.reports[0].state.nodes["b"]
    assert end_of(paused, last) == end_of(straight, plain)


def test_runs_the_stale_child_again_when_a_gate_resume_completes_a_failed_ancestor() -> None:
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["c"]}
    plan = a_plan(
        shell("a"),
        shell("b", "a"),
        shell("c", "b", trigger_rule="all_done"),
        gate,
        shell("after", "ok"),
    )

    def a_run() -> Passes:
        failed = NodeFailedError("exec_failed", "exit 1")
        return Passes(plan, ScriptedRunner({"b": [failed, "b2"], "c": ["c1", "c2"]}))

    straight, paused = a_run(), a_run()
    for run in (straight, paused):
        assert run.next(None).reason == "ok"
        run.answers[("ok", 1)] = APPROVE
    plain = straight.to_end(None)
    control = Breakpoints({"c": "1.3"})
    stopped = paused.next(control)
    last = paused.to_end(control)

    assert straight.ran[1] == ["b", "c", "after"]
    assert stopped.state.pause == DebugPause("c", "1.3", "breakpoint")
    assert paused.ran[1:] == [["b"], ["c", "after"]]
    assert last.state.nodes["c"] == NodeResult("completed", "c2")
    assert end_of(paused, last) == end_of(straight, plain)


def stale_skip_run() -> Passes:
    # ``a`` fails, so the first pass skips ``s`` and opens the gate; the gate's resume completes
    # ``a``, which makes ``x`` and that skip of ``s`` stale.
    gate = {
        "id": "ok",
        "type": "approval",
        "message": "Ship?",
        "depends_on": ["x", "s"],
        "trigger_rule": "all_done",
    }
    plan = a_plan(
        shell("a"),
        shell("x", "a", trigger_rule="all_done"),
        shell("s", "a"),
        gate,
        shell("after", "ok"),
    )
    run = Passes(plan, ScriptedRunner({"a": [NodeFailedError("exec_failed", "exit 1"), "a2"]}))
    assert run.next(None).reason == "ok"
    assert run.reports[0].state.nodes["s"].state == "skipped"
    run.answers[("ok", 1)] = APPROVE
    return run


def test_pauses_before_the_stale_skip_when_a_resume_after_the_gate_reaches_its_breakpoint() -> None:
    run = stale_skip_run()
    control = Breakpoints({"x": "1.2", "s": "1.3"})

    before_x = run.next(control)
    before_s = run.next(control)
    last = run.to_end(control)

    assert before_x.state.pause == DebugPause("x", "1.2", "breakpoint")
    assert "s" in before_x.state.rerun
    assert run.ran[1:3] == [["a"], ["x"]]
    assert (before_s.status, before_s.state.pause) == (
        "paused",
        DebugPause("s", "1.3", "breakpoint"),
    )
    assert (last.status, run.ran[3]) == ("done", ["s", "after"])


def test_runs_only_the_next_node_when_a_step_follows_a_stale_skip_of_an_earlier_pass() -> None:
    run = stale_skip_run()

    stops = [run.next(Stepping()) for _ in range(3)]

    assert [report.reason for report in stops] == ["a", "x", "s"]
    assert run.ran[1:] == [[], ["a"], ["x"]]
    assert stops[2].state.pause is not None and stops[2].state.pause.node == "s"


def test_pauses_before_the_stale_skip_when_a_debug_resume_runs_its_owed_ancestor_again() -> None:
    # The pass that pauses before the failed ``x`` owes ``x`` a rerun but never reaches the skip
    # below it; the resume completes ``x``, which makes that skip of ``s`` stale, so it is asked
    # again, as the gate's resume with no pause before ``x`` asks it.
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["s"]}
    plan = a_plan(
        shell("a"),
        shell("x", "a"),
        shell("s", "x"),
        gate | {"trigger_rule": "all_done"},
        shell("after", "ok"),
    )

    def a_run() -> Passes:
        run = Passes(plan, ScriptedRunner({"x": [NodeFailedError("exec_failed", "exit 1"), "x2"]}))
        assert run.next(None).reason == "ok"
        assert run.reports[0].state.nodes["s"].state == "skipped"
        run.answers[("ok", 1)] = APPROVE
        return run

    straight, paused = a_run(), a_run()
    plain_control = Breakpoints({"s": "1.3"})
    plain_stop = straight.next(plain_control)
    plain = straight.to_end(plain_control)
    control = Breakpoints({"x": "1.2", "s": "1.3"})
    before_x = paused.next(control)
    before_s = paused.next(control)
    last = paused.to_end(control)

    assert plain_stop.state.pause == DebugPause("s", "1.3", "breakpoint")
    assert before_x.state.pause == DebugPause("x", "1.2", "breakpoint")
    assert before_x.state.rerun == frozenset({"x"})
    assert (before_s.status, before_s.reason) == ("paused", "s")
    assert before_s.state.pause == DebugPause("s", "1.3", "breakpoint")
    assert paused.ran[1:] == [[], ["x"], ["s", "after"]]
    assert (last.status, end_of(paused, last)) == ("done", end_of(straight, plain))
