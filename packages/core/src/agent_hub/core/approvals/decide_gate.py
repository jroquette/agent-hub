"""Decide a workflow gate (ADR 0032, AGH-230): one decision per open gate, then its event.

A paused run's gates live in its record (the ``GateBook``: the cli's ``records.jsonl``, read and
written under the run's lock), which also keeps the answer's text for the engine's resume.
``DecideGate`` refuses a gate that is not open or already has its decision and an answer the
gate cannot take, records the decision, then sends a ``control_plane`` ``gate.result`` in the
run's session (``run:<id>``) through ``IngestEvents``: ``fold_approvals`` pairs it with the
request by ``gate_id``. The event carries the result, the approver and where it was decided,
never the text (ADR 0019). A store that fails after the decision is recorded leaves the
decision standing; the error is returned for the caller to report.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.approvals.approval import ApprovalStatus
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.events import gate_event_kind
from agent_hub.core.workflows.gates import GateAnswer, GateForm, answer_problem

# An approval's decision as the Approvals read model shows it; any other answer is "approved".
_RESULTS: Final[Mapping[str, ApprovalStatus]] = {"approve": "approved", "reject": "rejected"}


class GateDecisionError(AgentHubError):
    """A decision refused: no open gate by that id, a second decision, an answer that does not
    fit the gate."""


@dataclass(frozen=True)
class RequestedGate:
    """A gate as its run recorded it: where it is and what answers it."""

    gate_id: str
    run: str
    workflow: str
    node: str
    attempt: int
    form: GateForm
    choices: tuple[str, ...]


@dataclass(frozen=True)
class GateDecision:
    """A person's answer to ``gate_id``, who gave it, where (``cli``, ``web``) and when."""

    gate_id: str
    answer: GateAnswer
    approver: str
    where: str
    at: datetime


@dataclass(frozen=True)
class GateDecided:
    """The ``gate.result`` sent, and the store's error when it could not be sent."""

    event: Event
    event_error: str | None = None


class GateBook(Protocol):
    """A run's record of its gates and their decisions."""

    def open_gate(self, gate_id: str) -> RequestedGate | None:
        """The gate when it was requested and its node has not ended since; else ``None``."""
        ...

    def decided(self, gate_id: str) -> bool:
        """Whether a decision for ``gate_id`` is already recorded."""
        ...

    def record(self, gate: RequestedGate, decision: GateDecision) -> None:
        """Keep ``decision`` (its text included) where the run's resume reads it."""
        ...


class DecideGate:
    """Record one decision for an open gate and send its ``gate.result``."""

    def __init__(self, book: GateBook, ingest: IngestEvents | None, *, project: str) -> None:
        self._book, self._ingest, self._project = book, ingest, project

    def execute(self, decision: GateDecision) -> GateDecided:
        gate = self._book.open_gate(decision.gate_id)
        if gate is None:
            raise GateDecisionError(f"no open gate {decision.gate_id}")
        if self._book.decided(gate.gate_id):
            raise GateDecisionError(f"the gate {gate.gate_id} is already decided")
        if (problem := answer_problem(gate.form, gate.choices, decision.answer)) is not None:
            raise GateDecisionError(problem)
        self._book.record(gate, decision)
        event = self._event(gate, decision)
        if self._ingest is None:
            return GateDecided(event)
        try:
            self._ingest.execute([event])
        except (AgentHubError, OSError) as error:
            return GateDecided(event, " ".join(str(error).split()) or type(error).__name__)
        return GateDecided(event)

    def _event(self, gate: RequestedGate, decision: GateDecision) -> Event:
        choice = decision.answer.choice
        result = _RESULTS.get(choice or "", "approved")
        if gate.form == "decision" and choice not in _RESULTS:
            result = "changes_requested"
        payload: dict[str, JsonValue] = {
            "run": gate.run,
            "attempt": gate.attempt,
            "gate_id": gate.gate_id,
            "kind": gate_event_kind(gate.form),
            "name": gate.node,
            "result": result,
            "approver": decision.approver,
            "where": decision.where,
        }
        return Event(
            project=self._project,
            session=f"run:{gate.run}",
            type=EventType.GATE_RESULT,
            timestamp=decision.at,
            source=EventSource.CONTROL_PLANE,
            source_id=f"{gate.gate_id}:{EventType.GATE_RESULT}",
            payload=payload,
            workflow=gate.workflow,
            step=gate.node,
        )
