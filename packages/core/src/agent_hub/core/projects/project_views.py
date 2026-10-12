"""Project views: Portfolio cards, Project overview, Now, repos, Needs you, activity, search,
live tiles and the global stream's counts."""

from typing import Literal

from pydantic import Field

from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import (
    DEPRECATED_FIELD,
    ApiTimestamp,
    DerivedView,
    Money,
    ViewModel,
)
from agent_hub.core.runner.run_record import Stage
from agent_hub.core.sessions.session import (
    Actor,
    Outcome,
    ProblemCounts,
    SessionLabel,
    SessionStatus,
)

type HubHealth = Literal["ok", "warning", "error"]
type LockState = Literal["in_sync", "drift", "sync_pending", "not_adopted"]


class ProjectActivity(DerivedView):
    """The event-derived numbers of one project (``EventReadModels.project_activity``)."""

    project: str
    live_sessions: int = Field(ge=0)
    runs_in_flight_by_stage: dict[Stage, int]
    failed_runs_7d: int = Field(ge=0)
    cost_period: Money | None
    cost_previous_period: Money | None
    cost_daily: tuple[Money, ...] = ()
    last_activity_at: ApiTimestamp | None


class ProjectSummary(DerivedView):
    """A Portfolio card: hub config plus the project's activity; PRs and issues need sources
    not connected in Phase 2 (``null``)."""

    name: str
    hub_id: str
    hub_repo: str
    tracker_teams: tuple[str, ...]
    platform_version: str
    lock_version: str | None
    lock_state: LockState | None
    repos: tuple[str, ...]
    hub_health: HubHealth | None
    live_sessions: int = Field(ge=0)
    runs_in_flight_by_stage: dict[Stage, int]
    failed_runs_7d: int = Field(ge=0)
    cost_period: Money | None
    cost_previous_period: Money | None
    cost_daily: tuple[Money, ...] = ()
    open_prs: int | None = None
    ready_issues: int | None = None


class TrackerView(ViewModel):
    """The project's tracker settings from ``hub.json``."""

    kind: str
    teams: tuple[str, ...]
    ready_label: str | None
    failed_label: str | None


class ProjectDetail(ViewModel):
    """The Project overview header."""

    name: str
    hub_id: str
    hub_path: str
    hub_repo: str
    tracker: TrackerView
    default_branch: str | None
    branch_prefix: str | None
    platform_version: str
    lock_version: str | None
    lock_state: LockState | None
    modules: tuple[str, ...]
    warnings: tuple[str, ...] = ()


class NowItem(ViewModel):
    """One line of ``brain/now.md``."""

    text: str
    last_verified: str | None = None
    provenance: str | None = None


class ProjectNow(ViewModel):
    """``brain/now.md`` split into its sections; ``problem`` when it cannot be read."""

    project: str
    focus: tuple[NowItem, ...]
    next: tuple[NowItem, ...]
    watch: tuple[NowItem, ...]
    source_path: str | None
    problem: str | None = None


class RepoView(DerivedView):
    """A repo of the project as ``hub.json`` and its checkout describe it."""

    name: str
    dir: str
    github: str
    role: str | None
    default_branch: str | None
    check_fast: str
    check: str
    agents_md_present: bool
    agents_md_lines: int | None
    open_prs: int | None = None


type NeedsYouKind = Literal["approval", "failed", "waiting", "blocked", "doctor", "learning"]


class NeedsYouItem(ViewModel):
    """A verb-first line of the Needs you list."""

    kind: NeedsYouKind
    verb: str
    context: str
    project: str
    since: ApiTimestamp | None
    href: str


type ActivityKind = Literal["reported", "failed", "learning", "doctor", "approval"]


class ActivityItem(ViewModel):
    """A notable event in the activity feed."""

    kind: ActivityKind
    text: str
    project: str
    at: ApiTimestamp
    href: str | None
    event_id: EventId | None = None


type SearchKind = Literal[
    "session", "run", "approval", "learning", "feature", "file", "command", "tool"
]


class SearchHit(ViewModel):
    """A search result over ids, paths, commands and tool names; never payload bodies."""

    kind: SearchKind
    label: str
    detail: str | None
    project: str | None
    href: str
    event_id: EventId | None = None


type TileGroup = Literal["waiting", "live", "idle", "ended_recently"]


class LiveTile(DerivedView):
    """A session tile of the Live sessions screen.

    ``agent`` is deprecated (``label`` and ``actors``); ``needs_you_problem`` is the owner-facing
    line of the first problem that needs the owner ("Needs you: <kind> in <where>").
    """

    id: str
    project: str
    repo: str | None
    agent: str = Field(json_schema_extra=DEPRECATED_FIELD)
    is_subagent: bool = False
    status: SessionStatus
    group: TileGroup
    outcome: Outcome | None = None
    waiting_reason: str | None = None
    last_action: str | None
    last_tool: str | None
    last_activity_at: ApiTimestamp
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None = None
    run_id: str | None = None
    step: str | None = None
    attempt: int | None = None
    issue: str | None = None
    turns: int = Field(ge=0)
    tokens_total: int = Field(ge=0)
    files_touched: int = Field(ge=0)
    errors: int = Field(ge=0)
    guard_denials: int = Field(ge=0)
    cost_usd: Money | None
    budget_usd: Money | None = None
    failing_notice: str | None = None
    sparkline_60s: tuple[int, ...] = ()
    label: SessionLabel | None = None
    actors: tuple[Actor, ...] = ()
    problems: ProblemCounts = ProblemCounts()
    needs_you_problem: str | None = None


class StreamCounts(ViewModel):
    """The badge counts the global stream sends as ``counts``."""

    approvals_open: int = Field(ge=0)
    live_sessions: int = Field(ge=0)
    failed_runs_7d: int = Field(ge=0)
    learnings_proposed: int = Field(ge=0)
    doctor_errors: int | None = None
    ready_issues: int | None = None
