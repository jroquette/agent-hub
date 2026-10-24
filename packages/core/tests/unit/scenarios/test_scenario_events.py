"""A scenario run's events, metadata only (AC-350.26, ADR 0019)."""

import agent_hub.core.events.payload_keys as payload_keys
import agent_hub.core.scenarios.scenario_events as scenario_events
from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.payload_keys import kept_payload
from agent_hub.core.scenarios.access_policy import PolicyDecision
from agent_hub.core.scenarios.policy_gates import NodeDecision
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.testing.workflow_fakes import START
from agent_hub.core.workflows.ports import ContextCapture, ExpectPoll
from agent_hub.core.workflows.run_control import DebugPause

SECRET_OUTPUT = {"status": "ON_HOLD", "order_id": "o-secret-7"}


def test_keeps_only_payload_keys_when_scenario_events_built_for_polls() -> None:
    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")

    events.expect_polled(
        ExpectPoll("wait", 1, 1, held=False, at=START, output={"status": "PENDING"})
    )
    events.expect_polled(ExpectPoll("wait", 1, 2, held=True, at=START, output=SECRET_OUTPUT))
    events.context_captured(ContextCapture("wait", 1, "order_id", START, "o-secret-7"))

    polls, held, capture = events.events
    assert [event.type for event in events.events] == [
        EventType.EXPECT_POLL,
        EventType.EXPECT_POLL,
        EventType.CONTEXT_CAPTURE,
    ]
    assert polls.payload == {"run": "1a2b3c4d", "attempt": 1, "poll": 1, "held": False}
    assert held.payload == {"run": "1a2b3c4d", "attempt": 1, "poll": 2, "held": True}
    assert capture.payload == {"run": "1a2b3c4d", "attempt": 1, "name": "order_id"}
    for event in events.events:
        assert kept_payload(event.type, event.payload) == event.payload
        assert (event.source, event.session, event.step) == (
            EventSource.EXECUTOR,
            "run:1a2b3c4d",
            "wait",
        )
        assert event.workflow == "scenario:walk"
        assert "secret" not in event.model_dump_json()
    assert len({event.source_id for event in events.events}) == 3


def test_keeps_only_payload_keys_when_scenario_events_built_for_actions() -> None:
    run = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")
    standalone = ScenarioEvents(project="demo", run_id=None, workflow=None, session="action:5e6f")
    facts = scenario_events.ActionFacts(
        step="send",
        attempt=2,
        action="aws/send",
        content_hash="sha256:" + "0" * 64,
        environment="staging",
        services=("demo-api/orders",),
        effect="write",
        origin="human",
        decision="ask",
        approver="jane",
    )

    for events in (run, standalone):
        events.policy_decided(facts, reason_kind="table", at=START)
        events.action_started(facts, at=START)
        events.action_ended(facts, status="failed", failure_kind="output_contract", at=START)

    decided, started, ended = run.events
    assert [event.type for event in run.events] == [
        EventType.POLICY_DECISION,
        EventType.ACTION_START,
        EventType.ACTION_END,
    ]
    shared = {
        "action": "aws/send",
        "environment": "staging",
        "effect": "write",
        "origin": "human",
        "decision": "ask",
    }
    assert decided.payload == {"run": "1a2b3c4d", "attempt": 2, **shared, "reason_kind": "table"}
    action = {**shared, "content_hash": "sha256:" + "0" * 64, "service": ["demo-api/orders"]}
    assert started.payload == {"run": "1a2b3c4d", "attempt": 2, **action, "approver": "jane"}
    assert ended.payload == {
        **started.payload,
        "status": "failed",
        "failure_kind": "output_contract",
    }
    for event in (*run.events, *standalone.events):
        assert kept_payload(event.type, event.payload) == event.payload
        assert event.step == "send"
    assert {event.session for event in standalone.events} == {"action:5e6f"}
    assert all("run" not in event.payload for event in standalone.events)
    assert all(event.workflow is None for event in standalone.events)
    assert len({event.source_id for event in (*run.events, *standalone.events)}) == 6


def test_lists_gate_reason_when_payload_keys_read() -> None:
    keys = payload_keys.PAYLOAD_KEYS
    common = payload_keys.COMMON_PAYLOAD_KEYS
    assert "reason" in keys[EventType.GATE_REQUEST]
    for kind in ("finding", "workaround.start", "workaround.end"):
        assert EventType(kind) in keys
    # ``step`` is a key of every type.
    assert keys[EventType.FINDING] - common == {"finding_id"}
    workaround = {"workaround_id", "option", "steps", "status"}
    assert keys[EventType.WORKAROUND_END] - common == workaround


def test_keeps_one_event_per_poll_when_scenario_events_built_for_expect_calls() -> None:
    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")
    facts = scenario_events.ActionFacts(
        step="wait",
        attempt=1,
        action="demo/get-order",
        content_hash="sha256:" + "0" * 64,
        environment="staging",
        services=(),
        effect="read",
        origin="author",
        decision="allow",
    )

    for poll in (1, 2):
        events.policy_decided(facts, reason_kind="table", at=START, poll=poll)
        events.action_started(facts, at=START, poll=poll)
        events.action_ended(facts, status="ok", failure_kind=None, at=START, poll=poll)

    # The store keeps one event per source id: each poll's call is its own.
    assert len({event.source_id for event in events.events}) == 6
    for event in events.events:
        assert kept_payload(event.type, event.payload) == event.payload
        assert "poll" not in event.payload


# AGH-359 (owner decision B): a process workflow node's decision, metadata only.


def test_keeps_only_payload_keys_when_scenario_events_built_for_node_decisions() -> None:
    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="deploy")
    decided = NodeDecision(
        step="g__build",
        node_type="shell",
        effect="write",
        environment="staging",
        decision=PolicyDecision(decision="ask", reason_kind="table"),
    )

    events.node_decided(decided, attempt=0, at=START)
    events.node_decided(decided, attempt=2, at=START, item="until1")

    start, later = events.events
    assert start.type == EventType.POLICY_DECISION
    assert start.payload == {
        "run": "1a2b3c4d",
        "attempt": 0,
        "node": "g__build",
        "environment": "staging",
        "effect": "write",
        "origin": "author",
        "decision": "ask",
        "reason_kind": "table",
    }
    assert kept_payload(start.type, start.payload) == start.payload
    assert (start.step, start.workflow) == ("g__build", "deploy")
    assert start.source_id == "1a2b3c4d:g__build:0:policy.decision:"
    assert later.source_id == "1a2b3c4d:g__build:2:policy.decision:until1"


# AGH-360: an investigation's findings and workarounds, and every new type together.


def test_keeps_only_payload_keys_when_scenario_events_built() -> None:
    from agent_hub.core.workflows.events import WorkflowEvents
    from agent_hub.core.workflows.ports import GateRequest

    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")
    facts = scenario_events.ActionFacts(
        step="order-held__investigation.w1",
        attempt=1,
        action="demo/release-hold",
        content_hash="sha256:" + "0" * 64,
        environment="local",
        services=("demo-api/api",),
        effect="write",
        origin="agent",
        decision="ask",
        approver="dev",
    )
    workaround = scenario_events.WorkaroundFacts(
        step="order-held", attempt=1, workaround_id="w1", option="o1", steps=1
    )
    events.policy_decided(facts, reason_kind="agent_origin", at=START)
    events.action_started(facts, at=START, item="read1")
    events.action_ended(facts, status="ok", failure_kind=None, at=START, item="read1")
    events.expect_polled(ExpectPoll("wait", 1, 1, held=True, at=START, output=SECRET_OUTPUT))
    events.context_captured(ContextCapture("wait", 1, "order_id", START, "o-secret-7"))
    events.finding_recorded(step="order-held", attempt=1, finding_id="f1", at=START)
    events.workaround_started(workaround, at=START)
    events.workaround_ended(workaround, status="ok", at=START)
    gates = WorkflowEvents(
        project="demo", run_id="1a2b3c4d", workflow="scenario:walk", revision=1, content_hash="h"
    )
    gates.gate_requested(
        GateRequest(
            "order-held__investigation",
            1,
            "approval",
            "choice",
            START,
            ("pick", "retry", "stop"),
            "the secret message",
            reason="investigation",
        )
    )

    built = [*events.events, *gates.events]
    assert {event.type for event in built} == {
        EventType.POLICY_DECISION,
        EventType.ACTION_START,
        EventType.ACTION_END,
        EventType.EXPECT_POLL,
        EventType.CONTEXT_CAPTURE,
        EventType.FINDING,
        EventType.WORKAROUND_START,
        EventType.WORKAROUND_END,
        EventType.GATE_REQUEST,
    }
    for event in built:
        assert kept_payload(event.type, event.payload) == event.payload, event.type
        assert "secret" not in event.model_dump_json()
    by_type = {event.type: event for event in built}
    assert by_type[EventType.FINDING].payload == {
        "run": "1a2b3c4d",
        "attempt": 1,
        "finding_id": "f1",
        "step": "order-held",
    }
    started = by_type[EventType.WORKAROUND_START].payload
    assert started == {"run": "1a2b3c4d", "attempt": 1, "workaround_id": "w1", "option": "o1"} | {
        "steps": 1,
        "status": "started",
    }
    assert by_type[EventType.WORKAROUND_END].payload["status"] == "ok"
    requested = by_type[EventType.GATE_REQUEST].payload
    assert (requested["kind"], requested["reason"]) == ("human_gate", "investigation")
    assert len({event.source_id for event in built}) == len(built)


# A debugging run: a debug pause, the command that resumes it and a breakpoint set, metadata only.


def test_keeps_only_payload_keys_when_scenario_events_built_for_debugging() -> None:
    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")

    events.breakpoints_set(2, number=1, at=START)
    events.debug_paused(DebugPause("payment--2", "8.2", "breakpoint"), number=1, at=START)
    events.debug_commanded("step", approver="Ada", node="payment--2", number=1, at=START)
    events.breakpoints_set(0, number=2, at=START)

    breakpoints, paused, commanded, cleared = events.events
    assert [event.type for event in events.events] == [
        EventType.DEBUG_BREAKPOINTS,
        EventType.DEBUG_PAUSE,
        EventType.DEBUG_COMMAND,
        EventType.DEBUG_BREAKPOINTS,
    ]
    assert breakpoints.payload == {"run": "1a2b3c4d", "attempt": 1, "count": 2}
    assert breakpoints.step is None
    assert paused.payload == {"run": "1a2b3c4d", "attempt": 1} | {
        "node": "payment--2",
        "block": "8.2",
        "reason": "breakpoint",
    }
    assert commanded.payload == {"run": "1a2b3c4d", "attempt": 1} | {
        "command": "step",
        "approver": "Ada",
    }
    assert (paused.step, commanded.step) == ("payment--2", "payment--2")
    assert cleared.payload["count"] == 0
    keys, common = payload_keys.PAYLOAD_KEYS, payload_keys.COMMON_PAYLOAD_KEYS
    assert keys[EventType.DEBUG_PAUSE] - common == {"node", "block", "reason"}
    assert keys[EventType.DEBUG_COMMAND] - common == {"command", "approver"}
    assert keys[EventType.DEBUG_BREAKPOINTS] - common == {"count"}
    for event in events.events:
        assert kept_payload(event.type, event.payload) == event.payload, event.type
        assert (event.source, event.session) == (EventSource.EXECUTOR, "run:1a2b3c4d")
    assert len({event.source_id for event in events.events}) == 4
