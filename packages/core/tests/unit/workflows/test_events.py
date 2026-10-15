"""A workflow run's events: built from the engine's recorder calls, metadata only (ADR 0019)."""

import hashlib
from datetime import timedelta

import pytest

from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.events.payload_keys import kept_payload
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.workflow_fakes import (
    START,
    FakeClock,
    KeysOutputs,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord
from agent_hub.core.workflows.gates import GateForm, GateKind
from agent_hub.core.workflows.ports import GateRequest, RunEnd, StepEnd, StepStart

# A real digest: redaction must keep it whole.
HASH = "sha256:" + hashlib.sha256(b"issue-to-pr snapshot").hexdigest()


def a_recorder(end_index: int = 0) -> WorkflowEvents:
    return WorkflowEvents(
        project="demo",
        run_id="r1",
        workflow="issue-to-pr",
        revision=3,
        content_hash=HASH,
        end_index=end_index,
        repo="demo-api",
    )


def test_builds_step_start_when_a_step_starts() -> None:
    recorder = a_recorder()

    recorder.step_started(StepStart("plan", 2, START))

    [event] = recorder.events
    assert event.type == EventType.STEP_START
    assert (event.source, event.source_id) == (EventSource.EXECUTOR, "r1:plan:2:step.start")
    assert (event.project, event.session, event.repo) == ("demo", "run:r1", "demo-api")
    assert (event.workflow, event.step, event.timestamp) == ("issue-to-pr", "plan", START)
    assert event.payload == {"run": "r1", "attempt": 2, "revision": 3, "content_hash": HASH}


def test_keeps_outputs_and_details_out_when_a_step_ends() -> None:
    recorder = a_recorder()

    recorder.step_ended(
        StepEnd("plan", 1, "failed", START, "output_contract", output={"x": 1}, detail="$: breaks")
    )

    [event] = recorder.events
    assert event.source_id == "r1:plan:1:step.end"
    assert event.payload == {
        "run": "r1",
        "attempt": 1,
        "status": "failed",
        "failure_kind": "output_contract",
    }


def test_names_the_cause_and_origin_when_a_step_is_skipped() -> None:
    recorder = a_recorder()

    recorder.step_ended(
        StepEnd("pr", 1, "skipped", START, skip_cause="upstream_failed", origin="verify")
    )

    assert recorder.events[0].payload == {
        "run": "r1",
        "attempt": 1,
        "status": "skipped",
        "skip_cause": "upstream_failed",
        "reason": "verify",
    }


def test_emits_nothing_when_a_retry_is_scheduled() -> None:
    recorder = a_recorder()

    recorder.retry_scheduled("plan", RetryRecord(1, "transient", timedelta(seconds=2)))

    assert recorder.events == []


def test_keys_run_end_by_its_index_when_the_run_ends() -> None:
    recorder = a_recorder(end_index=2)

    recorder.run_ended(RunEnd("failed", START, outcome="blocked", reason="verify"))

    [event] = recorder.events
    assert event.type == EventType.RUN_END
    assert (event.source_id, event.step) == ("r1:run:2:end", None)
    assert event.payload == {
        "run": "r1",
        "status": "failed",
        "outcome": "blocked",
        "reason": "verify",
        "revision": 3,
        "content_hash": HASH,
    }


def test_stores_a_boolean_outcome_when_outcome_field_is_boolean() -> None:
    recorder = a_recorder()

    recorder.run_ended(RunEnd("done", START, outcome=False))

    assert recorder.events[0].payload["outcome"] is False
    assert "reason" not in recorder.events[0].payload


def test_emits_unique_keys_and_only_step_end_for_skips_when_a_run_retries_and_skips() -> None:
    plan = a_plan(
        {"id": "a", "type": "shell", "command": ["true"]},
        {"id": "b", "type": "shell", "command": ["true"], "depends_on": ["a"]},
    )
    recorder = a_recorder()
    runner = ScriptedRunner({"a": [NodeFailedError("transient"), NodeFailedError("transient")]})
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5)

    run_workflow(plan, {}, ports)

    assert [event.source_id for event in recorder.events] == [
        "r1:a:1:step.start",
        "r1:a:1:step.end",
        "r1:a:2:step.start",
        "r1:a:2:step.end",
        "r1:b:1:step.end",
        "r1:run:0:end",
    ]


def test_stores_every_payload_whole_when_ingested() -> None:
    recorder = a_recorder()
    recorder.step_started(StepStart("a", 1, START))
    recorder.step_ended(StepEnd("a", 1, "failed", START, "timeout"))
    recorder.step_ended(StepEnd("b", 1, "skipped", START, skip_cause="upstream_failed", origin="a"))
    recorder.run_ended(RunEnd("failed", START, outcome="failed", reason="a"))
    store = InMemoryEventStore()

    IngestEvents(store).execute(recorder.events)

    assert [stored.payload for stored in store.read_all()] == [
        event.payload for event in recorder.events
    ]
    assert all(kept_payload(e.type, e.payload) == e.payload for e in recorder.events)


def test_tags_every_event_with_issue_when_run_has_one() -> None:
    recorder = WorkflowEvents(
        project="demo", run_id="r1", workflow="fix", revision=1, content_hash=HASH, issue="DEM-7"
    )

    recorder.step_started(StepStart("plan", 1, START))
    recorder.step_ended(StepEnd("plan", 1, "ok", START))
    recorder.run_ended(RunEnd("done", START))

    assert [event.payload["issue"] for event in recorder.events] == ["DEM-7"] * 3
    assert all(kept_payload(e.type, e.payload) == e.payload for e in recorder.events)


def test_leaves_issue_out_when_input_is_not_tracker_key() -> None:
    recorder = WorkflowEvents(
        project="demo", run_id="r1", workflow="fix", revision=1, content_hash=HASH, issue="dem 7"
    )

    recorder.run_ended(RunEnd("done", START))

    assert "issue" not in recorder.events[0].payload


@pytest.mark.parametrize(
    ("kind", "form", "event_kind"),
    [
        ("approval", "decision", "human_gate"),
        ("wait", "text", "human_gate"),
        ("wait", "choice", "human_gate"),
        ("wait", "timer", "wait"),
    ],
)
def test_builds_gate_request_without_its_text_when_a_gate_opens(
    kind: GateKind, form: GateForm, event_kind: str
) -> None:
    recorder = a_recorder()

    recorder.gate_requested(GateRequest("ok", 2, kind, form, START, ("approve",), "Ship?"))

    [event] = recorder.events
    assert (event.type, event.source, event.step) == (
        EventType.GATE_REQUEST,
        EventSource.EXECUTOR,
        "ok",
    )
    assert (event.source_id, event.session) == ("r1:ok:2:gate.request", "run:r1")
    assert event.payload == {
        "run": "r1",
        "attempt": 2,
        "gate_id": "r1:ok:2",
        "kind": event_kind,
        "name": "ok",
    }


def test_lists_an_open_approval_when_an_approval_request_is_folded() -> None:
    recorder = a_recorder()
    recorder.gate_requested(GateRequest("ok", 1, "approval", "decision", START, ("approve",)))
    store = InMemoryEventStore()
    IngestEvents(store).execute(recorder.events)

    approvals = fold_approvals(store.query(EventQuery()).items)

    approval = approvals["r1:ok:1"]
    assert (approval.kind, approval.status, approval.session_id) == ("human_gate", "open", "run:r1")
