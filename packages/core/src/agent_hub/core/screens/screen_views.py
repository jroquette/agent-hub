"""What the screen reads answer (ADR 0056)."""

from pydantic import Field

from agent_hub.core.projects.project_views import ActivityItem, NeedsYouItem, ProjectSummary
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.view_types import ViewModel


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
