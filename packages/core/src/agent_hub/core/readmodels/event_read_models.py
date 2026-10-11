"""``EventReadModels`` over an ``EventReader``: folds on read, snapshot pages, a memo (D12).

Every read folds the stored events up to a high-water mark into sessions, runs, approvals and
learnings. A list's first page uses the store's current mark and its cursor carries it, so the
following pages fold exactly the same events: appends between page requests never make an
item repeat or vanish (AC-200.32); they show up on the next first page.

Two memos keep reads cheap, both in process and never on disk: the loaded events, kept until
the high-water mark moves, and the folded snapshot, kept for the same mark and the same second
of ``now`` (statuses depend on the clock). Search reads only ids, paths, commands and tool
names, never payload bodies.
"""

import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from agent_hub.core.approvals.approval import Approval
from agent_hub.core.approvals.fold_approvals import fold_approvals
from agent_hub.core.events.event import EventType
from agent_hub.core.events.event_query import MAX_QUERY_LIMIT, EventQuery
from agent_hub.core.events.event_reader import EventReader
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.learnings.fold_learning import fold_learnings
from agent_hub.core.learnings.learning import Learning, LearningStatus
from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    ProjectActivity,
    SearchHit,
    SearchKind,
    StreamCounts,
)
from agent_hub.core.readmodels.cursor import (
    Cursor,
    CursorKeyPart,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    id_digest,
)
from agent_hub.core.readmodels.fact_keys import canonical_events, resolve_facts
from agent_hub.core.readmodels.filters import (
    ApprovalFilter,
    LearningFilter,
    PageRequest,
    RunFilter,
    Scope,
    SessionFilter,
)
from agent_hub.core.readmodels.fold_memo import FoldMemo
from agent_hub.core.readmodels.live_tiles import live_tiles
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.fold_run import fold_runs
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.sessions.fold_session import fold_session, group_by_session, run_issues
from agent_hub.core.sessions.pricing import PRICES, PerMillion
from agent_hub.core.sessions.session import (
    Session,
    SessionCost,
    SessionFileChange,
    SessionStatus,
    SessionSummary,
    TimelineEvent,
)
from agent_hub.core.sessions.session_cost import fold_session_cost
from agent_hub.core.sessions.session_files import fold_session_files
from agent_hub.core.sessions.session_summary import summarize_session

type SortKey = tuple[CursorKeyPart, ...]

RECENT = timedelta(days=7)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
DAYS_IN_PERIOD = 7
_IN_FLIGHT_DONE = frozenset({Stage.REPORTED, Stage.FAILED})
_SEARCH_ORDER: Mapping[SearchKind, int] = {
    "session": 0,
    "run": 1,
    "approval": 2,
    "learning": 3,
    "feature": 4,
    "file": 5,
    "command": 6,
    "tool": 7,
}


# What a session's fold depends on besides its id: its event count and highest seq, the time
# it was folded at, and the run issues.
type _SessionKey = tuple[int, int, datetime, frozenset[tuple[str, str]]]


@dataclass(frozen=True, kw_only=True, slots=True)
class _Snapshot:
    """Everything folded from the events up to ``hwm``, at one ``now``."""

    hwm: int
    now: datetime
    events: tuple[StoredEvent, ...]
    by_session: Mapping[str, Sequence[StoredEvent]]
    sessions: Mapping[str, Session]
    runs: Mapping[str, WorkflowRun]
    approvals: Mapping[str, Approval]
    learnings: Mapping[str, Learning]


def _microseconds(moment: datetime | None) -> int:
    return 0 if moment is None else int(moment.timestamp() * 1_000_000)


def _money_key(value: Decimal | None, *, descending: bool) -> SortKey:
    # A missing amount sorts last both ways; amounts compare exactly at 10 decimal places.
    if value is None:
        return (0 if descending else 1, 0)
    return (1 if descending else 0, int(value.scaleb(10).to_integral_value()))


def _after(key: SortKey, item_id: str, cursor: Cursor, *, descending: bool) -> bool:
    try:
        if descending:
            return (key, item_id) < (cursor.key, cursor.id)
        return (key, item_id) > (cursor.key, cursor.id)
    except TypeError as error:
        msg = "invalid cursor: it belongs to another list or sort"
        raise InvalidCursorError(msg) from error


def _after_cursor[T](
    ordered: list[T],
    cursor: Cursor,
    *,
    key: Callable[[T], SortKey],
    item_id: Callable[[T], str],
    descending: bool,
) -> list[T]:
    if cursor.id is not None:
        return [
            item
            for item in ordered
            if _after(key(item), item_id(item), cursor, descending=descending)
        ]
    # Compact cursor: start right after the item whose id has its digest, in the same snapshot.
    for index, item in enumerate(ordered):
        if id_digest(item_id(item)) == cursor.id_digest:
            return ordered[index + 1 :]
    msg = "invalid cursor: the item it points to is gone; load the first page again"
    raise InvalidCursorError(msg)


def _paginate[T](
    items: Sequence[T],
    *,
    key: Callable[[T], SortKey],
    item_id: Callable[[T], str],
    descending: bool,
    request: PageRequest,
    hwm: int,
) -> Page[T]:
    ordered = sorted(items, key=lambda item: (key(item), item_id(item)), reverse=descending)
    if request.cursor is not None:
        ordered = _after_cursor(
            ordered,
            decode_cursor(request.cursor),
            key=key,
            item_id=item_id,
            descending=descending,
        )
    page = ordered[: request.limit]
    next_cursor = None
    if len(ordered) > request.limit:
        last = page[-1]
        next_cursor = encode_cursor(Cursor(hwm=hwm, key=key(last), id=item_id(last)))
    return Page[T](items=tuple(page), next_cursor=next_cursor, total_estimate=len(items))


def _whole[T](items: Sequence[T]) -> Page[T]:
    return Page[T](items=tuple(items), next_cursor=None, total_estimate=len(items))


def _in_scope(project: str, scope: Scope) -> bool:
    return scope.project is None or scope.project == project


class FoldedEventReadModels:
    """The ``EventReadModels`` port, folding the events an ``EventReader`` returns.

    ``now`` is the clock (folds never read one themselves); ``hub_path_of`` names a project's
    hub path for "How to decide", when the caller knows it.
    """

    def __init__(
        self,
        reader: EventReader,
        *,
        now: Callable[[], datetime],
        hub_path_of: Callable[[str], str | None] | None = None,
        prices: Mapping[str, PerMillion] = PRICES,
    ) -> None:
        self._reader = reader
        self._now = now
        self._hub_path_of = hub_path_of
        self._prices = prices
        # The events read so far and the mark they were read up to: the store only grows, so
        # a later read takes only what was appended since.
        self._loaded: tuple[int, tuple[StoredEvent, ...]] = (0, ())
        self._loading = threading.Lock()
        self._snapshots: FoldMemo[tuple[int, datetime], _Snapshot] = FoldMemo(max_entries=8)
        # The last fold of each session and what it was folded from: a session whose events,
        # ``now`` and run issues are unchanged is not folded again.
        self._sessions: dict[str, tuple[_SessionKey, Session]] = {}
        self._sessions_lock = threading.Lock()

    # Loading and folding

    def _load(self, *, after: int, hwm: int) -> tuple[StoredEvent, ...]:
        loaded: list[StoredEvent] = []
        after_seq = after
        while True:
            page = self._reader.query(EventQuery(after_seq=after_seq, limit=MAX_QUERY_LIMIT))
            loaded.extend(stored for stored in page.items if stored.seq <= hwm)
            if page.next_after_seq is None or page.next_after_seq >= hwm:
                return tuple(loaded)
            after_seq = page.next_after_seq

    def _events_up_to(self, hwm: int) -> tuple[StoredEvent, ...]:
        current = self._reader.high_water_mark()
        with self._loading:
            loaded_hwm, events = self._loaded
            if current != loaded_hwm:
                # A smaller mark is another store at the same path: read it all again.
                after = loaded_hwm if current > loaded_hwm else 0
                kept = events if current > loaded_hwm else ()
                events = kept + self._load(after=after, hwm=current)
                self._loaded = (current, events)
        if hwm >= current:
            return events
        return tuple(stored for stored in events if stored.seq <= hwm)

    def _fold(self, hwm: int, now: datetime) -> _Snapshot:
        events = self._events_up_to(hwm)
        # Sorted once here; every fold below takes the marked list as already canonical.
        ordered = canonical_events(events)
        by_session = group_by_session(ordered)
        issues = run_issues(ordered)
        sessions = self._fold_sessions(by_session, now=now, issues=issues)
        hub_paths = self._hub_paths({stored.event.project for stored in events})
        return _Snapshot(
            hwm=hwm,
            now=now,
            events=events,
            by_session=by_session,
            sessions=sessions,
            runs=fold_runs(ordered, sessions=sessions),
            approvals=fold_approvals(ordered, hub_paths=hub_paths),
            learnings=fold_learnings(ordered),
        )

    def _fold_sessions(
        self,
        by_session: Mapping[str, Sequence[StoredEvent]],
        *,
        now: datetime,
        issues: Mapping[str, str],
    ) -> dict[str, Session]:
        issues_key = frozenset(issues.items())
        with self._sessions_lock:
            known = dict(self._sessions)
        folded: dict[str, tuple[_SessionKey, Session]] = {}
        for session_id, group in by_session.items():
            # The store only grows, so a group's size and highest seq name its events.
            key = (len(group), max(stored.seq for stored in group), now, issues_key)
            found = known.get(session_id)
            if found is not None and found[0] == key:
                folded[session_id] = found
                continue
            session = fold_session(group, now=now, issues=issues, prices=self._prices)
            folded[session_id] = (key, session)
        with self._sessions_lock:
            self._sessions = folded
        return {session_id: session for session_id, (_, session) in folded.items()}

    def _hub_paths(self, projects: Iterable[str]) -> dict[str, str]:
        if self._hub_path_of is None:
            return {}
        paths = {project: self._hub_path_of(project) for project in projects}
        return {project: path for project, path in paths.items() if path is not None}

    def _snapshot(self, cursor: str | None = None) -> _Snapshot:
        hwm = decode_cursor(cursor).hwm if cursor is not None else self._reader.high_water_mark()
        now = self._now()
        second = now.replace(microsecond=0)
        return self._snapshots.get((hwm, second), hwm=hwm, compute=lambda: self._fold(hwm, now))

    def _session(self, snapshot: _Snapshot, session_id: str) -> Session:
        session = snapshot.sessions.get(session_id)
        if session is None:
            raise EntityNotFoundError(entity="session", entity_id=session_id)
        return session

    # Sessions

    def list_sessions(self, session_filter: SessionFilter) -> Page[Session]:
        """Sessions matching the filter, one page in its sort order."""
        snapshot = self._snapshot(session_filter.cursor)
        matching = [
            session
            for session in snapshot.sessions.values()
            if _session_matches(session, session_filter, snapshot)
        ]
        sort = session_filter.sort
        descending = sort.startswith("-")
        return _paginate(
            matching,
            key=_session_sort_key(sort.removeprefix("-"), descending=descending),
            item_id=lambda session: session.id,
            descending=descending,
            request=session_filter,
            hwm=snapshot.hwm,
        )

    def get_session(self, session_id: str) -> Session:
        """One session."""
        return self._session(self._snapshot(), session_id)

    def session_summary(self, session_id: str) -> SessionSummary:
        """The session's summary lines (D17)."""
        snapshot = self._snapshot()
        self._session(snapshot, session_id)
        return summarize_session(session_id, snapshot.by_session[session_id], now=snapshot.now)

    def session_events(
        self, session_id: str, *, types: frozenset[EventType], page: PageRequest
    ) -> Page[TimelineEvent]:
        """The session's events in timestamp order, filtered by type (empty = all)."""
        snapshot = self._snapshot(page.cursor)
        self._session(snapshot, session_id)
        timeline = _timeline(snapshot.by_session[session_id])
        selected = [item for item in timeline if not types or item.type in types]
        return _paginate(
            selected,
            key=lambda item: (_microseconds(item.timestamp), item.seq),
            item_id=lambda item: item.event_id,
            descending=False,
            request=page,
            hwm=snapshot.hwm,
        )

    def session_files(self, session_id: str) -> Page[SessionFileChange]:
        """The paths the session touched."""
        snapshot = self._snapshot()
        self._session(snapshot, session_id)
        return _whole(fold_session_files(snapshot.by_session[session_id]))

    def session_cost(self, session_id: str) -> SessionCost:
        """The session's estimated cost per turn and in total, with its run's total and budget."""
        snapshot = self._snapshot()
        session = self._session(snapshot, session_id)
        cost = fold_session_cost(session_id, snapshot.by_session[session_id], prices=self._prices)
        run = None if session.run_id is None else snapshot.runs.get(session.run_id)
        if run is None:
            return cost
        budget = None if run.caps is None else run.caps.budget_usd
        return cost.model_copy(update={"run_total_usd": run.cost_usd, "budget_usd": budget})

    def list_live_sessions(self, scope: Scope) -> Page[LiveTile]:
        """Live session tiles grouped waiting, live, idle, ended recently."""
        snapshot = self._snapshot()
        sessions = {
            session_id: session
            for session_id, session in snapshot.sessions.items()
            if _in_scope(session.project, scope)
        }
        budgets = {
            run_id: run.caps.budget_usd
            for run_id, run in snapshot.runs.items()
            if run.caps is not None and run.caps.budget_usd is not None
        }
        return _whole(live_tiles(sessions, snapshot.by_session, now=snapshot.now, budgets=budgets))

    # Runs, approvals, learnings

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        """Workflow runs matching the filter, newest first."""
        snapshot = self._snapshot(run_filter.cursor)
        matching = [run for run in snapshot.runs.values() if _run_matches(run, run_filter)]
        return _paginate(
            matching,
            key=lambda run: (_microseconds(run.started_at),),
            item_id=lambda run: run.id,
            descending=True,
            request=run_filter,
            hwm=snapshot.hwm,
        )

    def get_run(self, run_id: str) -> WorkflowRun:
        """One workflow run."""
        run = self._snapshot().runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(entity="run", entity_id=run_id)
        return run

    def list_approvals(self, approval_filter: ApprovalFilter) -> Page[Approval]:
        """Approvals matching the filter, oldest first."""
        snapshot = self._snapshot(approval_filter.cursor)
        matching = [
            approval
            for approval in snapshot.approvals.values()
            if _approval_matches(approval, approval_filter)
        ]
        return _paginate(
            matching,
            key=lambda approval: (_microseconds(approval.requested_at),),
            item_id=lambda approval: approval.id,
            descending=False,
            request=approval_filter,
            hwm=snapshot.hwm,
        )

    def get_approval(self, approval_id: str) -> Approval:
        """One approval."""
        approval = self._snapshot().approvals.get(approval_id)
        if approval is None:
            raise EntityNotFoundError(entity="approval", entity_id=approval_id)
        return approval

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """Learnings matching the filter, newest proposal first."""
        snapshot = self._snapshot(learning_filter.cursor)
        matching = [
            learning
            for learning in snapshot.learnings.values()
            if _in_scope(learning.project, learning_filter)
            and (learning_filter.status is None or learning.status == learning_filter.status)
        ]
        return _paginate(
            matching,
            key=lambda learning: (_microseconds(learning.proposed_at),),
            item_id=lambda learning: learning.id,
            descending=True,
            request=learning_filter,
            hwm=snapshot.hwm,
        )

    def get_learning(self, learning_id: str) -> Learning:
        """One learning."""
        learning = self._snapshot().learnings.get(learning_id)
        if learning is None:
            raise EntityNotFoundError(entity="learning", entity_id=learning_id)
        return learning

    # Projects, needs, activity, search, counts

    def project_activity(self, project: str) -> ProjectActivity:
        """The event-derived numbers of one project (a project with no event has zeros)."""
        snapshot = self._snapshot()
        sessions = [s for s in snapshot.sessions.values() if s.project == project]
        runs = [run for run in snapshot.runs.values() if run.project == project]
        in_flight: dict[Stage, int] = {}
        for run in runs:
            if run.stage not in _IN_FLIGHT_DONE:
                in_flight[run.stage] = in_flight.get(run.stage, 0) + 1
        now = snapshot.now
        times = [s.event.timestamp for s in snapshot.events if s.event.project == project]
        return ProjectActivity(
            project=project,
            live_sessions=sum(1 for session in sessions if _is_running(session)),
            runs_in_flight_by_stage=in_flight,
            failed_runs_7d=sum(1 for run in runs if _failed_recently(run, now)),
            cost_period=_cost_between(sessions, now - RECENT, now),
            cost_previous_period=_cost_between(sessions, now - 2 * RECENT, now - RECENT),
            cost_daily=_daily_costs(sessions, now),
            last_activity_at=max(times, default=None),
        )

    def needs_you(self, scope: Scope) -> Page[NeedsYouItem]:
        """What waits for a person, oldest first."""
        snapshot = self._snapshot()
        items = [
            *(_approval_need(item) for item in snapshot.approvals.values() if not item.decided),
            *(
                _failed_need(run)
                for run in snapshot.runs.values()
                if _failed_recently(run, snapshot.now)
            ),
            *(
                _learning_need(learning)
                for learning in snapshot.learnings.values()
                if learning.status == LearningStatus.PROPOSED
            ),
        ]
        scoped = [item for item in items if _in_scope(item.project, scope)]
        scoped.sort(key=lambda item: (item.since is None, item.since or snapshot.now, item.href))
        return _whole(scoped)

    def activity(self, page: PageRequest) -> Page[ActivityItem]:
        """Notable events, newest first."""
        snapshot = self._snapshot(page.cursor)
        items = [
            *(_run_activity(run) for run in snapshot.runs.values() if run.ended_at is not None),
            *(_learning_activity(learning) for learning in snapshot.learnings.values()),
            *(
                _approval_activity(approval)
                for approval in snapshot.approvals.values()
                if approval.decided
            ),
        ]
        scoped = [item for item in items if _in_scope(item.project, page)]
        return _paginate(
            scoped,
            key=lambda item: (_microseconds(item.at),),
            item_id=lambda item: f"{item.kind}:{item.href}",
            descending=True,
            request=page,
            hwm=snapshot.hwm,
        )

    def search_events(self, query: str, page: PageRequest) -> Page[SearchHit]:
        """Hits on ids, paths, commands and tool names; never payload bodies."""
        snapshot = self._snapshot(page.cursor)
        needle = query.strip().casefold()
        hits = [] if not needle else _search(snapshot, needle)
        scoped = [hit for hit in hits if hit.project is None or _in_scope(hit.project, page)]
        return _paginate(
            scoped,
            key=lambda hit: (_SEARCH_ORDER[hit.kind], hit.label),
            item_id=lambda hit: hit.href,
            descending=False,
            request=page,
            hwm=snapshot.hwm,
        )

    def stream_counts(self) -> StreamCounts:
        """The badge counts of the global stream."""
        snapshot = self._snapshot()
        return StreamCounts(
            approvals_open=sum(1 for item in snapshot.approvals.values() if not item.decided),
            live_sessions=sum(1 for item in snapshot.sessions.values() if _is_running(item)),
            failed_runs_7d=sum(
                1 for run in snapshot.runs.values() if _failed_recently(run, snapshot.now)
            ),
            learnings_proposed=sum(
                1
                for learning in snapshot.learnings.values()
                if learning.status == LearningStatus.PROPOSED
            ),
        )


# Session filters and sort


def _session_matches(session: Session, wanted: SessionFilter, snapshot: _Snapshot) -> bool:
    checks = (
        _in_scope(session.project, wanted),
        wanted.repo is None or session.repo == wanted.repo,
        wanted.agent is None or session.agent == wanted.agent,
        wanted.status is None or session.status == wanted.status,
        wanted.outcome is None or session.outcome == wanted.outcome,
        wanted.run_id is None or session.run_id == wanted.run_id,
        wanted.started_from is None or session.started_at >= wanted.started_from,
        wanted.started_to is None or session.started_at <= wanted.started_to,
        wanted.tool is None or wanted.tool in session.tool_counts,
        wanted.guard_denial is None or (session.guard_denials > 0) == wanted.guard_denial,
    )
    return (
        all(checks)
        and _cost_in_range(session.cost_usd, wanted)
        and _workflow_matches(snapshot.by_session[session.id], wanted.workflow)
        and _file_matches(snapshot.by_session[session.id], wanted.file)
    )


def _cost_in_range(cost: Decimal | None, wanted: SessionFilter) -> bool:
    if wanted.cost_min is None and wanted.cost_max is None:
        return True
    if cost is None:
        return False
    above_min = wanted.cost_min is None or cost >= wanted.cost_min
    return above_min and (wanted.cost_max is None or cost <= wanted.cost_max)


def _workflow_matches(events: Sequence[StoredEvent], workflow: str | None) -> bool:
    return workflow is None or any(stored.event.workflow == workflow for stored in events)


def _file_matches(events: Sequence[StoredEvent], file: str | None) -> bool:
    return file is None or any(file in change.path for change in fold_session_files(events))


def _session_sort_key(field: str, *, descending: bool) -> Callable[[Session], SortKey]:
    if field == "cost":
        return lambda session: _money_key(session.cost_usd, descending=descending)
    if field == "last_activity_at":
        return lambda session: (_microseconds(session.last_activity_at),)
    return lambda session: (_microseconds(session.started_at),)


def _timeline(events: Sequence[StoredEvent]) -> list[TimelineEvent]:
    resolution = resolve_facts(events)
    ordered = sorted(events, key=lambda stored: (stored.event.timestamp, stored.seq))
    timeline = []
    for stored in ordered:
        event = stored.event
        latency = None
        if stored.received_at is not None:
            latency = int((stored.received_at - event.timestamp).total_seconds() * 1000)
        timeline.append(
            TimelineEvent(
                event_id=stored.event_id,
                seq=stored.seq,
                project=event.project,
                session=event.session,
                type=event.type,
                timestamp=event.timestamp,
                received_at=stored.received_at,
                latency_ms=latency,
                source=event.source,
                source_id=event.source_id,
                repo=event.repo,
                agent=event.agent,
                workflow=event.workflow,
                step=event.step,
                payload=dict(event.payload),
                fact_key=resolution.keys.get(stored.event_id),
                merged_sources=resolution.merged_sources.get(stored.event_id, ()),
                conflict=stored.event_id in resolution.conflicts,
            )
        )
    return timeline


# Runs and approvals


def _run_matches(run: WorkflowRun, wanted: RunFilter) -> bool:
    failure_stage = None if run.failure is None else run.failure.stage
    checks = (
        _in_scope(run.project, wanted),
        wanted.repo is None or run.repo == wanted.repo,
        wanted.stage is None or run.stage == wanted.stage,
        wanted.outcome != "done" or (run.stage == Stage.REPORTED and run.failure is None),
        wanted.outcome != "failed" or run.failure is not None,
        wanted.failure_stage is None or failure_stage == wanted.failure_stage,
        wanted.mode is None or run.mode == wanted.mode,
        wanted.issue is None or (run.issue is not None and run.issue.key == wanted.issue),
    )
    return all(checks)


def _approval_matches(approval: Approval, wanted: ApprovalFilter) -> bool:
    status_matches = {
        "open": not approval.decided,
        "decided": approval.decided,
        "all": True,
    }[wanted.status]
    kind_matches = wanted.kind is None or approval.kind == wanted.kind
    return _in_scope(approval.project, wanted) and kind_matches and status_matches


# Project numbers


def _is_running(session: Session) -> bool:
    return session.status != SessionStatus.ENDED


def _failed_recently(run: WorkflowRun, now: datetime) -> bool:
    return run.failure is not None and now - (run.ended_at or run.last_activity_at) <= RECENT


def _cost_between(sessions: Sequence[Session], start: datetime, end: datetime) -> Decimal | None:
    costs = [
        session.cost_usd
        for session in sessions
        if session.cost_usd is not None and start <= session.started_at < end
    ]
    return sum(costs, Decimal(0)) if costs else None


def _daily_costs(sessions: Sequence[Session], now: datetime) -> tuple[Decimal, ...]:
    days = []
    for days_ago in range(DAYS_IN_PERIOD - 1, -1, -1):
        end = now - timedelta(days=days_ago)
        days.append(_cost_between(sessions, end - timedelta(days=1), end) or Decimal(0))
    return tuple(days)


def _approval_need(approval: Approval) -> NeedsYouItem:
    return NeedsYouItem(
        kind="approval",
        verb="Review",
        context=approval.title,
        project=approval.project,
        since=approval.requested_at,
        href=f"/approvals/{approval.id}",
    )


def _failed_need(run: WorkflowRun) -> NeedsYouItem:
    issue = run.issue.key if run.issue is not None else f"Run {run.id}"
    stage = run.failure.stage.value if run.failure is not None else run.stage.value
    return NeedsYouItem(
        kind="failed",
        verb="Check failed run",
        context=f"{issue} failed at {stage}",
        project=run.project,
        since=run.ended_at or run.last_activity_at,
        href=f"/runs/{run.id}",
    )


def _learning_need(learning: Learning) -> NeedsYouItem:
    return NeedsYouItem(
        kind="learning",
        verb="Review learning",
        context=learning.text,
        project=learning.project,
        since=learning.proposed_at,
        href=f"/knowledge/learnings/{learning.id}",
    )


def _run_activity(run: WorkflowRun) -> ActivityItem:
    issue = run.issue.key if run.issue is not None else run.id
    failed = run.failure is not None
    kind: Literal["failed", "reported"] = "failed" if failed else "reported"
    text = f"{issue} failed at {run.failure.stage.value}" if run.failure else f"{issue} reported"
    return ActivityItem(
        kind=kind,
        text=text,
        project=run.project,
        at=run.ended_at or run.last_activity_at,
        href=f"/runs/{run.id}",
        event_id=None if run.failure is None else run.failure.failing_event_id,
    )


def _learning_activity(learning: Learning) -> ActivityItem:
    return ActivityItem(
        kind="learning",
        text=f"Learning {learning.status.value}: {learning.text}",
        project=learning.project,
        at=learning.decided_at or learning.proposed_at or _EPOCH,
        href=f"/knowledge/learnings/{learning.id}",
        event_id=learning.source_event_id,
    )


def _approval_activity(approval: Approval) -> ActivityItem:
    return ActivityItem(
        kind="approval",
        text=f"{approval.title}: {approval.status}",
        project=approval.project,
        at=approval.decided_at or approval.requested_at,
        href=f"/approvals/{approval.id}",
        event_id=approval.decision_event_id,
    )


# Search


def _entity_hits(snapshot: _Snapshot, needle: str) -> list[SearchHit]:
    hits = [
        SearchHit(
            kind="session",
            label=s.id,
            detail=f"{s.project} · {s.agent}",
            project=s.project,
            href=f"/sessions/{s.id}",
        )
        for s in snapshot.sessions.values()
        if needle in s.id.casefold()
    ]
    for run in snapshot.runs.values():
        issue = "" if run.issue is None else run.issue.key
        if needle in run.id.casefold() or needle in issue.casefold():
            hits.append(
                SearchHit(
                    kind="run",
                    label=run.id,
                    detail=issue or None,
                    project=run.project,
                    href=f"/runs/{run.id}",
                )
            )
    hits.extend(
        SearchHit(
            kind="approval",
            label=a.id,
            detail=a.title,
            project=a.project,
            href=f"/approvals/{a.id}",
        )
        for a in snapshot.approvals.values()
        if needle in a.id.casefold()
    )
    hits.extend(
        SearchHit(
            kind="learning",
            label=item.id,
            detail=item.text,
            project=item.project,
            href=f"/knowledge/learnings/{item.id}",
        )
        for item in snapshot.learnings.values()
        if needle in item.id.casefold()
    )
    return hits


_CALL_FIELDS: tuple[tuple[str, SearchKind], ...] = (
    ("path", "file"),
    ("command", "command"),
    ("tool", "tool"),
)


def _call_hits(snapshot: _Snapshot, needle: str) -> list[SearchHit]:
    hits: dict[str, SearchHit] = {}
    for session_id, events in snapshot.by_session.items():
        for stored in events:
            if stored.event.type != EventType.TOOL_CALL:
                continue
            for field, kind in _CALL_FIELDS:
                value = stored.event.payload.get(field)
                if not isinstance(value, str) or needle not in value.casefold():
                    continue
                tab = "?tab=files" if kind == "file" else ""
                href = f"/sessions/{session_id}{tab}#{kind}:{value}"
                hits.setdefault(
                    href,
                    SearchHit(
                        kind=kind,
                        label=value,
                        detail=session_id,
                        project=stored.event.project,
                        href=href,
                        event_id=stored.event_id,
                    ),
                )
    return list(hits.values())


def _search(snapshot: _Snapshot, needle: str) -> list[SearchHit]:
    return [*_entity_hits(snapshot, needle), *_call_hits(snapshot, needle)]
