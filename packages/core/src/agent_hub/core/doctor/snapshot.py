"""What ``hub doctor`` knows of a hub: its config (or why it failed), and the files it looked at.

The cli fills a ``DoctorSnapshot``; rules read it and never touch the disk. Paths are relative
POSIX paths from the hub root.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry


@dataclass(frozen=True, kw_only=True, slots=True)
class PinMismatch:
    """``platform.version`` is a well-formed release other than the running ``hub``."""

    pinned: str
    running: str
    # The command that runs the pinned release; ``None`` when the pin is too long to echo.
    command: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class ConfigFailure:
    """Why ``hub.json`` cannot be used: the reader's or schema's problems, or a pin mismatch."""

    problems: tuple[ConfigProblem, ...]
    pin: PinMismatch | None


@dataclass(frozen=True, kw_only=True, slots=True)
class HubFiles:
    """The files of one tree, read without following links.

    ``entries`` holds every path looked at (listed or fixed, present ones only); ``listed`` is
    the sorted listing of the tree, empty when no rule asked for it; ``problem`` says why the
    listing could not be made.
    """

    entries: Mapping[str, TreeEntry]
    listed: tuple[str, ...]
    problem: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class DoctorSnapshot:
    """The input of every rule: the config, the running release and the hub's files."""

    config: HubConfig | ConfigFailure
    running_version: str
    hub: HubFiles

    @property
    def hub_config(self) -> HubConfig:
        """The valid config; only the config rules run on a failed one, so reading it is a bug."""
        if isinstance(self.config, ConfigFailure):
            msg = "hub.json is not valid; only config.schema and platform.version run"
            raise ValueError(msg)
        return self.config


def hub_paths(config: HubConfig) -> tuple[str, ...]:
    """The paths every run looks at by path, listed or not: the files rules read by name."""
    return (
        HUB_LOCK_PATH,
        ".claude/settings.json",
        ".claude/settings.project.json",
        ".mcp.json",
        "Makefile",
        "Makefile.project",
        "package.json",
        f"plugin/{config.project.name}/hooks/project_guard.py",
    )


def text_of(entry: TreeEntry | None) -> str | None:
    """A regular file's UTF-8 text; ``None`` when absent, a link or folder, unread or binary."""
    if not isinstance(entry, FileEntry) or entry.content is None or b"\x00" in entry.content:
        return None
    try:
        return entry.content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def lines_of(text: str) -> tuple[str, ...]:
    """The lines of a text, split on ``\\n`` only (``splitlines`` also splits on U+2028).

    A final ``\\n`` ends the last line; it does not start an empty one.
    """
    if not text:
        return ()
    return tuple(text.removesuffix("\n").split("\n"))
