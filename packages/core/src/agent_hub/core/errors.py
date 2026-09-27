"""Root of the agent-hub exception hierarchy; each package defines its own subclasses."""


class AgentHubError(Exception):
    """Base class for every error agent-hub raises on purpose."""
