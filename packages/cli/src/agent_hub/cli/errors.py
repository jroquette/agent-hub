"""Errors raised by the hub command itself; the command prints them, never a traceback."""

from agent_hub.core.errors import AgentHubError


class CliError(AgentHubError):
    """Base class for errors of the hub command."""


class HomeDirectoryNotFoundError(CliError):
    """No usable home directory, so the default database path cannot be built."""

    def __init__(self) -> None:
        super().__init__("cannot resolve the home directory; pass --db or set AGENT_HUB_DB")


class ChildTimedOutError(CliError):
    """A child process ran past its timeout and was killed."""

    def __init__(self, *, program: str, timeout: float) -> None:
        super().__init__(f"{program} timed out after {timeout:g} s")
