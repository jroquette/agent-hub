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


class WorktreeError(CliError):
    """A worktree step failed: a repo not cloned, a git call or a setup script that failed."""


class WorktreeUsageError(WorktreeError):
    """A worktree task's input is refused: its name, its branch or the repo asked for."""


class RunLogError(CliError):
    """A record or the inbox line of ``hub run`` could not be written."""

    def __init__(self, error: OSError) -> None:
        super().__init__(f"could not write the run's records: {error.strerror or error}")
