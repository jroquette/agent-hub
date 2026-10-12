"""The hub git adapter's own errors; a failed change request raises core's port errors."""

from agent_hub.core.errors import AgentHubError


class HubGitError(AgentHubError):
    """Base of the hub git adapter's errors (a tool missing, a runner misused)."""
