"""The Tickets view of a feature (AGH-136): each ticket's row, the planning and the source.

A row joins the plan's ticket (``features.json`` → ``tickets``) and Linear's summary of it;
``ref`` is the ticket's id once created, else its draft key, and every reference between rows
uses it. Everything here is derived: planning is a recommendation, never an action.
"""

from typing import Literal

from agent_hub.core.features.feature_view import GoldenPath, TicketsSource
from agent_hub.core.readmodels.view_types import ApiTimestamp, DerivedView, ViewModel
from agent_hub.core.tracker.tracker_reader import IssueState

# Whether a ticket can start now: all blockers done (``can_start``), some not (``waiting``),
# already started in Linear (``in_progress``: In Progress, In Review…, whatever its blockers),
# itself done or canceled, part of a dependency cycle, or its state unknown (no snapshot).
type Readiness = Literal[
    "can_start", "in_progress", "waiting", "done", "canceled", "in_cycle", "unknown"
]
# Where a "blocked by" edge comes from: the plan's ``blocked_by``, Linear's relations, or both.
type EdgeSource = Literal["plan", "linear", "both"]


class TicketEdge(ViewModel):
    """A "blocked by" edge to the ticket ``ref`` (a row's ``ref`` or an external issue id)."""

    ref: str
    source: EdgeSource


class TicketRow(ViewModel):
    """One ticket of the feature.

    ``key`` is the plan's draft key (None for a ticket only Linear or ``linear`` lists), ``id``
    the tracker identifier (None until created). ``title``, ``state``, ``assignee`` and ``url``
    come from Linear when read, else ``title`` from the plan and the others None. ``acs`` are the
    AC ids whose ``ticket`` names it; ``blocks`` the refs it blocks; ``waiting_on`` the refs of
    its blockers not done yet. ``reviewed`` is None when unknown (no snapshot and no record).
    """

    ref: str
    key: str | None
    id: str | None
    title: str | None
    state: IssueState | None
    assignee: str | None
    url: str | None
    priority: int | None
    estimate: float | None
    repo: str | None
    order: int | None
    acs: tuple[str, ...]
    blocked_by: tuple[TicketEdge, ...]
    blocks: tuple[str, ...]
    readiness: Readiness
    waiting_on: tuple[str, ...]
    reviewed: bool | None


class ExternalBlocker(ViewModel):
    """A blocker outside the feature's tickets, with its status when Linear returned it."""

    id: str
    title: str | None
    state: IssueState | None
    url: str | None
    done: bool


class TicketPlan(ViewModel):
    """The planning of the feature's tickets, every ticket named by its row's ``ref``.

    ``layers`` are the parallel groups (Kahn's layers over tickets not done or canceled);
    ``can_start`` the first layer's tickets that wait on nothing and are not started yet;
    ``order`` the recommended order; ``waiting`` the tickets with a blocker not done;
    ``cycles`` each dependency cycle (left out of the layers); ``critical_path`` the longest
    chain of tickets not done.
    """

    layers: tuple[tuple[str, ...], ...]
    can_start: tuple[str, ...]
    order: tuple[str, ...]
    waiting: tuple[str, ...]
    cycles: tuple[tuple[str, ...], ...]
    external_blockers: tuple[ExternalBlocker, ...]
    critical_path: tuple[str, ...]
    warnings: tuple[str, ...]


class TrackerProblem(ViewModel):
    """Why Linear was not read, as RFC 9457 members: ``type`` is
    ``urn:agent-hub:problem:tracker-<kind>``, ``status`` Linear's HTTP status (or 503 when it did
    not answer, 504 on a timeout)."""

    type: str
    title: str
    status: int
    detail: str


class FeatureTickets(DerivedView):
    """``GET /features/{project}/{slug}/tickets``: the tickets, their planning and the golden
    path computed with them.

    ``source`` is ``linear`` when a snapshot was used (``stale`` when it is the last good one
    after a failure; ``as_of`` is when it was read), else ``plan``, with a ``notice`` and the
    ``tracker_problem`` naming the cause.
    """

    project: str
    slug: str
    source: TicketsSource
    stale: bool
    as_of: ApiTimestamp | None
    notice: str | None
    tracker_problem: TrackerProblem | None
    tickets: tuple[TicketRow, ...]
    planning: TicketPlan
    golden_path: GoldenPath
