"""Deciding a workflow gate: one decision per open gate, recorded, then a ``gate.result``."""

from dataclasses import dataclass, field

import pytest

from agent_hub.core.approvals.decide_gate import (
    DecideGate,
    GateDecision,
    GateDecisionError,
    RequestedGate,
)
from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.workflow_fakes import START
from agent_hub.core.workflows.events import WorkflowEvents
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.ports import GateRequest

GATE = RequestedGate("r1:ship:2", "r1", "deliver", "ship", 2, "decision", ("approve", "reject"))


@dataclass
class Book:
    """A ``GateBook`` over one run's gates, keeping what it recorded."""

    gates: dict[str, RequestedGate] = field(default_factory=lambda: {GATE.gate_id: GATE})
    recorded: list[GateDecision] = field(default_factory=list)

    def open_gate(self, gate_id: str) -> RequestedGate | None:
        return self.gates.get(gate_id)

    def decided(self, gate_id: str) -> bool:
        return any(decision.gate_id == gate_id for decision in self.recorded)

    def record(self, gate: RequestedGate, decision: GateDecision) -> None:
        self.recorded.append(decision)


def decision(choice: str | None = "approve", text: str | None = None) -> GateDecision:
    return GateDecision("r1:ship:2", GateAnswer(choice, text), "jdoe", "cli", START)


def test_records_the_decision_and_sends_a_paired_gate_result_when_a_gate_is_open() -> None:
    store, book = InMemoryEventStore(), Book()
    request = WorkflowEvents(
        project="demo", run_id="r1", workflow="deliver", revision=1, content_hash="sha256:0"
    )
    request.gate_requested(GateRequest("ship", 2, "approval", "decision", START, ("approve",)))
    IngestEvents(store).execute(request.events)

    decided = DecideGate(book, lambda: IngestEvents(store), project="demo").execute(
        decision(text="ship it")
    )

    assert book.recorded == [decision(text="ship it")]
    event = decided.event
    assert (event.type, event.source, event.session) == (
        EventType.GATE_RESULT,
        EventSource.CONTROL_PLANE,
        "run:r1",
    )
    assert (event.source_id, event.workflow, event.step) == (
        "r1:ship:2:gate.result",
        "deliver",
        "ship",
    )
    assert event.payload == {
        "run": "r1",
        "attempt": 2,
        "gate_id": "r1:ship:2",
        "kind": "human_gate",
        "name": "ship",
        "result": "approved",
        "approver": "jdoe",
        "where": "cli",
    }
    approval = fold_approvals(store.query(EventQuery()).items)["r1:ship:2"]
    assert (approval.status, approval.decided) == ("approved", True)


@pytest.mark.parametrize(
    ("gate", "answer", "result"),
    [
        (GATE, GateAnswer("reject"), "rejected"),
        (
            RequestedGate("r1:ship:2", "r1", "deliver", "ship", 2, "decision", ("rework",)),
            GateAnswer("rework"),
            "changes_requested",
        ),
        (
            RequestedGate("r1:ship:2", "r1", "deliver", "ship", 2, "text", ()),
            GateAnswer(text="blue"),
            "approved",
        ),
    ],
)
def test_maps_the_answer_to_an_approval_result_when_a_gate_is_decided(
    gate: RequestedGate, answer: GateAnswer, result: str
) -> None:
    book = Book({gate.gate_id: gate})

    decided = DecideGate(book, None, project="demo").execute(
        GateDecision(gate.gate_id, answer, "jdoe", "cli", START)
    )

    assert decided.event.payload["result"] == result
    assert "blue" not in str(decided.event.payload)


def test_refuses_a_second_decision_when_the_gate_was_decided() -> None:
    book = Book()
    use_case = DecideGate(book, None, project="demo")
    use_case.execute(decision())

    with pytest.raises(GateDecisionError, match="already decided"):
        use_case.execute(decision("reject"))
    assert len(book.recorded) == 1


@pytest.mark.parametrize(
    ("book", "answer", "message"),
    [
        (Book({}), decision(), "no open gate"),
        (Book(), decision("maybe"), 'no decision "maybe"'),
        (
            Book({GATE.gate_id: RequestedGate(GATE.gate_id, "r1", "w", "nap", 2, "timer", ())}),
            decision(None, "now"),
            "takes no answer",
        ),
    ],
)
def test_refuses_without_recording_when_the_gate_cannot_take_the_answer(
    book: Book, answer: GateDecision, message: str
) -> None:
    with pytest.raises(GateDecisionError, match=message):
        DecideGate(book, None, project="demo").execute(answer)
    assert book.recorded == []


def test_keeps_the_decision_and_names_the_error_when_the_event_store_fails() -> None:
    class Failing(InMemoryEventStore):
        def append(self, events: list[Event]) -> AppendResult:  # type: ignore[override]
            raise AgentHubError("database is locked")

    book = Book()

    decided = DecideGate(book, lambda: IngestEvents(Failing()), project="demo").execute(decision())

    assert book.recorded == [decision()]
    assert decided.event_error == "database is locked"


def test_opens_the_event_store_only_after_recording_when_a_decision_is_taken() -> None:
    book, opened = Book(), []

    def events() -> IngestEvents:
        opened.append(len(book.recorded))
        raise OSError("no database")

    use_case = DecideGate(book, events, project="demo")
    with pytest.raises(GateDecisionError):
        use_case.execute(decision("maybe"))
    decided = use_case.execute(decision())

    assert opened == [1]
    assert decided.event_error == "no database"


def test_takes_the_text_when_it_is_exactly_64_kib() -> None:
    book = Book()

    DecideGate(book, None, project="demo").execute(decision(text="x" * 65536))

    assert len(book.recorded) == 1


def test_refuses_the_text_without_recording_when_it_is_one_byte_over_64_kib() -> None:
    book = Book()

    with pytest.raises(GateDecisionError, match="65536 bytes"):
        DecideGate(book, None, project="demo").execute(decision(text="é" * 32768 + "x"))
    assert book.recorded == []
