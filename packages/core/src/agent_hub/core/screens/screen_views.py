"""What the screen reads answer (ADR 0056)."""

from pydantic import Field

from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.hub_config.config_view import HubConfigView
from agent_hub.core.hubs.finding_view import DoctorFindings
from agent_hub.core.projects.project_views import (
    ActivityItem,
    NeedsYouItem,
    ProjectDetail,
    ProjectNow,
    ProjectSummary,
    RepoView,
)
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.runs.workflow_run import WorkflowRun
from agent_hub.core.sessions.session import Session


class ShellProject(ViewModel):
    """A project in the shell's switcher: its name and how many of its sessions are live."""

    name: str
    live_sessions: int = Field(ge=0)


class ShellView(ViewModel):
    """The app shell's facts: how many hubs are registered, every project, the features that
    need you in the scope, and whether any project has a workflow run."""

    hub_count: int = Field(ge=0)
    projects: tuple[ShellProject, ...]
    features_needing_you: int = Field(ge=0)
    has_workflow_runs: bool


class PortfolioView(ViewModel):
    """Home's first view: every project's card, what needs you in the scope and the scope's
    newest activity page, each as its resource route answers it."""

    projects: Page[ProjectSummary]
    needs_you: Page[NeedsYouItem]
    activity: Page[ActivityItem]


class ProjectOverviewView(ViewModel):
    """The Project overview's first view: each resource part as its route answers it for the
    project (``runs`` its first 200, ``projects`` every card), and ``recent_sessions``, the
    project's 200 newest sessions narrowed to those of issues with a session active in the last
    7 days, newest first; ``has_sessions`` says whether those 200 held any session."""

    project: ProjectDetail
    findings: DoctorFindings
    projects: Page[ProjectSummary]
    needs_you: Page[NeedsYouItem]
    runs: Page[WorkflowRun]
    now: ProjectNow
    features: Page[FeatureView]
    repos: Page[RepoView]
    config: HubConfigView
    recent_sessions: Page[Session]
    has_sessions: bool
