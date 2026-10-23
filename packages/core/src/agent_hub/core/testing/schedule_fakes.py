"""In-memory stand-ins for the scheduled starts' ports (ADR 0048): the ledger, the event source,
the run starter and the registered hubs."""

from collections.abc import Callable, Iterable, Mapping

from agent_hub.core.errors import AgentHubError
from agent_hub.core.schedules.scheduled_starts import (
    EventPollError,
    EventQuery,
    EventRef,
    ScheduledHub,
    StartLedgerError,
    StartState,
)
from agent_hub.core.workflows.launch import RunAccepted, RunTrigger, StartRunRequest


class InMemoryStartLedger:
    """``StartLedger`` over a dict; ``unreadable`` hubs raise ``StartLedgerError``."""

    def __init__(self) -> None:
        self.states: dict[str, StartState] = {}
        self.unreadable: set[str] = set()
        self.writes = 0

    def update[R](self, hub_path: str, change: Callable[[StartState], tuple[StartState, R]]) -> R:
        if hub_path in self.unreadable:
            raise StartLedgerError("the schedule ledger cannot be read")
        state = self.states.get(hub_path, StartState())
        new, result = change(state)
        if new != state:
            self.states[hub_path] = new
            self.writes += 1
        return result


class ScriptedEventSource:
    """``EventSource`` answering each query with what the test set (none: no event), recording
    every query; an ``EventPollError`` set as the answer is raised."""

    def __init__(self) -> None:
        self.answers: dict[EventQuery, tuple[EventRef, ...] | EventPollError] = {}
        self.queries: list[EventQuery] = []

    def poll(self, query: EventQuery) -> tuple[EventRef, ...]:
        self.queries.append(query)
        answer = self.answers.get(query, ())
        if isinstance(answer, EventPollError):
            raise answer
        return answer


class RecordingRunStarter:
    """``RunStarter`` recording each request with its trigger and environment; a workflow in
    ``refused`` raises its error instead."""

    def __init__(self) -> None:
        self.calls: list[tuple[StartRunRequest, RunTrigger | None, str | None]] = []
        self.refused: dict[str, AgentHubError] = {}

    def __call__(
        self,
        request: StartRunRequest,
        *,
        trigger: RunTrigger | None = None,
        environment: str | None = None,
    ) -> RunAccepted:
        if request.workflow in self.refused:
            raise self.refused[request.workflow]
        self.calls.append((request, trigger, environment))
        return RunAccepted(run_id=f"run-{len(self.calls)}", project=request.project, action="start")

    def inputs(self) -> list[Mapping[str, object]]:
        """The inputs of each recorded start."""
        return [dict(request.inputs) for request, _, _ in self.calls]


class StaticScheduledHubs:
    """``ScheduledHubs`` over a fixed list."""

    def __init__(self, *hubs: ScheduledHub) -> None:
        self.hubs = hubs

    def scheduled_hubs(self) -> Iterable[ScheduledHub]:
        return self.hubs
