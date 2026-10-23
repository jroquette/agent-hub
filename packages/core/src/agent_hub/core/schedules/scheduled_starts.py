"""Start the workflows ``hub.json`` schedules and the repo events it names (ADR 0048).

``StartScheduledRuns`` is the use case ``hub web`` ticks: ``start_due_slots(now)`` starts, per
registered hub, each schedule whose most recent slot at or before ``now`` is later than the one
its ledger holds (a missed slot runs once, older ones never); ``poll_events()`` asks each event
source for its newest items and starts one run per id it has not seen, oldest first (the first
successful poll of a source is a baseline and starts nothing). The ledger is changed under the
hub's exclusive lock **before** any run starts, so a slot or an event starts at most once, across
restarts and across two ``hub web`` processes. Each start goes through ``StartWorkflowRun``, with
its guards (``issue-to-pr`` refused, one live run per issue). Nothing is logged here: the report
says what started and what failed, and the caller logs it.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Annotated, Final, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.schedules import EventKind, EventStart, Schedule
from agent_hub.core.json_form import JsonValue
from agent_hub.core.schedules.cron import parse_cron
from agent_hub.core.workflows.launch import (
    RunAccepted,
    RunTrigger,
    StartRunRequest,
    WorkflowPlans,
)

# The items one poll reads, newest first.
EVENT_PAGE: Final = 20
# The ids kept per source: more than a page, so an id leaves the page before it leaves the ledger.
MAX_SEEN: Final = 100
MAX_LEDGER_SLOTS: Final = 32
MAX_LEDGER_SOURCES: Final = 32


@dataclass(frozen=True)
class EventQuery:
    """One event source: the kind of event, the GitHub repo (``owner/name``) and its branch."""

    kind: EventKind
    github: str
    branch: str


@dataclass(frozen=True)
class EventRef:
    """One event: its id (a commit sha, a PR number, an Actions run id) and the inputs it offers."""

    id: str
    data: Mapping[str, JsonValue]


class EventPollError(AgentHubError):
    """A poll that read nothing usable; the message names why, never the answer's text."""


class EventSource(Protocol):
    def poll(self, query: EventQuery) -> tuple[EventRef, ...]:
        """The newest events of ``query`` first, at most ``EVENT_PAGE``; ``EventPollError``."""
        ...


class StartState(BaseModel):
    """A hub's ledger: the last slot started per workflow and the event ids seen per source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    slots: Annotated[dict[str, AwareDatetime], Field(max_length=MAX_LEDGER_SLOTS)] = Field(
        default_factory=dict
    )
    seen: Annotated[
        dict[str, Annotated[tuple[str, ...], Field(max_length=MAX_SEEN)]],
        Field(max_length=MAX_LEDGER_SOURCES),
    ] = Field(default_factory=dict)


class StartLedgerError(AgentHubError):
    """The ledger cannot be read or written; it is never overwritten then."""


class StartLedgerBusyError(StartLedgerError):
    """Another process holds the hub's ledger lock."""


class StartLedger(Protocol):
    def update[R](self, hub_path: str, change: Callable[[StartState], tuple[StartState, R]]) -> R:
        """Run ``change`` on the hub's state under its exclusive lock, write the new state
        (atomically, only when it differs) and return ``change``'s result. A change that
        raises writes nothing. ``StartLedgerError`` (``StartLedgerBusyError``) otherwise."""
        ...


@dataclass(frozen=True)
class ScheduledHub:
    """A registered hub that may start runs by itself: its project, folder and config."""

    project: str
    hub_path: str
    config: HubConfig


class ScheduledHubs(Protocol):
    def scheduled_hubs(self) -> Iterable[ScheduledHub]:
        """Each valid registered project with its hub folder and config, the first of a name."""
        ...


class RunStarter(Protocol):
    """``StartWorkflowRun``'s call shape."""

    def __call__(
        self,
        request: StartRunRequest,
        *,
        trigger: RunTrigger | None = None,
        environment: str | None = None,
    ) -> RunAccepted:
        """Start the run; an ``AgentHubError`` when it is refused or cannot start."""
        ...


@dataclass(frozen=True)
class StartedRun:
    """A run started by itself."""

    project: str
    workflow: str
    run_id: str
    trigger: RunTrigger


@dataclass(frozen=True)
class StartFailure:
    """A start, a poll or a ledger read that failed; ``workflow`` is None for a whole hub."""

    project: str
    workflow: str | None
    reason: str


@dataclass(frozen=True)
class StartReport:
    """What one tick or poll did."""

    started: tuple[StartedRun, ...] = ()
    failures: tuple[StartFailure, ...] = ()


class _Report:
    def __init__(self) -> None:
        self.started: list[StartedRun] = []
        self.failures: list[StartFailure] = []

    def fail(self, project: str, workflow: str | None, reason: str) -> None:
        self.failures.append(StartFailure(project=project, workflow=workflow, reason=reason))

    def done(self) -> StartReport:
        return StartReport(started=tuple(self.started), failures=tuple(self.failures))


def source_key(event: EventStart) -> str:
    """The ledger's key of an event source: ``<workflow> <on> <repo>``."""
    return f"{event.workflow} {event.on} {event.repo}"


class StartScheduledRuns:
    """The scheduled and event starts of every registered hub (see the module docstring)."""

    def __init__(
        self,
        *,
        hubs: ScheduledHubs,
        plans: WorkflowPlans,
        ledger: StartLedger,
        events: EventSource,
        start: RunStarter,
    ) -> None:
        self._hubs, self._plans, self._ledger = hubs, plans, ledger
        self._events, self._start = events, start

    def start_due_slots(self, now: datetime) -> StartReport:
        """Start each schedule whose most recent slot at or before ``now`` has not started."""
        report = _Report()
        for hub in self._hubs.scheduled_hubs():
            schedules = hub.config.schedules
            if not schedules:
                continue
            try:
                due = self._ledger.update(
                    hub.hub_path, partial(_record_slots, schedules=schedules, now=now)
                )
            except StartLedgerError as error:
                report.fail(hub.project, None, str(error))
                continue
            for schedule in due:
                self._launch(
                    hub,
                    workflow=schedule.workflow,
                    inputs=dict(schedule.inputs),
                    report=report,
                    environment=schedule.environment,
                    trigger="schedule",
                )
        return report.done()

    def poll_events(self) -> StartReport:
        """Poll each event source and start one run per event not seen before."""
        report = _Report()
        for hub in self._hubs.scheduled_hubs():
            if hub.config.events:
                self._poll_hub(hub, report)
        return report.done()

    def _poll_hub(self, hub: ScheduledHub, report: _Report) -> None:
        # Polled outside the lock: a slow gh call never holds the ledger.
        polled = self._polled(hub, report)
        if not polled:
            return
        declared = tuple(source_key(event) for event in hub.config.events)
        try:
            new = self._ledger.update(
                hub.hub_path, partial(_record_seen, polled=polled, declared=declared)
            )
        except StartLedgerError as error:
            report.fail(hub.project, None, str(error))
            return
        for event, ref in new:
            inputs = self._event_inputs(hub, event, ref=ref, report=report)
            if inputs is not None:
                self._launch(
                    hub,
                    workflow=event.workflow,
                    inputs=inputs,
                    report=report,
                    environment=None,
                    trigger="event",
                )

    def _polled(
        self, hub: ScheduledHub, report: _Report
    ) -> list[tuple[EventStart, tuple[EventRef, ...]]]:
        config = hub.config
        github = {repo.dir: repo.github for repo in config.repos}
        polled: list[tuple[EventStart, tuple[EventRef, ...]]] = []
        for event in config.events:
            query = EventQuery(event.on, github[event.repo], config.default_branch_for(event.repo))
            try:
                polled.append((event, self._events.poll(query)[:EVENT_PAGE]))
            except EventPollError as error:
                reason = f"event poll failed: {source_key(event)}: {error}"
                report.fail(hub.project, event.workflow, reason)
        return polled

    def _event_inputs(
        self, hub: ScheduledHub, event: EventStart, *, ref: EventRef, report: _Report
    ) -> dict[str, JsonValue] | None:
        # The event's data reaches the run only as inputs the workflow declares (ADR 0048).
        try:
            _, plan = self._plans.workflow_plan(hub.project, event.workflow)
        except AgentHubError as error:
            report.fail(hub.project, event.workflow, str(error))
            return None
        declared = plan.document.inputs
        offered = {name: value for name, value in ref.data.items() if name in declared}
        return {**event.inputs, **offered}

    def _launch(  # noqa: PLR0913 -- one start's parts, all keyword-only
        self,
        hub: ScheduledHub,
        *,
        workflow: str,
        inputs: Mapping[str, JsonValue],
        report: _Report,
        environment: str | None,
        trigger: RunTrigger,
    ) -> None:
        try:
            request = StartRunRequest.model_validate(
                {"project": hub.project, "workflow": workflow, "inputs": dict(inputs)}
            )
            accepted = self._start(request, trigger=trigger, environment=environment)
        except (AgentHubError, ValueError) as error:
            report.fail(hub.project, workflow, str(error))
            return
        report.started.append(
            StartedRun(
                project=hub.project, workflow=workflow, run_id=accepted.run_id, trigger=trigger
            )
        )


def _record_slots(
    state: StartState, *, schedules: Sequence[Schedule], now: datetime
) -> tuple[StartState, tuple[Schedule, ...]]:
    # Only the hub's current schedules are kept, so the ledger stays within its bounds.
    slots = {}
    due = []
    for schedule in schedules:
        latest = parse_cron(schedule.cron).latest_at_or_before(now)
        last = state.slots.get(schedule.workflow)
        if latest is not None and (last is None or latest > last):
            due.append(schedule)
            last = latest
        if last is not None:
            slots[schedule.workflow] = last
    return state.model_copy(update={"slots": slots}), tuple(due)


def _record_seen(
    state: StartState,
    *,
    polled: Sequence[tuple[EventStart, tuple[EventRef, ...]]],
    declared: tuple[str, ...],
) -> tuple[StartState, tuple[tuple[EventStart, EventRef], ...]]:
    # A source no longer declared is dropped; one whose poll failed keeps what it had. A
    # source seen for the first time records a baseline and starts nothing.
    seen = {key: ids for key, ids in state.seen.items() if key in declared}
    new: list[tuple[EventStart, EventRef]] = []
    for event, refs in polled:
        key = source_key(event)
        known = seen.get(key)
        if known is None:
            seen[key] = tuple(ref.id for ref in refs)[:MAX_SEEN]
            continue
        fresh = [ref for ref in refs if ref.id not in known]
        new.extend((event, ref) for ref in reversed(fresh))
        seen[key] = (*(ref.id for ref in fresh), *known)[:MAX_SEEN]
    return state.model_copy(update={"seen": seen}), tuple(new)
