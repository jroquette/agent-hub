"""Errors raised by the storage adapter; external database errors are translated into these."""

from agent_hub.core.errors import AgentHubError


class StorageError(AgentHubError):
    """Base class for storage adapter errors."""
