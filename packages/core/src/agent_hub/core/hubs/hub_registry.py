"""The hub registry port (D18) and the hub file reader the control plane reads hubs through.

``HubRegistry`` keeps the registered hubs: an id (UUIDv7) minted at registration, the hub's
path and when it was added; a path is registered once. ``HubFileReader`` reads one hub's files
(``hub.json``, ``hub.lock``, ``hub.local.json``, ``brain/now.md``, feature folders, brain notes,
skill sources, repo checkouts) and builds its doctor snapshot; the generator implements it,
core decides what the files mean. A registry that cannot be read or written raises
``HubRegistryError``; a request the registry or a use case refuses raises
``HubConflictError`` (already registered, same project) or ``HubInvalidError`` (no or invalid
``hub.json``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.doctor.run_rules import Selection
from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockState
from agent_hub.core.errors import AgentHubError
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.registered_hub import RegisteredHub, ValidationProblem
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, SkillLimits, SkillSources

# The most hubs a registry holds.
MAX_HUBS = 100


def to_milliseconds(moment: datetime) -> datetime:
    """``moment`` cut to whole milliseconds, the precision the registry and the API keep."""
    return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


class HubRegistryError(AgentHubError):
    """The registry file cannot be read or written, or is over its bounds."""


class HubConflictError(AgentHubError):
    """The hub is registered already, or another registered hub has its project name."""


class HubInvalidError(AgentHubError):
    """The path holds no usable ``hub.json``: ``title`` says which, ``problems`` where."""

    def __init__(self, title: str, *, problems: tuple[ValidationProblem, ...] = ()) -> None:
        self.title = title
        self.problems = problems
        super().__init__(title)


type UnreadKind = Literal["missing", "not_regular", "too_large", "unreadable"]


@dataclass(frozen=True, kw_only=True, slots=True)
class UnreadHubFile:
    """Why a hub file could not be read (one line), and whether it was absent.

    ``kind`` is set by the brain reads (a link or folder is ``not_regular``, a note over the
    cap ``too_large``); the older reads leave it None and say only ``is_missing``.
    """

    message: str
    is_missing: bool
    kind: UnreadKind | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class BrainListing:
    """The ``.md`` notes under a hub's ``brain/``, bounded; ``truncated`` when a cap stopped the
    walk, ``skipped`` the entries left out (unreadable folders, past a cap)."""

    entries: tuple[BrainEntry, ...]
    truncated: bool = False
    skipped: int = 0


class HubRegistry(Protocol):
    """The registered hubs, kept across restarts."""

    def entries(self) -> tuple[RegisteredHub, ...]:
        """Every registered hub, in registration order."""
        ...

    def add(self, path: str) -> RegisteredHub:
        """Register ``path`` with a new UUIDv7 id; ``HubConflictError`` when it is registered."""
        ...

    def remove(self, hub_id: str) -> None:
        """Forget the hub; ``EntityNotFoundError`` (entity ``hub``) when no hub has the id."""
        ...


class HubFileReader(Protocol):
    """Reads one hub's files; ``hub_path`` is a path ``resolve`` returned."""

    def resolve(self, path: str) -> str:
        """The absolute real path of ``path`` (links resolved once)."""
        ...

    def read_hub_json(self, hub_path: str) -> bytes | UnreadHubFile:
        """The bytes of ``hub.json`` as read, or why not."""
        ...

    def read_lock(self, hub_path: str) -> LockState | None:
        """``hub.lock`` as found (never through a link); None when it cannot be read."""
        ...

    def read_local(self, hub_path: str) -> LocalConfig | tuple[ConfigProblem, ...]:
        """The hub's ``hub.local.json``, ``LocalConfig()`` when absent, or its problems."""
        ...

    def doctor_snapshot(
        self,
        hub_path: str,
        *,
        config: HubConfig,
        running_version: str,
        selection: Selection,
        local: LocalConfig | tuple[ConfigProblem, ...],
    ) -> DoctorSnapshot:
        """What the selected doctor rules read of the hub, as ``hub doctor`` reads it."""
        ...

    def modified_times(self, hub_path: str, paths: Sequence[str]) -> tuple[int | None, ...]:
        """The modification time (ns) of each hub-relative path, None when absent."""
        ...

    def read_now(self, hub_path: str) -> bytes | UnreadHubFile:
        """The bytes of ``brain/now.md``, or why not."""
        ...

    def agents_md_lines(self, hub_path: str, repo_dir: str) -> int | None:
        """The line count of ``../<repo_dir>/AGENTS.md``; None when absent or unreadable."""
        ...

    def feature_folders(self, hub_path: str) -> tuple[FeatureFolder, ...]:
        """The folders under ``brain/features/``, bounded, no link followed."""
        ...

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        """The one folder ``brain/features/<slug>/``, read as ``feature_folders`` reads it and
        nothing else; None when there is no such folder (absent, hidden, a link)."""
        ...

    def brain_tree(self, hub_path: str) -> BrainListing:
        """The ``.md`` notes under ``brain/`` (no ``auto/``, no hidden name, no link followed)."""
        ...

    def brain_folders(self, hub_path: str) -> tuple[str, ...]:
        """The folders directly under ``brain/`` by name (no ``auto/``, no hidden name, no
        link), bounded: what a learning's accept dialog offers without walking the brain."""
        ...

    def read_brain_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The bytes of ``brain/<path>`` (a path ``brain_relative`` accepted), or why not: no
        link followed anywhere on the way, a regular file of at most ``max_bytes``."""
        ...

    def brain_file_size(self, hub_path: str, path: str) -> int | None:
        """The size of the regular file ``brain/<path>``; None when absent, a link or unreadable."""
        ...

    def skill_sources(self, hub_path: str, *, limits: SkillLimits = DEFAULT_LIMITS) -> SkillSources:
        """Every entry under the hub's skill roots (``skill_relative``), stat-only, in path
        order, within ``limits``: no file opened, no link followed (its target text only)."""
        ...

    def read_skill_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The bytes of the hub-relative ``path``, or why not: a path ``skill_relative`` refuses
        reads ``missing`` without any read; a link or special file is ``not_regular`` (never
        opened through, never blocking); over ``max_bytes`` is ``too_large``."""
        ...
