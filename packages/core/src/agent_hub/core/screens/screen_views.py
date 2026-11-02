"""What the screen reads answer (ADR 0056)."""

from pydantic import Field

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
