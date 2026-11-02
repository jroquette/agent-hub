"""What the screen reads answer (ADR 0056).

RED stub for AGH-623 (plan SHELL-1 commit 30b): the shell's view as the slice states it.
"""

from agent_hub.core.readmodels.view_types import ViewModel


class ShellProject(ViewModel):
    """A project in the shell's switcher: its name and how many of its sessions are live."""

    name: str
    live_sessions: int


class ShellView(ViewModel):
    """The app shell's facts: how many hubs are registered, every project, the features that
    need you in the scope, and whether any project has a workflow run."""

    hub_count: int
    projects: tuple[ShellProject, ...]
    features_needing_you: int
    has_workflow_runs: bool
