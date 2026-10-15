"""The ``approval`` and ``wait`` gates: a pause, its request, and the answer that ends it."""

import threading
from collections.abc import Mapping
from datetime import timedelta

import pytest

from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.workflow_fakes import (
    START,
    AnswerBook,
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.engine import MAX_LAYER_THREADS, EnginePorts, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.gates import GateAnswer, OpenGate, answer_problem, gate_id
from agent_hub.core.workflows.plan import plan_workflow
from agent_hub.core.workflows.ports import NodeCall, NodeReply
from agent_hub.core.workflows.run_state import RunReport, RunState
from agent_hub.core.workflows.substitution import NodeResult

DECISIONS = [{"id": "ship", "label": "Ship"}, {"id": "rework", "label": "Rework"}]


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "shell", "command": ["true"], "depends_on": list(depends_on)}
    return node | keys


def approval(**keys: object) -> dict[str, object]:
    node = {"id": "gate", "type": "approval", "message": "Ship $a.output?", "depends_on": ["a"]}
    return node | keys


def wait(**keys: object) -> dict[str, object]:
    return {"id": "gate", "type": "wait", "depends_on": ["a"]} | keys


class Gated:
    """One run over the fakes, its answers given per ``(node, attempt)``."""

    def __init__(
        self,
        *nodes: dict[str, object],
        answers: Mapping[tuple[str, int], GateAnswer] | None = None,
        prior: RunState | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        self.runner = ScriptedRunner({"a": ["red"]})
        self.recorder = ListRecorder()
        self.clock = clock or FakeClock()
        ports = EnginePorts(
            self.runner,
            self.recorder,
            self.clock,
            KeysOutputs(),
            lambda: 0.5,
            gates=AnswerBook(dict(answers or {})),
        )
        self.report: RunReport = run_workflow(a_plan(*nodes), {}, ports, prior=prior)


def paused_at_gate(attempt: int = 1) -> RunState:
    return RunState(
        {"a": NodeResult("completed", "red")},
        {"a": 1, "gate": attempt},
        {},
        {"gate": OpenGate(attempt)},
    )


def test_pauses_and_records_the_request_when_an_approval_is_reached() -> None:
    run = Gated(shell("a"), approval(), shell("b", "gate"))

    assert (run.report.status, run.report.reason) == ("paused", "gate")
    assert run.report.state.gates == {"gate": OpenGate(1)}
    [request] = run.recorder.gates
    assert (request.node, request.attempt, request.kind, request.form) == (
        "gate",
        1,
        "approval",
        "decision",
    )
    assert (request.text, request.choices) == ("Ship red?", ("approve", "reject"))
    assert [start.node for start in run.recorder.starts] == ["a", "gate"]
    assert [end.node for end in run.recorder.ends] == ["a"]
    assert run.recorder.run_ends == []
    assert run.runner.ran() == ["a"]


def test_completes_with_the_decision_and_runs_on_when_resumed_with_an_answer() -> None:
    answers = {("gate", 1): GateAnswer("rework", "add tests")}
    nodes = (shell("a"), approval(decisions=DECISIONS, capture_response=True))
    when = "$gate.output.decision == 'rework'"

    run = Gated(*nodes, shell("b", "gate", when=when), answers=answers, prior=paused_at_gate())

    assert run.report.status == "done"
    assert run.recorder.end_of("gate").output == {"decision": "rework", "text": "add tests"}
    assert run.recorder.gates == []
    assert run.runner.ran() == ["b"]


def test_leaves_the_text_out_when_the_approval_does_not_capture_it() -> None:
    answers = {("gate", 1): GateAnswer("approve", "fine")}

    run = Gated(shell("a"), approval(), answers=answers, prior=paused_at_gate())

    assert run.recorder.end_of("gate").output == {"decision": "approve"}


def test_pauses_again_without_a_new_request_when_resumed_before_an_answer() -> None:
    run = Gated(shell("a"), approval(), shell("b", "gate"), prior=paused_at_gate(2))

    assert (run.report.status, run.report.state.gates) == ("paused", {"gate": OpenGate(2)})
    assert run.recorder.gates == []
    assert run.recorder.starts == []


def test_fails_config_when_the_answer_is_not_a_declared_decision() -> None:
    answers = {("gate", 1): GateAnswer("maybe")}

    run = Gated(shell("a"), approval(), answers=answers, prior=paused_at_gate())

    assert (run.report.status, run.recorder.end_of("gate").failure_kind) == ("failed", "config")


def test_reuses_a_decided_approval_when_a_later_failure_is_resumed() -> None:
    prior = RunState(
        {
            "a": NodeResult("completed", "red"),
            "gate": NodeResult("completed", {"decision": "approve"}),
        },
        {"a": 1, "gate": 1, "b": 1},
    )

    run = Gated(shell("a"), approval(), shell("b", "gate"), prior=prior)

    assert run.report.status == "done"
    assert run.recorder.end_of("gate").skip_cause == "prior_success"


def test_pauses_until_the_due_time_then_completes_when_a_duration_wait_resumes() -> None:
    first = Gated(shell("a"), wait(duration="2h"))
    [request] = first.recorder.gates
    assert (request.form, request.due) == ("timer", START + timedelta(hours=2))
    held = RunState(
        {"a": NodeResult("completed", "red")}, {"a": 1, "gate": 1}, {}, first.report.state.gates
    )

    early = Gated(
        shell("a"), wait(duration="2h"), prior=held, clock=FakeClock(START + timedelta(hours=1))
    )
    late = Gated(
        shell("a"), wait(duration="2h"), prior=held, clock=FakeClock(START + timedelta(hours=3))
    )

    assert (first.report.status, early.report.status, late.report.status) == (
        "paused",
        "paused",
        "done",
    )
    assert late.recorder.end_of("gate").output == {"at": (START + timedelta(hours=3)).isoformat()}


@pytest.mark.parametrize(
    ("until", "status"),
    [("2026-10-15T08:00:00+00:00", "done"), ("2026-10-16T09:00:00+02:00", "paused")],
)
def test_ends_once_the_time_passed_when_a_wait_names_an_instant(until: str, status: str) -> None:
    run = Gated(shell("a"), wait(until=until))

    assert run.report.status == status


def test_fails_config_when_until_reads_a_value_that_is_not_an_instant() -> None:
    run = Gated(shell("a"), wait(until="$a.output"))

    assert (run.report.status, run.recorder.end_of("gate").failure_kind) == ("failed", "config")


@pytest.mark.parametrize(
    ("keys", "answer", "output"),
    [
        ({"attention": "Which colour?"}, GateAnswer(text="blue"), {"text": "blue"}),
        (
            {"attention": "Pick", "options": DECISIONS},
            GateAnswer("ship"),
            {"choice": "ship", "text": ""},
        ),
    ],
)
def test_completes_with_the_answer_when_an_attention_wait_is_answered(
    keys: dict[str, object], answer: GateAnswer, output: JsonValue
) -> None:
    first = Gated(shell("a"), wait(**keys))
    answered = Gated(
        shell("a"), wait(**keys), answers={("gate", 1): answer}, prior=paused_at_gate()
    )

    assert first.report.status == "paused"
    assert answered.recorder.end_of("gate").output == output


@pytest.mark.parametrize(
    ("gate", "answer", "problem"),
    [
        (("decision", "approve"), GateAnswer("approve", "ok"), None),
        (("decision", "approve"), GateAnswer("ship"), 'no decision "ship"'),
        (("decision", "approve"), GateAnswer(text="ok"), "a decision"),
        (("choice", "red"), GateAnswer("red"), None),
        (("choice", "red"), GateAnswer(text="red"), "an option"),
        (("text",), GateAnswer(text="blue"), None),
        (("text",), GateAnswer(text="  "), "a text answer"),
        (("text",), GateAnswer("blue", "x"), "takes no option"),
        (("timer",), GateAnswer(text="now"), "takes no answer"),
    ],
)
def test_checks_the_answer_against_the_gate_form_when_one_is_given(
    gate: tuple[str, ...], answer: GateAnswer, problem: str | None
) -> None:
    form, *choices = gate

    found = answer_problem(form, tuple(choices), answer)  # type: ignore[arg-type]

    assert found is None if problem is None else problem in (found or "")


def test_names_the_gate_by_run_node_and_attempt_when_asked_for_its_id() -> None:
    assert gate_id("r1", "gate", 3) == "r1:gate:3"


def test_fails_unknown_when_the_answers_port_raises() -> None:
    class Broken(AnswerBook):
        def answer(self, node: str, attempt: int) -> GateAnswer | None:
            raise OSError("disk")

    recorder = ListRecorder()
    ports = EnginePorts(
        ScriptedRunner(), recorder, FakeClock(), KeysOutputs(), lambda: 0.5, gates=Broken()
    )

    report = run_workflow(a_plan(shell("a"), approval()), {}, ports)

    assert (report.status, recorder.end_of("gate").failure_kind) == ("failed", "unknown")


def test_ends_the_run_cancelled_when_default_decisions_are_rejected_and_nothing_reads_it() -> None:
    answers = {("gate", 1): GateAnswer("reject")}

    run = Gated(shell("a"), approval(), shell("b", "gate"), answers=answers, prior=paused_at_gate())

    assert (run.report.status, run.report.reason) == ("cancelled", "gate")
    assert run.recorder.end_of("gate").output == {"decision": "reject"}
    assert run.runner.ran() == []
    assert run.recorder.run_ends[-1].status == "cancelled"


def test_completes_the_gate_and_runs_on_when_a_condition_reads_the_rejected_decision() -> None:
    answers = {("gate", 1): GateAnswer("reject")}
    when = "$gate.output.decision == 'reject'"

    run = Gated(
        shell("a"),
        approval(),
        shell("b", "gate", when=when),
        answers=answers,
        prior=paused_at_gate(),
    )

    assert run.report.status == "done"
    assert run.runner.ran() == ["b"]


def test_completes_the_gate_when_authored_decisions_include_reject() -> None:
    decisions = [{"id": "approve", "label": "Go"}, {"id": "reject", "label": "Stop"}]
    answers = {("gate", 1): GateAnswer("reject")}

    run = Gated(
        shell("a"),
        approval(decisions=decisions),
        shell("b", "gate"),
        answers=answers,
        prior=paused_at_gate(),
    )

    assert run.report.status == "done"
    assert run.runner.ran() == ["b"]


@pytest.mark.parametrize(
    ("until", "status"),
    [("2026-10-22T09:00:00+00:00", "paused"), ("2026-10-22T09:00:01+00:00", "failed")],
)
def test_bounds_until_at_seven_days_when_the_gate_opens(until: str, status: str) -> None:
    run = Gated(shell("a"), wait(until=until))

    assert run.report.status == status
    if status == "failed":
        assert run.recorder.end_of("gate").failure_kind == "config"


# Gates inside a loop_group body: the iteration pauses and its resume picks it up again.
REWORK = {
    "id": "g",
    "type": "loop_group",
    "max_iterations": 3,
    "until_when": "$ok.output.decision == 'approve'",
    "nodes": [
        {"id": "work", "type": "shell", "command": ["fix", "$LOOP_PREV.ok.output.text"]},
        {"id": "side", "type": "shell", "command": ["lint"]},
        {
            "id": "ok",
            "type": "approval",
            "message": "Ship?",
            "capture_response": True,
            "depends_on": ["work"],
        },
    ],
}


def resumed(
    report: RunReport, answers: Mapping[tuple[str, int], GateAnswer], runner: ScriptedRunner
) -> tuple[RunReport, ListRecorder]:
    recorder = ListRecorder()
    ports = EnginePorts(
        runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5, gates=AnswerBook(dict(answers))
    )
    plan = a_plan(REWORK, shell("after", "g"))
    return run_workflow(plan, {}, ports, prior=report.state), recorder


def test_reworks_until_approved_when_a_body_approval_is_rejected_then_approved() -> None:
    runner = ScriptedRunner()
    first, _ = resumed(RunReport("paused", None, None, RunState()), {}, runner)
    rejected, middle = resumed(first, {("g__ok", 1): GateAnswer("reject", "add tests")}, runner)
    approved, last = resumed(rejected, {("g__ok", 2): GateAnswer("approve")}, runner)

    assert (first.status, first.reason) == ("paused", "g__ok")
    assert sorted(runner.ran()[:2]) == ["g__side", "g__work"]
    assert (rejected.status, rejected.reason) == ("paused", "g__ok")
    assert [g.node for g in middle.gates] == ["g__ok"]
    assert middle.gates[0].attempt == 2
    assert approved.status == "done"
    fixes = [call.argv for call in runner.calls if call.node.id == "g__work"]
    assert fixes == [("fix", ""), ("fix", "add tests")]
    assert runner.ran().count("g__side") == 2
    assert runner.ran()[-1] == "after"
    group_ends = [end for end in last.ends if end.node == "g"]
    assert [(end.attempt, end.status) for end in group_ends] == [(1, "ok")]
    assert last.end_of("g").output == {
        "work": "",
        "side": "",
        "ok": {"decision": "approve", "text": ""},
    }
    assert [start.node for start in middle.starts].count("g") == 0


def test_pauses_again_without_rerunning_the_iteration_when_resumed_before_an_answer() -> None:
    runner = ScriptedRunner()
    first, _ = resumed(RunReport("paused", None, None, RunState()), {}, runner)

    again, recorder = resumed(first, {}, runner)

    assert (again.status, again.reason) == ("paused", "g__ok")
    assert sorted(runner.ran()) == ["g__side", "g__work"]
    assert recorder.starts == []
    assert recorder.gates == []
    assert recorder.ends == []
    assert again.state.groups == first.state.groups


def test_opens_no_gate_after_an_interrupt_when_a_parallel_layer_is_stopped() -> None:
    # Every thread of the body layer holds a running shell when ``a`` interrupts the run; the
    # gate, queued behind them, is visited only once one returns, after the stop. No shell
    # raises, so nothing cancels the queued gate first.
    all_running, interrupted = threading.Barrier(MAX_LAYER_THREADS + 1), threading.Event()

    class Stopping(ScriptedRunner):
        def run(self, call: NodeCall) -> NodeReply:
            all_running.wait(timeout=5)
            if call.node.id == "a":
                raise KeyboardInterrupt
            assert interrupted.wait(timeout=5)
            return super().run(call)

    gate = {"id": "ok", "type": "approval", "message": "Ship?"}
    shells = [shell(f"w{index}") for index in range(MAX_LAYER_THREADS)]
    group = REWORK | {"nodes": [*shells, gate]}
    recorder = ListRecorder()
    ports = EnginePorts(
        Stopping(),
        recorder,
        FakeClock(),
        KeysOutputs(),
        lambda: 0.5,
        max_parallel=MAX_LAYER_THREADS + 1,
        interrupt=interrupted.set,
    )

    with pytest.raises(KeyboardInterrupt):
        run_workflow(a_plan(shell("a"), group), {}, ports)

    assert interrupted.is_set()
    assert recorder.gates == []


def body_failure_kind(*, pause: bool) -> str | None:
    """The group's failure kind when a body node failed before its gate: paused and resumed
    on the gate, or answered at once."""
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["work"]}
    group = REWORK | {"nodes": [shell("bad"), shell("work"), gate]}
    plan = a_plan(group)
    runner = ScriptedRunner({"g__bad": [NodeFailedError("exec_failed", "exit 1")]})
    answer = AnswerBook({("g__ok", 1): GateAnswer("approve")})
    prior = None
    if pause:
        first = EnginePorts(runner, ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5)
        prior = run_workflow(plan, {}, first).state
    recorder = ListRecorder()
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5, gates=answer)
    report = run_workflow(plan, {}, ports, prior=prior)
    assert report.status == "failed"
    return recorder.end_of("g").failure_kind


def test_fails_the_group_with_the_body_kind_when_a_failed_iteration_is_resumed() -> None:
    assert body_failure_kind(pause=True) == body_failure_kind(pause=False) == "exec_failed"


def test_keeps_the_run_going_when_a_body_condition_reads_the_previous_decision() -> None:
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["work"]}
    redo = shell("redo", when="$LOOP_PREV.ok.output.decision == 'reject'")
    group = REWORK | {"until_when": "$work.output == 'never'", "nodes": [shell("work"), gate, redo]}
    plan = a_plan(group)
    answers = AnswerBook({("g__ok", 1): GateAnswer("reject"), ("g__ok", 2): GateAnswer("approve")})
    runner = ScriptedRunner()
    ports = EnginePorts(
        runner, ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5, gates=answers
    )

    report = run_workflow(plan, {}, ports)

    assert (report.status, report.reason) == ("paused", "g__ok")
    assert runner.ran().count("g__redo") == 1


def test_lets_the_sibling_finish_before_the_pause_when_a_gate_shares_a_concurrent_layer() -> None:
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["a"]}
    plan = a_plan(shell("a"), gate, shell("side", "a"), shell("after", "ok", "side"))
    runner = ScriptedRunner()
    first = Gated(shell("a"), gate, shell("side", "a"), shell("after", "ok", "side"))

    assert (first.report.status, first.report.reason) == ("paused", "ok")
    assert first.runner.ran() == ["a", "side"]
    assert first.recorder.end_of("side").status == "ok"
    recorder = ListRecorder()
    answers = AnswerBook({("ok", 1): GateAnswer("approve")})
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5, gates=answers)
    resumed_report = run_workflow(plan, {}, ports, prior=first.report.state)
    assert resumed_report.status == "done"
    assert runner.ran() == ["after"]
    assert recorder.end_of("side").skip_cause == "prior_success"


def test_reworks_through_namespaced_ids_when_the_gated_group_comes_from_an_include() -> None:
    included = parse_workflow({"version": 1, "name": "rework", "revision": 1, "nodes": [REWORK]})
    document = {
        "version": 1,
        "name": "main",
        "revision": 1,
        "nodes": [{"id": "i", "type": "include", "include": "rework"}],
    }
    plan = plan_workflow(parse_workflow(document), includes={"rework": included}.get)
    runner, state = ScriptedRunner(), RunState()
    ids: list[tuple[str | None, list[str]]] = []
    for answers in (
        {},
        {("i__g__ok", 1): GateAnswer("reject")},
        {("i__g__ok", 2): GateAnswer("approve")},
    ):
        ports = EnginePorts(
            runner,
            ListRecorder(),
            FakeClock(),
            KeysOutputs(),
            lambda: 0.5,
            gates=AnswerBook(answers),
        )
        report = run_workflow(plan, {}, ports, prior=state)
        state = report.state
        ids.append((report.reason, sorted(state.groups)))

    assert ids[:2] == [("i__g__ok", ["i__g"]), ("i__g__ok", ["i__g"])]
    assert report.status == "done"
    assert runner.ran().count("i__g__work") == 2
