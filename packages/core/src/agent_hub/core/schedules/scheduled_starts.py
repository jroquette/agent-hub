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

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Final, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.schedules import EventKind
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.launch import (
    RunAccepted,
    RunTrigger,
    StartRunRequest,
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
