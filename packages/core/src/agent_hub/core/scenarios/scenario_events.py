"""A scenario run's own events (docs/design/scenarios.md § Events and bounds): metadata only.

``ScenarioEvents`` is the engine's ``RunTrace`` for a scenario run: each ``expect`` poll is an
``expect.poll`` (``poll`` count, ``held``), each ``capture:`` value a ``context.capture``
(``name``). Source ``executor``, session ``run:<run>``, ``workflow`` the run's label
(``scenario:<name>``) and ``step`` the node id as recorded, as the run's other events
(``workflows.events``). Outputs and captured values stay in the run's record, never here
(ADR 0019). ``source_id`` is ``<run>:<step>:<attempt>:<type>:<poll or name>``.
"""

from datetime import datetime

from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.ports import ContextCapture, ExpectPoll


class ScenarioEvents:
    """The polls and captures of one scenario run, as events, in the order they came."""

    def __init__(
        self, *, project: str, run_id: str, workflow: str, repo: str | None = None
    ) -> None:
        self.project, self.run_id, self.workflow, self.repo = project, run_id, workflow, repo
        self.events: list[Event] = []

    def expect_polled(self, poll: ExpectPoll) -> None:
        payload: dict[str, JsonValue] = {"poll": poll.poll, "held": poll.held}
        self._add(
            EventType.EXPECT_POLL,
            poll.node,
            poll.attempt,
            item=str(poll.poll),
            at=poll.at,
            payload=payload,
        )

    def context_captured(self, capture: ContextCapture) -> None:
        payload: dict[str, JsonValue] = {"name": capture.name}
        self._add(
            EventType.CONTEXT_CAPTURE,
            capture.node,
            capture.attempt,
            item=capture.name,
            at=capture.at,
            payload=payload,
        )

    def _add(
        self,
        kind: EventType,
        step: str,
        attempt: int,
        *,
        item: str,
        at: datetime,
        payload: dict[str, JsonValue],
    ) -> None:
        self.events.append(
            Event(
                project=self.project,
                session=f"run:{self.run_id}",
                type=kind,
                timestamp=at,
                source=EventSource.EXECUTOR,
                source_id=f"{self.run_id}:{step}:{attempt}:{kind}:{item}",
                payload={"run": self.run_id, "attempt": attempt, **payload},
                repo=self.repo,
                workflow=self.workflow,
                step=step,
            )
        )
