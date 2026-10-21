"""A scenario run's own events (docs/design/scenarios.md § Events and bounds): metadata only.

Each action call is a ``policy.decision`` (every decision, a deny too; a process workflow's
shell, script and ``until_bash`` decisions too, with ``node`` for ``action``) and, when it runs,
``action.start`` and ``action.end``, built from its ``ActionFacts``: names, its pinned hash, its
effect, origin, decision and approver; never an arg, an output or a credential. A standalone
``hub action run`` has no run: its events carry the session ``action:<uuid>``, no ``run`` key
and no ``workflow``.

``ScenarioEvents`` is the engine's ``RunTrace`` for a scenario run: each ``expect`` poll is an
``expect.poll`` (``poll`` count, ``held``), each ``capture:`` value a ``context.capture``
(``name``). Source ``executor``, session ``run:<run>``, ``workflow`` the run's label
(``scenario:<name>``) and ``step`` the node id as recorded, as the run's other events
(``workflows.events``). Outputs and captured values stay in the run's record, never here
(ADR 0019). ``source_id`` is ``<run>:<step>:<attempt>:<type>:<poll or name>``: an expect's
action call gives its ``poll`` (from 1), so each poll's call is an event of its own (the store
keeps one event per source id); a plain call has none, and an investigation's read gives its own
``item``.

An investigation adds a ``finding`` per finding of a proposal (``finding_id`` and the diverged
``step``; its title and text stay in the record) and, when an option is picked,
``workaround.start`` and ``workaround.end`` (``workaround_id``, ``option`` id, ``steps`` count,
``status``), their attempt the investigation's number.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import Decision, Effect, Origin, ReasonKind
from agent_hub.core.scenarios.policy_gates import NodeDecision
from agent_hub.core.workflows.ports import ContextCapture, ExpectPoll


class ActionFacts(BaseModel):
    """What the events of one action call say: ``step`` is the node id as recorded (a
    standalone call's action reference), ``services`` the ``<repo>/<service>`` names its
    ``service`` inputs resolved to, ``approver`` who answered an ask."""

    model_config = ConfigDict(frozen=True)

    step: str
    attempt: int
    action: str
    content_hash: str
    environment: str
    services: tuple[str, ...]
    effect: Effect
    origin: Origin
    decision: Decision
    approver: str | None = None

    def decided(self) -> dict[str, JsonValue]:
        return {
            "action": self.action,
            "environment": self.environment,
            "effect": self.effect,
            "origin": self.origin,
            "decision": self.decision,
        }

    def called(self) -> dict[str, JsonValue]:
        called: dict[str, JsonValue] = {
            **self.decided(),
            "content_hash": self.content_hash,
            "service": list(self.services),
        }
        return called if self.approver is None else {**called, "approver": self.approver}


class WorkaroundFacts(BaseModel):
    """What a workaround's events say: the diverged ``step``, the investigation's number
    (``attempt``), the workaround's id, the option picked and its step count."""

    model_config = ConfigDict(frozen=True)

    step: str
    attempt: int
    workaround_id: str
    option: str
    steps: int

    def payload(self, status: str) -> dict[str, JsonValue]:
        return {
            "workaround_id": self.workaround_id,
            "option": self.option,
            "steps": self.steps,
            "status": status,
        }


class ScenarioEvents:
    """The events of one scenario run (or one standalone action call: ``run_id`` ``None`` and
    its own ``session``), in the order they came."""

    def __init__(
        self,
        *,
        project: str,
        run_id: str | None,
        workflow: str | None,
        repo: str | None = None,
        session: str | None = None,
    ) -> None:
        self.project, self.run_id, self.workflow, self.repo = project, run_id, workflow, repo
        self.session = session if session is not None else f"run:{run_id}"
        self.events: list[Event] = []

    def policy_decided(
        self,
        facts: ActionFacts,
        *,
        reason_kind: ReasonKind,
        at: datetime,
        poll: int = 0,
        item: str | None = None,
    ) -> None:
        """An action call's decision; ``item`` ``start`` for a process workflow's start."""
        payload = {**facts.decided(), "reason_kind": reason_kind}
        self._add(
            EventType.POLICY_DECISION,
            facts.step,
            facts.attempt,
            item=_poll_item(poll) if item is None else item,
            at=at,
            payload=payload,
        )

    def node_decided(
        self, decision: NodeDecision, *, attempt: int, at: datetime, item: str = ""
    ) -> None:
        """A process workflow node's decision (a shell or script node, or an ``until_bash``):
        ``attempt`` 0 and ``item`` ``start`` at the start, the call's attempt after."""
        payload: dict[str, JsonValue] = {
            "node": decision.step,
            "environment": decision.environment,
            "effect": decision.effect,
            "origin": "author",
            "decision": decision.decision.decision,
            "reason_kind": decision.decision.reason_kind,
        }
        self._add(
            EventType.POLICY_DECISION, decision.step, attempt, item=item, at=at, payload=payload
        )

    def action_started(
        self, facts: ActionFacts, *, at: datetime, poll: int = 0, item: str | None = None
    ) -> None:
        payload = facts.called()
        self._add(
            EventType.ACTION_START,
            facts.step,
            facts.attempt,
            item=_poll_item(poll) if item is None else item,
            at=at,
            payload=payload,
        )

    def action_ended(
        self,
        facts: ActionFacts,
        *,
        status: str,
        failure_kind: str | None,
        at: datetime,
        poll: int = 0,
        item: str | None = None,
    ) -> None:
        payload: dict[str, JsonValue] = {**facts.called(), "status": status}
        if failure_kind is not None:
            payload["failure_kind"] = failure_kind
        self._add(
            EventType.ACTION_END,
            facts.step,
            facts.attempt,
            item=_poll_item(poll) if item is None else item,
            at=at,
            payload=payload,
        )

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

    def finding_recorded(self, *, step: str, attempt: int, finding_id: str, at: datetime) -> None:
        """A finding of an investigation's proposal: its id and the diverged step only."""
        payload: dict[str, JsonValue] = {"finding_id": finding_id, "step": step}
        self._add(EventType.FINDING, step, attempt, item=finding_id, at=at, payload=payload)

    def workaround_started(self, facts: WorkaroundFacts, *, at: datetime) -> None:
        self._add(
            EventType.WORKAROUND_START,
            facts.step,
            facts.attempt,
            item=facts.workaround_id,
            at=at,
            payload=facts.payload("started"),
        )

    def workaround_ended(self, facts: WorkaroundFacts, *, status: str, at: datetime) -> None:
        self._add(
            EventType.WORKAROUND_END,
            facts.step,
            facts.attempt,
            item=facts.workaround_id,
            at=at,
            payload=facts.payload(status),
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
        run: dict[str, JsonValue] = {} if self.run_id is None else {"run": self.run_id}
        origin = self.run_id if self.run_id is not None else self.session
        self.events.append(
            Event(
                project=self.project,
                session=self.session,
                type=kind,
                timestamp=at,
                source=EventSource.EXECUTOR,
                source_id=f"{origin}:{step}:{attempt}:{kind}:{item}",
                payload={**run, "attempt": attempt, **payload},
                repo=self.repo,
                workflow=self.workflow,
                step=step,
            )
        )


def _poll_item(poll: int) -> str:
    """An action call's ``source_id`` item: its expect poll, or nothing for a plain call."""
    return str(poll) if poll else ""
