"""In-memory fakes of the core ports, used by unit tests and checked by the contract suites."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_hub.core.errors import TrackerError
from agent_hub.core.events.append_plan import plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.tracker.tracker_client import (
    CLOSED_STATE_TYPES,
    ISSUE_ID_PATTERN,
    UNSTARTED_STATE_TYPES,
    Issue,
)


class InMemoryEventStore:
    """An ``EventStore`` kept in memory; it plans the whole batch before changing anything."""

    def __init__(self) -> None:
        self._by_key: dict[EventKey, Event] = {}
        self._events: list[Event] = []

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append the new events of the batch; a conflict raises before any change."""
        plan = plan_append(events, self._by_key)
        for event in plan.new_events:
            # Event is frozen only shallowly: keep a copy, so the caller's payload stays theirs.
            stored = event.model_copy(deep=True)
            self._by_key[event.key] = stored
            self._events.append(stored)
        return AppendResult(appended=len(plan.new_events), duplicates=plan.duplicates)

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        return [event.model_copy(deep=True) for event in self._events]


@dataclass(frozen=True, kw_only=True, slots=True)
class TrackerState:
    """A workflow state of a team.

    ``type`` is Linear's ``WorkflowState.type`` (``triage``, ``backlog``, ``unstarted``,
    ``started``, ``completed``, ``canceled`` or ``duplicate``); ``closed`` is derived from it.
    """

    name: str
    type: str

    @property
    def closed(self) -> bool:
        """True for a ``completed``, ``canceled`` or ``duplicate`` state."""
        return self.type in CLOSED_STATE_TYPES


@dataclass(kw_only=True, slots=True)
class FakeTrackerBackend:
    """The tracker's data, shared by the in-memory client and the adapters' fake servers.

    Tests read and seed it directly, so a write is observed here, not through the port.
    ``comments`` holds ``(issue_id, body)`` pairs in the order they were added.
    """

    states: dict[str, tuple[TrackerState, ...]] = field(default_factory=dict)
    team_labels: dict[str, tuple[str, ...]] = field(default_factory=dict)
    workspace_labels: tuple[str, ...] = ()
    issues: dict[str, Issue] = field(default_factory=dict)
    comments: list[tuple[str, str]] = field(default_factory=list)


class InMemoryTrackerClient:
    """A ``TrackerClient`` over a ``FakeTrackerBackend``; it checks every name before a change."""

    def __init__(self, backend: FakeTrackerBackend) -> None:
        self._backend = backend

    def list_ready(self, team: str, label: str) -> list[Issue]:
        """Return the team's open issues with the label; an unknown team or label matches none."""
        if team not in self._backend.states:
            return []
        closed = {state.name for state in self._backend.states[team] if state.closed}
        return [
            issue
            for issue in self._backend.issues.values()
            if _team_of(issue.id) == team and label in issue.labels and issue.state not in closed
        ]

    def get_issue(self, issue_id: str) -> Issue:
        """Return the stored issue."""
        return self._issue("get_issue", issue_id)

    def move_state(
        self, issue_id: str, state_name: str, *, only_if_unstarted: bool = False
    ) -> bool:
        """Move the issue to a state of its team; the current state is a no-op (False).

        With ``only_if_unstarted``, an issue in a state of another type than
        ``UNSTARTED_STATE_TYPES`` is left alone (False) before ``state_name`` is checked.
        """
        issue = self._issue("move_state", issue_id)
        states = self._team_states("move_state", issue_id)
        if only_if_unstarted:
            types = {state.name: state.type for state in states}
            if types.get(issue.state) not in UNSTARTED_STATE_TYPES:
                return False
        names = [state.name for state in states]
        if state_name not in names:
            raise TrackerError(
                operation="move_state",
                issue_id=issue_id,
                cause=f"state {state_name!r} not found in team {_team_of(issue_id)}",
                fix=f"use one of: {', '.join(names)}",
            )
        if issue.state == state_name:
            return False
        self._store(issue.model_copy(update={"state": state_name}))
        return True

    def add_label(self, issue_id: str, name: str) -> None:
        """Add a label of the issue's team or workspace; a present label is a no-op."""
        issue = self._issue("add_label", issue_id)
        self._check_label("add_label", issue_id, name)
        if name not in issue.labels:
            self._store(issue.model_copy(update={"labels": (*issue.labels, name)}))

    def remove_label(self, issue_id: str, name: str) -> None:
        """Remove a known label; one the issue does not carry is a no-op."""
        issue = self._issue("remove_label", issue_id)
        self._check_label("remove_label", issue_id, name)
        if name in issue.labels:
            labels = tuple(label for label in issue.labels if label != name)
            self._store(issue.model_copy(update={"labels": labels}))

    def comment(self, issue_id: str, body: str) -> None:
        """Record one comment on the issue."""
        self._issue("comment", issue_id)
        self._backend.comments.append((issue_id, body))

    def _issue(self, operation: str, issue_id: str) -> Issue:
        if not ISSUE_ID_PATTERN.fullmatch(issue_id):
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause="malformed issue id",
                fix="pass an identifier such as DEM-1",
            )
        issue = self._backend.issues.get(issue_id)
        if issue is None:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause="issue not found",
                fix="check the issue id",
            )
        return issue

    def _team_states(self, operation: str, issue_id: str) -> tuple[TrackerState, ...]:
        team = _team_of(issue_id)
        states = self._backend.states.get(team)
        if states is None:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"team {team} not found",
                fix="check the issue id",
            )
        return states

    def _check_label(self, operation: str, issue_id: str, name: str) -> None:
        self._team_states(operation, issue_id)
        team_labels = self._backend.team_labels.get(_team_of(issue_id), ())
        if name not in team_labels and name not in self._backend.workspace_labels:
            raise TrackerError(
                operation=operation,
                issue_id=issue_id,
                cause=f"label {name!r} not found in team {_team_of(issue_id)} or the workspace",
                fix="create the label in the tracker first",
            )

    def _store(self, issue: Issue) -> None:
        self._backend.issues[issue.id] = issue


def _team_of(issue_id: str) -> str:
    # The team key is the identifier's prefix, as in Linear (``DEM-1`` belongs to ``DEM``).
    return issue_id.partition("-")[0]
