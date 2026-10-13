"""The read ports the API depends on: one method per read use case (ADR draft 0017).

``EventReadModels`` folds stored events into sessions, runs, approvals and learnings;
``HubReadModels`` reads the registered hubs' files. Routes depend only on these Protocols, so
the implementations and the routes are built and tested apart. A missing entity raises
``EntityNotFoundError``, which the API answers with a 404 problem naming the id.
"""

from typing import Protocol

from agent_hub.core.approvals.approval import Approval
from agent_hub.core.brain.brain_note import BrainNote, BrainTree
from agent_hub.core.errors import AgentHubError
from agent_hub.core.events.event import EventType
from agent_hub.core.features.feature_view import FeatureDetail, FeatureView
from agent_hub.core.features.ticket_view import FeatureTickets
from agent_hub.core.hubs.finding_view import FindingView
from agent_hub.core.hubs.registered_hub import HubView
from agent_hub.core.learnings.learning import Learning
from agent_hub.core.projects.project_views import (
    ActivityItem,
    LiveTile,
    NeedsYouItem,
    ProjectActivity,
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
    SearchHit,
    StreamCounts,
)
from agent_hub.core.readmodels.filters import (
    ApprovalFilter,
    LearningFilter,
    PageRequest,
    RunFilter,
    Scope,
    SessionFilter,
)
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.settings_view import SettingsView
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.sessions.problem import SessionProblems
from agent_hub.core.sessions.session import (
    Session,
    SessionCost,
    SessionFileChange,
    SessionSummary,
    TimelineEvent,
)


class EntityNotFoundError(AgentHubError):
    """No ``entity`` (session, run, approval, learning, project, feature, hub) has this id."""

    def __init__(self, *, entity: str, entity_id: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"no {entity} with id {entity_id!r}")


class EventReadModels(Protocol):
    """Reads folded from the event store."""

    def list_sessions(self, session_filter: SessionFilter) -> Page[Session]:
        """Sessions matching the filter, one page in its sort order."""
        ...

    def get_session(self, session_id: str) -> Session:
        """One session."""
        ...

    def session_summary(self, session_id: str) -> SessionSummary:
        """The session's summary lines (D17)."""
        ...

    def session_events(
        self, session_id: str, *, types: frozenset[EventType], page: PageRequest
    ) -> Page[TimelineEvent]:
        """The session's events in timestamp order, filtered by type (empty = all)."""
        ...

    def session_files(self, session_id: str) -> Page[SessionFileChange]:
        """The paths the session touched."""
        ...

    def session_cost(self, session_id: str) -> SessionCost:
        """The session's estimated cost per turn and in total."""
        ...

    def session_problems(self, session_id: str) -> SessionProblems:
        """The session's problems with their resolutions and the "what went wrong" lines."""
        ...

    def list_live_sessions(self, scope: Scope) -> Page[LiveTile]:
        """Live session tiles grouped waiting, live, idle, ended recently."""
        ...

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        """Workflow runs matching the filter, newest first."""
        ...

    def get_run(self, run_id: str) -> WorkflowRun:
        """One workflow run."""
        ...

    def list_approvals(self, approval_filter: ApprovalFilter) -> Page[Approval]:
        """Approvals matching the filter, oldest first."""
        ...

    def get_approval(self, approval_id: str) -> Approval:
        """One approval."""
        ...

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """Learnings matching the filter."""
        ...

    def get_learning(self, learning_id: str) -> Learning:
        """One learning."""
        ...

    def project_activity(self, project: str) -> ProjectActivity:
        """The event-derived numbers of one project (a project with no event has zeros)."""
        ...

    def needs_you(self, scope: Scope) -> Page[NeedsYouItem]:
        """What waits for a person, oldest first."""
        ...

    def activity(self, page: PageRequest) -> Page[ActivityItem]:
        """Notable events, newest first."""
        ...

    def search_events(self, query: str, page: PageRequest) -> Page[SearchHit]:
        """Hits on ids, paths, commands and tool names; never payload bodies."""
        ...

    def stream_counts(self) -> StreamCounts:
        """The badge counts of the global stream."""
        ...


class HubReadModels(Protocol):
    """Reads of the hub registry and the registered hubs' files."""

    def list_hubs(self) -> Page[HubView]:
        """Every registered hub, valid or not."""
        ...

    def register_hub(self, path: str) -> HubView:
        """Register the hub at ``path`` (the only write of Phase 2 besides removal)."""
        ...

    def remove_hub(self, hub_id: str) -> None:
        """Forget a hub; its events stay in the store."""
        ...

    def list_projects(self) -> Page[ProjectSummary]:
        """A Portfolio card per registered, valid hub."""
        ...

    def get_project(self, project: str) -> ProjectDetail:
        """The Project overview header."""
        ...

    def project_now(self, project: str) -> ProjectNow:
        """The project's ``brain/now.md``."""
        ...

    def project_repos(self, project: str) -> Page[RepoView]:
        """The project's repos."""
        ...

    def list_features(self, scope: Scope) -> Page[FeatureView]:
        """Feature folders of every scoped hub."""
        ...

    def get_feature(self, project: str, slug: str) -> FeatureDetail:
        """One feature with its acceptance criteria."""
        ...

    def feature_tickets(self, project: str, slug: str) -> FeatureTickets:
        """One feature's tickets, their planning and golden path; the only read that may call
        the tracker (ADR 0025). A tracker failure falls back to the plan, never raises."""
        ...

    def doctor_findings(self, scope: Scope) -> Page[FindingView]:
        """Doctor findings of every scoped hub (cached 15 min per hub)."""
        ...

    def settings(self) -> SettingsView:
        """The running server's settings."""
        ...

    def brain_tree(self, project: str) -> BrainTree:
        """The ``.md`` notes of the project's hub brain."""
        ...

    def brain_note(self, project: str, path: str) -> BrainNote:
        """One note of the project's hub brain; ``BrainPathError`` for a refused path,
        ``BrainNoteNotFoundError`` or ``BrainNoteTooLargeError`` when it cannot be served."""
        ...
