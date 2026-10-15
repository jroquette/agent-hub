"""The Session read model and the views of one session: summary, files, cost, timeline."""

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import (
    DEPRECATED_FIELD,
    ApiTimestamp,
    DerivedView,
    Money,
    ViewModel,
)


class SessionStatus(StrEnum):
    """Where a session is now (D14): waiting wins over live; ended is final until reopened."""

    LIVE = "live"
    WAITING = "waiting"
    IDLE = "idle"
    ENDED = "ended"


class Outcome(StrEnum):
    """How an ended session ended; ``None`` when no source says."""

    DONE = "done"
    STOPPED = "stopped"
    BLOCKED = "blocked"
    ERROR = "error"


class TokenUsage(ViewModel):
    """Tokens counted from transcript usage, once per message id."""

    input: int = Field(ge=0)
    output: int = Field(ge=0)
    cache_read: int = Field(ge=0)
    cache_write: int = Field(ge=0)


class SessionSegment(ViewModel):
    """One stretch of a session; a later event after an end reopens it as a new segment."""

    index: int = Field(ge=1)
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None
    end_reason: str | None
    end_inferred: bool = False


class PullRequestRef(ViewModel):
    """A pull request; GitHub is not connected in Phase 2, so sessions carry ``null``."""

    number: int
    url: str
    state: str


class SessionLabel(ViewModel):
    """What a session is about, derived on read (S1): issue, workflow, repo and branch.

    ``issue`` is ``<TEAM>-<n>`` found in ``branch`` or ``worktree`` with the hub's tracker teams,
    else ``None``, never a guess. ``workflow`` is the session's main slash command or skill
    (``/feature``); ``workflows`` lists every one in order. ``worktree`` is the folder name under
    ``.claude/worktrees/`` in the session's ``cwd``.
    """

    issue: str | None
    workflow: str | None
    workflows: tuple[str, ...]
    repo: str | None
    branch: str | None
    worktree: str | None
    derived: bool = True


type ActorKind = Literal["main", "subagent"]


class Actor(ViewModel):
    """Who acted in a session (S2): the main agent, or a subagent of a type.

    A subagent carries its ``agent_id`` and, when its start is linked to the main agent's
    Agent tool call, that call's ``description`` and ``started_by_event_id``.
    """

    kind: ActorKind
    type: str | None = None
    agent_id: str | None = None
    description: str | None = None
    started_by_event_id: EventId | None = None


class ProblemCounts(ViewModel):
    """A session's problems by owner-facing status (S4, E5); ``handled`` = recovered or
    continued by the agent."""

    needs_you: int = Field(default=0, ge=0)
    open: int = Field(default=0, ge=0)
    handled: int = Field(default=0, ge=0)
    by_you: int = Field(default=0, ge=0)


class Session(DerivedView):
    """A session folded from its events (status, counts, tokens, estimated cost).

    ``agent`` is deprecated: ``actors`` and ``label`` say who acted and what the session is about.
    ``agent_session_id`` is the agent session ``hub web`` drives it from, when there is one.
    The tile fields (``waiting_reason`` to ``sparkline_60s``) are what a Live tile shows,
    derived by the same code (D5); lists and the session read fill them, other reads leave them
    ``null``. ``sparkline_60s`` is ``null`` once the session has ended.
    """

    id: str
    project: str
    repo: str | None
    agent: str = Field(json_schema_extra=DEPRECATED_FIELD)
    parent_session_id: str | None = None
    run_id: str | None = None
    step: str | None = None
    attempt: int | None = None
    issue: str | None = None
    started_at: ApiTimestamp
    ended_at: ApiTimestamp | None
    last_activity_at: ApiTimestamp
    segments: tuple[SessionSegment, ...]
    status: SessionStatus
    outcome: Outcome | None
    end_reason: str | None
    end_inferred: bool = False
    turns: int = Field(ge=0)
    tool_counts: dict[str, int]
    files_touched: int = Field(ge=0)
    errors: int = Field(ge=0)
    guard_denials: int = Field(ge=0)
    gates: int = Field(ge=0)
    learnings_proposed: int = Field(ge=0)
    model: str | None
    tokens: TokenUsage | None
    cost_usd: Money | None
    cost_unknown_reason: str | None = None
    has_transcript: bool
    pr: PullRequestRef | None = None
    label: SessionLabel | None = None
    actors: tuple[Actor, ...] = ()
    problems: ProblemCounts = ProblemCounts()
    agent_session_id: str | None = None
    waiting_reason: str | None = None
    last_action: str | None = None
    last_tool: str | None = None
    needs_you_problem: str | None = None
    failing_notice: str | None = None
    sparkline_60s: tuple[int, ...] | None = None

    @model_validator(mode="after")
    def _no_sparkline_when_ended(self) -> Self:
        if self.status == SessionStatus.ENDED and self.sparkline_60s is not None:
            msg = "sparkline_60s must be null once the session has ended"
            raise ValueError(msg)
        return self


class SummaryLine(ViewModel):
    """One line of a session summary and the event it comes from."""

    text: str
    event_id: EventId


class SessionSummary(DerivedView):
    """3 to 5 deterministic lines (D17); a stored ``session.summary`` event wins (``stored``)."""

    session_id: str
    lines: tuple[SummaryLine, ...]
    generated_at: ApiTimestamp
    stored: bool = False


type FileOperation = Literal["read", "edited", "created", "written"]


class SessionFileChange(ViewModel):
    """A path a session touched, its operations and line counts (no content is stored)."""

    repo: str | None
    path: str
    ops: tuple[FileOperation, ...]
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    event_ids: tuple[EventId, ...]


class TurnCost(ViewModel):
    """Tokens and estimated cost of one turn."""

    turn: int = Field(ge=0)
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    cache_read: int = Field(ge=0)
    cache_write: int = Field(ge=0)
    cost_usd: Money | None


class SessionCost(DerivedView):
    """The Cost tab: per-turn series and totals, always "Estimated from transcript" (D15)."""

    session_id: str
    model: str | None
    series: tuple[TurnCost, ...]
    total_usd: Money | None
    run_total_usd: Money | None = None
    budget_usd: Money | None = None
    unknown_reason: str | None = None
    prices_as_of: date | None


class TimelineEvent(ViewModel):
    """One stored event as the timeline and Raw events show it.

    ``fact_key`` groups copies of the same fact from several sources; ``merged_sources`` lists
    them on the winner; a loser has ``conflict`` set (D16). ``latency_ms`` is ``received_at``
    minus ``timestamp`` when both exist.
    """

    event_id: EventId
    seq: int = Field(ge=1)
    project: str
    session: str
    type: EventType
    timestamp: ApiTimestamp
    received_at: ApiTimestamp | None
    latency_ms: int | None
    source: EventSource
    source_id: str
    repo: str | None
    agent: str | None
    workflow: str | None
    step: str | None
    payload: dict[str, JsonValue]
    fact_key: str | None = None
    merged_sources: tuple[EventSource, ...] = ()
    conflict: bool = False
