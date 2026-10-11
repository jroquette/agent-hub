"""In-memory fakes of the core ports, used by unit tests and checked by the contract suites."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_hub.core.errors import TrackerError
from agent_hub.core.events.append_plan import plan_append
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.event_query import EventPage, EventQuery
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.tracker.tracker_client import (
    CLOSED_STATE_TYPES,
    ISSUE_ID_PATTERN,
    UNSTARTED_STATE_TYPES,
    Issue,
)


class InMemoryEventStore:
    """An ``EventStore`` kept in memory; it plans the whole batch before changing anything.

    Like the SQLite store, it mints a UUIDv7 ``event_id`` and a ``received_at`` for each new
    event, and numbers events from 1 in append order.
    """

    def __init__(self) -> None:
        self._by_key: dict[EventKey, Event] = {}
        self._stored: list[StoredEvent] = []

    def append(self, events: Sequence[Event]) -> AppendResult:
        """Append the new events of the batch; a conflict raises before any change."""
        plan = plan_append(events, self._by_key)
        received_at = datetime.now(UTC)
        for event in plan.new_events:
            # Event is frozen only shallowly: keep a copy, so the caller's payload stays theirs.
            copied = event.model_copy(deep=True)
            self._by_key[event.key] = copied
            self._stored.append(
                StoredEvent(
                    seq=len(self._stored) + 1,
                    event_id=str(uuid.uuid7()),
                    received_at=received_at,
                    event=copied,
                )
            )
        return AppendResult(appended=len(plan.new_events), duplicates=plan.duplicates)

    def read_all(self) -> list[Event]:
        """Return every stored event in the order it was appended."""
        return [stored.event.model_copy(deep=True) for stored in self._stored]

    def query(self, query: EventQuery) -> EventPage:
        """The stored events matching ``query`` (see ``EventReader.query``)."""
        matching = [stored for stored in self._stored if _matches(stored, query)]
        if query.order == "desc":
            matching.reverse()
        items = tuple(stored.model_copy(deep=True) for stored in matching[: query.limit])
        has_more = len(matching) > query.limit
        next_after_seq = items[-1].seq if has_more and query.order == "asc" else None
        return EventPage(items=items, next_after_seq=next_after_seq)

    def find(self, event_id: str) -> StoredEvent | None:
        """The stored event with this storage id, or None."""
        for stored in self._stored:
            if stored.event_id == event_id:
                return stored.model_copy(deep=True)
        return None

    def high_water_mark(self) -> int:
        """The last append sequence, 0 when empty."""
        return len(self._stored)


def _matches(stored: StoredEvent, query: EventQuery) -> bool:
    event = stored.event
    checks = (
        query.project is None or event.project == query.project,
        query.session is None or event.session == query.session,
        not query.types or event.type in query.types,
        query.since is None or event.timestamp >= query.since,
        query.until is None or event.timestamp < query.until,
        query.after_seq is None or stored.seq > query.after_seq,
        query.before_seq is None or stored.seq < query.before_seq,
    )
    return all(checks)


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
