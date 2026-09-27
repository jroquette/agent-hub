"""Errors raised by the collector; source-specific failures are translated into these."""

from agent_hub.core.errors import AgentHubError


class CollectorError(AgentHubError):
    """Base class for collector errors."""
