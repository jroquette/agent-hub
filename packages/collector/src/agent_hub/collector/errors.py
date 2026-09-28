"""Errors raised by the collector; source-specific failures are translated into these."""

from agent_hub.core.errors import AgentHubError


class CollectorError(AgentHubError):
    """Base class for collector errors."""


class InputNotFoundError(CollectorError):
    """The input file does not exist."""


class InputUnreadableError(CollectorError):
    """The input exists but cannot be read as UTF-8 text (a directory, no permission, bad bytes)."""
