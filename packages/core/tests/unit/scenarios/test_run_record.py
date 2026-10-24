"""A scenario run folded from its record (P-16; docs/design/scenarios.md § Investigation)."""

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_hub.core.scenarios.run_record import (
    RunRecordError,
    debug_pause_line,
    debug_resume,
    fold_records,
    fold_values,
    record_lines,
)
from agent_hub.core.testing.workflow_fakes import (
    AnswerBook,
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ListTrace,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.run_control import DebugPause, PauseReason
from agent_hub.core.workflows.run_state import RunState

GATE = "order-held__investigation"


def a_record() -> list[dict[str, Any]]:
    """A scenario run paused at its first investigation, with one proposal."""
    return [
        {"event": "start", "run": "walk-1", "scenario": "order-walk", "environment": "local"}
        | {"mode": "interactive", "kind": "scenario", "ts": "2026-10-21T10:00:00+00:00"},
        {"event": "inputs", "inputs": {"ref": "T-1"}},
        {"event": "step_start", "node": "order-held", "attempt": 1},
        {"event": "step_end", "node": "order-held", "attempt": 1, "status": "failed"}
        | {"failure_kind": "timeout"},
        {"event": "investigation", "step": "order-held", "gate": GATE, "number": 1}
        | {"step_attempt": 1, "failure_kind": "timeout"},
        {"event": "gate", "node": GATE, "attempt": 1, "form": "choice"},
        a_proposal(1, "Order stays on hold", "o1"),
    ]


def a_proposal(proposal: int, title: str, *options: str) -> dict[str, Any]:
    return {
        "event": "proposal",
        "gate": GATE,
        "number": 1,
        "proposal": proposal,
        "findings": [{"finding_id": f"f{proposal}", "title": title, "text": "x", "evidence": ""}],
        "options": [
            {
                "option_id": option,
                "summary": "Release the hold",
                "steps": [{"action": "demo/release-hold", "with": {}}],
                "plan": [{"index": 1, "decision": "allow"}],
            }
            for option in options
        ],
    }


def test_folds_timeline_when_records_given() -> None:
    view = fold_records(a_record())

    assert (view.run, view.scenario, view.environment, view.mode, view.status) == (
        "walk-1",
        "order-walk",
        "local",
        "interactive",
        None,
    )
    assert [(item.event, item.node, item.attempt) for item in view.timeline] == [
        ("start", None, None),
        ("step_start", "order-held", 1),
        ("step_end", "order-held", 1),
        ("investigation", "order-held", 1),
        ("gate", GATE, 1),
        ("proposal", GATE, 1),
    ]
    assert view.timeline[0].at == "2026-10-21T10:00:00+00:00"
    (investigation,) = view.investigations
    assert (investigation.step, investigation.gate, investigation.failure_kind) == (
        "order-held",
        GATE,
        "timeout",
    )
    assert view.open_investigation == investigation
    assert [finding.finding_id for finding in view.findings] == ["f1"]


def test_closes_investigation_with_answer_when_decided_and_ended() -> None:
    records = [
        *a_record(),
        {"event": "decision", "node": GATE, "attempt": 1, "choice": "stop", "text": None}
        | {"approver": "dev"},
        {"event": "step_end", "node": GATE, "attempt": 1, "status": "ok"},
        {"event": "workaround_start", "workaround_id": "w1", "number": 1, "option": "o1"}
        | {"steps": 1, "approver": "dev"},
        {"event": "workaround_end", "workaround_id": "w1", "number": 1, "status": "ok"},
        {"event": "end", "status": "cancelled"},
    ]

    view = fold_records(records)

    (investigation,) = view.investigations
    assert (investigation.choice, investigation.approver, investigation.closed) == (
        "stop",
        "dev",
        True,
    )
    assert view.status == "cancelled"
    assert view.open_investigation is None
    assert [(item.workaround_id, item.option, item.status) for item in view.workarounds] == [
        ("w1", "o1", "ok")
    ]
    # Stop keeps the findings.
    assert [finding.title for finding in view.findings] == ["Order stays on hold"]


def test_keeps_latest_proposal_when_proposed_twice() -> None:
    records = [*a_record(), a_proposal(2, "The hold is a config flag", "o1", "o2")]

    view = fold_records(records)

    proposal = view.investigations[0].proposal
    assert proposal is not None
    assert proposal.proposal == 2
    assert [option.option_id for option in proposal.options] == ["o1", "o2"]
    assert proposal.option("o2") is not None
    assert proposal.option("o3") is None
    assert [finding.title for finding in view.findings] == ["The hold is a config flag"]


def test_drops_torn_line_when_record_cut() -> None:
    lines = [json.dumps(record) for record in a_record()]
    data = ("\n".join(lines) + "\n").encode() + b'{"event": "proposal", "gate": "order-he'

    parsed = record_lines(data)

    assert parsed == a_record()
    assert fold_records(parsed).investigations[0].proposal is not None


def test_refuses_line_when_record_holds_non_object() -> None:
    with pytest.raises(RunRecordError):
        record_lines(b'{"event": "start"}\n[1, 2]\n')


def test_keeps_polls_captures_and_decisions_when_records_folded() -> None:
    record = [
        *a_record(),
        {"event": "expect.poll", "node": "order-held", "attempt": 2, "poll": 1, "held": True}
        | {"output": {"status": "ON_HOLD"}, "ts": "2026-10-21T10:01:00+00:00"},
        {"event": "context.capture", "node": "order-held", "attempt": 2, "name": "order_id"}
        | {"value": "o-1"},
        {"event": "decision", "node": GATE, "attempt": 1, "choice": "retry", "text": None}
        | {"approver": "demo", "where": "web", "ts": "2026-10-21T10:02:00+00:00"},
    ]

    view = fold_records(record)

    (poll,) = view.polls
    assert (poll.node, poll.attempt, poll.poll, poll.held) == ("order-held", 2, 1, True)
    assert "output" not in repr(poll)
    (capture,) = view.captures
    assert (capture.name, capture.value) == ("order_id", "o-1")
    (decision,) = view.decisions
    assert (decision.node, decision.choice, decision.approver, decision.where) == (
        GATE,
        "retry",
        "demo",
        "web",
    )


def test_keeps_action_facts_when_action_lines_folded() -> None:
    """Each action call's policy facts (AGH-350 E-15): never its inputs or output."""
    record = [
        *a_record(),
        {"event": "action", "node": "order-held", "attempt": 1, "poll": 2}
        | {"action": "demo/get-order", "environment": "local", "effect": "read"}
        | {"origin": "author", "decision": "allow", "content_hash": "sha256:" + "a" * 64}
        | {"service": ["demo-api/api"], "reason_kind": "table", "inputs": {"ref": "T-1"}}
        | {"status": "ok", "failure_kind": None, "ts": "2026-10-21T10:00:30+00:00"},
        {"event": "action", "node": "release", "attempt": 1, "poll": 0, "action": "demo/release"}
        | {"effect": "write", "origin": "agent", "decision": "ask", "approver": "dev"}
        | {"status": "failed", "failure_kind": "exec_failed"},
    ]

    view = fold_records(record)

    first, second = view.actions
    assert (first.node, first.attempt, first.poll, first.action, first.effect) == (
        "order-held",
        1,
        2,
        "demo/get-order",
        "read",
    )
    assert (first.origin, first.decision, first.reason_kind, first.status) == (
        "author",
        "allow",
        "table",
        "ok",
    )
    assert first.content_hash == "sha256:" + "a" * 64
    assert first.at == "2026-10-21T10:00:30+00:00"
    assert "T-1" not in repr(first)
    assert (second.decision, second.approver, second.failure_kind) == ("ask", "dev", "exec_failed")
    assert all(item.event != "action" for item in view.timeline)


def test_names_action_and_effect_when_agent_action_folded() -> None:
    """An investigation read's line in the timeline names its action and effect (E-15)."""
    record = [
        *a_record(),
        {"event": "agent_action", "gate": GATE, "number": 1, "item": "", "action": "demo/get"}
        | {"effect": "read", "origin": "agent", "decision": "allow", "status": "ok"}
        | {"output": {"secret": "x"}},
    ]

    view = fold_records(record)

    read = view.timeline[-1]
    assert (read.event, read.node, read.action, read.effect, read.status) == (
        "agent_action",
        GATE,
        "demo/get",
        "read",
        "ok",
    )
    assert all(item.action is None for item in view.timeline[:-1])


# AC-507.16 (core): a debug pause, its breakpoints and commands, and the values to inspect.


@dataclass
class Breakpoints:
    """A ``RunControl`` that pauses before each node of ``at``, for the block it names."""

    at: Mapping[str, str] = field(default_factory=dict)

    def debugging(self) -> bool:
        return bool(self.at)

    def pause_before(self, node: str) -> PauseReason | None:
        block = self.at.get(node)
        return None if block is None else PauseReason(block, "breakpoint")


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "shell", "command": ["true"], "depends_on": list(depends_on)}
    return node | keys


def engine_ports(
    runner: ScriptedRunner, control: Breakpoints | None, *, answered: bool = True
) -> EnginePorts:
    """The fakes' ports; the gate ``ok`` is approved once ``answered``."""
    answers = AnswerBook({("ok", 1): GateAnswer("approve", approver="Ada")} if answered else {})
    return EnginePorts(
        runner,
        ListRecorder(),
        FakeClock(),
        KeysOutputs(),
        lambda: 0.5,
        gates=answers,
        trace=ListTrace(),
        control=control,
    )


def a_paused_run() -> tuple[WorkflowPlan, RunState]:
    """A run's second pass paused before ``side`` by a breakpoint: its first pass failed
    ``bad`` (so ``skip`` skipped) and paused on the gate ``ok``; the second, with ``ok``
    answered, opened the gate ``late`` just before the pause and holds it open."""
    gate = {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["a"]}
    late = {"id": "late", "type": "approval", "message": "Later?", "depends_on": ["ok"]}
    plan = a_plan(
        shell("a"),
        shell("bad"),
        shell("skip", "bad"),
        gate,
        late,
        shell("side", "ok"),
        shell("after", "side", "skip", trigger_rule="all_done"),
    )
    failure = NodeFailedError("exec_failed", "exit 1")
    runner = ScriptedRunner({"a": ['{"order_id": "o-1"}'], "bad": [failure]})
    first = run_workflow(plan, {}, engine_ports(runner, None, answered=False))
    second = run_workflow(
        plan, {}, engine_ports(runner, Breakpoints({"side": "1.4"})), prior=first.state
    )
    assert second.state.pause == DebugPause("side", "1.4", "breakpoint")
    return plan, second.state


def round_trip(line: Mapping[str, Any]) -> dict[str, Any]:
    """``line`` as the record holds it: one JSON object."""
    (parsed,) = record_lines((json.dumps(line) + "\n").encode())
    return parsed


def test_rebuilds_the_paused_pass_when_a_debug_pause_line_is_read_back() -> None:
    plan, state = a_paused_run()
    assert state.paused_pass is not None
    assert state.paused_pass.ends and state.paused_pass.before
    assert state.gates

    records = [*a_record(), round_trip(debug_pause_line(state, number=1))]
    resumed = debug_resume(records)

    assert resumed is not None
    # The rest of the state comes from the run's other lines (steps, gates, held groups).
    base = dataclasses.replace(state, gates={}, pause=None, paused_pass=None)
    rebuilt = resumed.applied_to(base)
    assert rebuilt == state
    runner = ScriptedRunner()
    again = run_workflow(plan, {}, engine_ports(runner, None), prior=rebuilt)
    kept = run_workflow(plan, {}, engine_ports(ScriptedRunner(), None), prior=state)
    assert (again.status, again.reason, again.state) == (kept.status, kept.reason, kept.state)


def test_folds_the_pause_breakpoints_and_commands_when_debug_lines_given() -> None:
    _, state = a_paused_run()
    records = [
        *a_record(),
        {"event": "debug.breakpoints", "addresses": ["1.2", "1.4"], "ts": "2026-10-21T10:03:00Z"},
        {"event": "debug.breakpoints", "addresses": ["1.4"]},
        round_trip(debug_pause_line(state, number=1) | {"ts": "2026-10-21T10:04:00Z"}),
    ]

    paused = fold_records(records)
    stepped = fold_records(
        [
            *records,
            {"event": "debug.command", "command": "step", "approver": "Ada", "node": "side"}
            | {"number": 1, "ts": "2026-10-21T10:05:00Z"},
        ]
    )
    resumed = fold_records([*stepped_lines(records), {"event": "resume"}])

    pause = paused.debug.pause
    assert pause is not None
    assert (pause.node, pause.block, pause.reason, pause.number, pause.at) == (
        "side",
        "1.4",
        "breakpoint",
        1,
        "2026-10-21T10:04:00Z",
    )
    assert paused.debug.breakpoints == ("1.4",)
    assert (paused.debug.commands, paused.debug.stepping) == ((), False)
    (command,) = stepped.debug.commands
    assert (command.command, command.approver, command.number, command.at) == (
        "step",
        "Ada",
        1,
        "2026-10-21T10:05:00Z",
    )
    assert stepped.debug.stepping
    assert stepped.debug.pause == pause
    assert resumed.debug.pause is None
    assert debug_resume([*stepped_lines(records), {"event": "resume"}]) is None
    # The view is metadata: the paused pass and its outputs stay in the record.
    assert "o-1" not in repr(paused)


def stepped_lines(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    command = {"event": "debug.command", "command": "step", "approver": "Ada", "node": "side"}
    return [*records, command | {"number": 1}]


def test_names_the_debug_pause_not_the_gate_when_a_gate_is_left_open_beside_it() -> None:
    # The investigation's gate stays open while a later pass pauses before a block: the run is
    # paused by the debugger, and the gate is answered once the pass reaches it again.
    _, state = a_paused_run()

    view = fold_records([*a_record(), round_trip(debug_pause_line(state, number=1))])

    assert view.debug.pause is not None
    assert view.open_investigation is None
    assert fold_records(a_record()).open_investigation is not None


def test_refuses_the_debug_pause_line_when_its_pass_cannot_be_read() -> None:
    _, state = a_paused_run()
    line = round_trip(debug_pause_line(state, number=1))
    line["pass"]["ends"]["a"]["state"] = "running"

    with pytest.raises(RunRecordError):
        debug_resume([*a_record(), line])


def test_gives_inspect_values_when_a_paused_run_is_folded() -> None:
    records = [
        *a_record(),
        {"event": "action_start", "node": "fetch", "attempt": 1, "poll": 0},
        {"event": "action", "node": "fetch", "attempt": 1, "poll": 0, "status": "ok"}
        | {"inputs": {"order": "o-1"}},
        {"event": "step_end", "node": "fetch", "attempt": 1, "status": "ok"}
        | {"output": {"order_status": "ON_HOLD"}},
        {"event": "action_start", "node": "wait", "attempt": 1, "poll": 1},
        {"event": "action", "node": "wait", "attempt": 1, "poll": 1, "inputs": {"order": "o-1"}},
        {"event": "expect.poll", "node": "wait", "attempt": 1, "poll": 1, "held": False}
        | {"output": {"review_status": "PENDING"}},
        {"event": "action_start", "node": "wait", "attempt": 1, "poll": 2},
        {"event": "action", "node": "wait", "attempt": 1, "poll": 2, "inputs": {"order": "o-2"}},
        {"event": "expect.poll", "node": "wait", "attempt": 1, "poll": 2, "held": True}
        | {"output": {"review_status": "REVIEWED"}},
        {"event": "step_end", "node": "wait", "attempt": 1, "status": "ok"}
        | {"output": {"review_status": "REVIEWED"}},
        # A reuse on resume keeps the end it reused.
        {"event": "step_end", "node": "fetch", "attempt": 1, "status": "skipped"}
        | {"skip_cause": "prior_success", "output": None},
        # Not finished: no values yet.
        {"event": "action_start", "node": "send", "attempt": 1, "poll": 0},
    ]

    values = fold_values(records)

    assert values.inputs == {"ref": "T-1"}
    by_node = {item.node: item for item in values.nodes}
    assert list(by_node) == ["order-held", "fetch", "wait"]
    fetch, wait = by_node["fetch"], by_node["wait"]
    assert (fetch.status, fetch.inputs, fetch.output) == (
        "ok",
        {"order": "o-1"},
        {"order_status": "ON_HOLD"},
    )
    assert (fetch.polls, fetch.last_poll) == (0, None)
    assert (wait.status, wait.inputs, wait.output) == (
        "ok",
        {"order": "o-2"},
        {"review_status": "REVIEWED"},
    )
    assert (wait.polls, wait.last_poll) == (2, {"review_status": "REVIEWED"})
    failed = by_node["order-held"]
    assert (failed.status, failed.inputs, failed.output) == ("failed", None, None)
