"""Errors raised by the storage adapter; external database errors are translated into these."""

from agent_hub.core.errors import AgentHubError


class StorageError(AgentHubError):
    """Base class for storage adapter errors."""


class MigrationError(StorageError):
    """The database could not be upgraded to the latest schema."""


class DatabaseAccessError(StorageError):
    """The event database could not be opened, read or written."""


def describe_database_error(error: Exception) -> str:
    """What went wrong, on one line, without the SQL statement or its bound parameters.

    SQLAlchemy's own message spans lines and quotes the statement and every parameter (event
    payloads included); the driver's error it wraps (``orig``) says what failed and no more.
    """
    cause = getattr(error, "orig", None) or error
    return " ".join(str(cause).split())
