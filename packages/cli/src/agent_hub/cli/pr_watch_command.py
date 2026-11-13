"""``hub pr-watch``: reads one pull request until it changes and prints one JSON line (ADR 0063).

A placeholder: it holds the names the command is built from, and each one raises
``NotImplementedError`` until the watch is written.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.workflow_runs import SystemClock
from agent_hub.core.workflows.ports import Clock

# ``run_child`` and ``SystemClock`` are what the command will run ``gh`` and wait with.
__all__ = [
    "SystemClock",
    "WatchEnd",
    "WatchRequest",
    "parse_since",
    "pr_watch",
    "run_child",
    "watch",
]


class WatchRequest:
    """One watch: the pull request, when its loop started, the interval and the window."""

    def __init__(self, **fields: object) -> None:
        raise NotImplementedError


class WatchEnd:
    """How a watch ended: its event, its exit code and the JSON line to print."""

    def __init__(self, **fields: object) -> None:
        raise NotImplementedError


def watch(
    request: WatchRequest, *, gh: Callable[[Sequence[str]], ChildResult], clock: Clock
) -> WatchEnd:
    """Read the pull request until it changes, the window ends or the total limit passes."""
    raise NotImplementedError


def parse_since(text: str) -> datetime | None:
    """The instant ``text`` names (UTC when it has no offset), or None when it is no ISO time."""
    raise NotImplementedError


def pr_watch() -> None:
    """Read one pull request until it changes, with GET calls only; print one JSON line."""
    raise NotImplementedError
