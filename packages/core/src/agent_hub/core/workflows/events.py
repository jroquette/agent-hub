"""A workflow run's events (ADR 0032): a ``RunRecorder`` that builds them, metadata only.

Each attempt is a ``step.start`` and a ``step.end``; a skipped node emits only ``step.end``.
Source ``executor``, session ``run:<run>``, ``workflow`` the name and ``step`` the node id as
recorded; ``source_id`` is ``<run>:<step>:<attempt>:<type>``, and ``<run>:run:<n>:end`` for
the run's ``n``-th end (0 first, one more per resume). Outputs, details and rendered text stay
in the run's record, never here (ADR 0019): ``reason`` holds only a node id. A retry adds no
event: its failed attempt already ended with its kind. A gate adds a ``gate.request``
(``gate_id`` ``<run>:<step>:<attempt>``, ``name`` its node id): ``kind`` ``human_gate``, which the
Approvals read model lists, when a person answers it (an approval, an attention wait), ``wait``
for a timed wait; its message and choices stay in the run's record. The composition root passes
``events`` to ``IngestEvents``, which redacts and trims them like any other.
"""

from datetime import datetime

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.failures import RetryRecord
from agent_hub.core.workflows.gates import GateForm, gate_id
from agent_hub.core.workflows.ports import GateRequest, RunEnd, StepEnd, StepStart


def gate_event_kind(form: GateForm) -> str:
    """A gate's ``kind`` in events: ``human_gate`` when a person answers it, else ``wait``."""
    return "wait" if form == "timer" else ApprovalKind.HUMAN_GATE.value


class WorkflowEvents:
    """The events of one run, in the order the engine reported them."""

    def __init__(
        self,
        *,
        project: str,
        run_id: str,
        workflow: str,
        revision: int,
        content_hash: str,
        end_index: int = 0,
        repo: str | None = None,
    ) -> None:
        self.project, self.run_id, self.workflow, self.repo = project, run_id, workflow, repo
        self.pinned: dict[str, JsonValue] = {"revision": revision, "content_hash": content_hash}
        self.end_index = end_index
        self.events: list[Event] = []

    def step_started(self, start: StepStart) -> None:
        payload = {"run": self.run_id, "attempt": start.attempt, **self.pinned}
        source_id = f"{self.run_id}:{start.node}:{start.attempt}:{EventType.STEP_START}"
        self.events.append(
            self._event(
                EventType.STEP_START, source_id, at=start.at, payload=payload, step=start.node
            )
        )

    def step_ended(self, end: StepEnd) -> None:
        payload: dict[str, JsonValue] = {
            "run": self.run_id,
            "attempt": end.attempt,
            "status": end.status,
        }
        optional = {
            "failure_kind": end.failure_kind,
            "skip_cause": end.skip_cause,
            "reason": end.origin,
        }
        payload |= {key: value for key, value in optional.items() if value is not None}
        source_id = f"{self.run_id}:{end.node}:{end.attempt}:{EventType.STEP_END}"
        self.events.append(
            self._event(EventType.STEP_END, source_id, at=end.at, payload=payload, step=end.node)
        )

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        """No event: the run's record keeps the retry."""

    def gate_requested(self, request: GateRequest) -> None:
        payload: dict[str, JsonValue] = {
            "run": self.run_id,
            "attempt": request.attempt,
            "gate_id": gate_id(self.run_id, request.node, request.attempt),
            "kind": gate_event_kind(request.form),
            "name": request.node,
        }
        source_id = f"{self.run_id}:{request.node}:{request.attempt}:{EventType.GATE_REQUEST}"
        self.events.append(
            self._event(
                EventType.GATE_REQUEST, source_id, at=request.at, payload=payload, step=request.node
            )
        )

    def run_ended(self, end: RunEnd) -> None:
        payload: dict[str, JsonValue] = {"run": self.run_id, "status": end.status}
        payload["outcome"] = end.outcome
        if end.reason is not None:
            payload["reason"] = end.reason
        payload |= self.pinned
        source_id = f"{self.run_id}:run:{self.end_index}:end"
        self.events.append(self._event(EventType.RUN_END, source_id, at=end.at, payload=payload))

    def _event(
        self,
        kind: EventType,
        source_id: str,
        *,
        at: datetime,
        payload: dict[str, JsonValue],
        step: str | None = None,
    ) -> Event:
        return Event(
            project=self.project,
            session=f"run:{self.run_id}",
            type=kind,
            timestamp=at,
            source=EventSource.EXECUTOR,
            source_id=source_id,
            payload=payload,
            repo=self.repo,
            workflow=self.workflow,
            step=step,
        )
