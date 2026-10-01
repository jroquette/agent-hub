"""What ``hub doctor`` knows of a hub: its config (or why), lock, files, base hooks, repos.

The cli fills a ``DoctorSnapshot``; rules read it and never touch the disk. Paths are relative
POSIX paths from the hub root.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH, HubLock
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry
from agent_hub.core.json_form import JsonValue


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

    ``entries`` holds every path looked at, present ones only: the listed and fixed paths, the
    lock's paths when read, and the leftover-shaped names the reader also records (unread,
    plan E9); ``listed`` is the sorted listing of the tree, empty when no rule asked for it. The
    tree's files, the only set a rule may treat as such, are the listing plus the fixed paths
    (``hub_paths``) present in ``entries`` (plan E31); never lock paths or leftover names.
    ``problem`` says why the listing could not be made or a path read. ``paths_read`` is whether
    every path looked at by path was read: when not, an absent one may be one the read never
    reached, so no rule may call it missing; a failed listing alone leaves it true.
    """

    entries: Mapping[str, TreeEntry]
    listed: tuple[str, ...]
    problem: str | None
    paths_read: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class RepoFiles:
    """One ``repos[].dir`` of ``hub.json`` and the files of its checkout at ``../<dir>``.

    ``files`` is ``None`` when ``../<dir>`` is absent or not a folder (spec Q-9); a checkout's
    paths are relative to the checkout, as the hub's are to the hub.
    """

    dir: str
    files: HubFiles | None


@dataclass(frozen=True, kw_only=True, slots=True)
class LockAbsent:
    """No ``hub.lock`` entry in the hub folder: the hub was never adopted."""


@dataclass(frozen=True, kw_only=True, slots=True)
class LockNotRegular:
    """``hub.lock`` is a link, folder, FIFO or other non-regular file, so it was never opened."""


# What ``hub.lock`` holds: the lock, no lock, something that is no file, or its problems.
type LockState = HubLock | LockAbsent | LockNotRegular | tuple[ConfigProblem, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class DoctorSnapshot:
    """The input of every rule: the config, the running release, the hub's files and its lock.

    ``lock`` is ``None`` when it was not read: no selected rule reads it, the config failed, or
    ``hub.lock`` could not be read (the hub's files then say why, as ``hub.lock`` is a fixed path).
    ``base_hooks`` is the ``hooks`` block of the running release's managed settings, ``None``
    when no selected rule reads it or the config failed. ``repos`` holds one entry per
    ``repos[].dir``, in ``hub.json`` order, when a selected rule reads them; else it is empty.
    """

    config: HubConfig | ConfigFailure
    running_version: str
    hub: HubFiles
    lock: LockState | None
    base_hooks: Mapping[str, JsonValue] | None
    repos: tuple[RepoFiles, ...]

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
        guard_extension_path(config),
    )


def guard_extension_path(config: HubConfig) -> str:
    """The project's guard extension, which the base guard runs (hub-generator.md § Hooks)."""
    return f"plugin/{config.project.name}/hooks/project_guard.py"


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
