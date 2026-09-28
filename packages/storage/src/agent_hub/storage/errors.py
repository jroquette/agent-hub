"""Errors raised by the storage adapter; external database errors are translated into these."""

from agent_hub.core.errors import AgentHubError


class StorageError(AgentHubError):
    """Base class for storage adapter errors."""


class MigrationError(StorageError):
    """The database could not be upgraded to the latest schema."""


class DatabaseAccessError(StorageError):
    """The event database could not be opened, read or written."""
