"""In-memory fakes of the hub ports: ``InMemoryHubRegistry`` (checked by ``HubRegistryContract``)
and ``FakeHubFileReader``, whose hubs are synthetic files kept in memory (``brain`` holds the
files under ``brain/``, ``brain_links`` the ones that play links; ``skill_files``,
``skill_links`` and ``skill_specials`` the hub-relative files, links and FIFOs under the skill
roots, checked by ``SkillSourcesContract``).
"""

import json
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.brain.brain_path import NOTE_SUFFIX, is_personal_folder
from agent_hub.core.doctor.run_rules import Selection
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles, LockAbsent, LockState
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.hubs.hub_registry import (
    BrainListing,
    HubConflictError,
    UnreadHubFile,
    to_milliseconds,
)
from agent_hub.core.hubs.registered_hub import RegisteredHub
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.skills.skill_sources import (
    DEFAULT_LIMITS,
    SkillLimits,
    SkillPathError,
    SkillSources,
    SourceFile,
    skill_relative,
)
from agent_hub.core.testing.builders import a_hub_document

MISSING = UnreadHubFile(message="cannot read: No such file or directory", is_missing=True)


def utc_now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


class InMemoryHubRegistry:
    """A ``HubRegistry`` kept in memory."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._entries: list[RegisteredHub] = []
        self._clock = clock

    def entries(self) -> tuple[RegisteredHub, ...]:
        """Every registered hub, in registration order."""
        return tuple(self._entries)

    def add(self, path: str) -> RegisteredHub:
        """Register ``path``; ``HubConflictError`` when it is registered already."""
        if any(entry.path == path for entry in self._entries):
            msg = f"hub {path!r} is registered already"
            raise HubConflictError(msg)
        entry = RegisteredHub(
            id=str(uuid.uuid7()), path=path, added_at=to_milliseconds(self._clock())
        )
        self._entries.append(entry)
        return entry

    def remove(self, hub_id: str) -> None:
        """Forget the hub with ``hub_id``."""
        kept = [entry for entry in self._entries if entry.id != hub_id]
        if len(kept) == len(self._entries):
            raise EntityNotFoundError(entity="hub", entity_id=hub_id)
        self._entries = kept


def hub_json_bytes(*, pin: str, **project: Any) -> bytes:
    """A synthetic ``hub.json`` pinned to ``pin``, with ``project`` keys overridden."""
    document = a_hub_document()
    document["platform"]["version"] = pin
    document["project"].update(project)
    return json.dumps(document).encode()


@dataclass(kw_only=True)
class FakeHub:
    """One synthetic hub's files; ``files`` are the hub-relative files the doctor sees."""

    hub_json: bytes | UnreadHubFile = MISSING
    lock: LockState | None = field(default_factory=LockAbsent)
    local: LocalConfig | tuple[ConfigProblem, ...] = field(default_factory=LocalConfig)
    files: dict[str, bytes] = field(default_factory=dict)
    # The folders directly under ``workflows/`` the doctor snapshot lists.
    folders: tuple[str, ...] = ()
    now: bytes | UnreadHubFile = MISSING
    agents_md_lines: dict[str, int] = field(default_factory=dict)
    features: tuple[FeatureFolder, ...] = ()
    mtimes: dict[str, int] = field(default_factory=dict)
    brain: dict[str, bytes] = field(default_factory=dict)
    brain_links: frozenset[str] = frozenset()
    skill_files: dict[str, bytes] = field(default_factory=dict)
    skill_links: dict[str, str] = field(default_factory=dict)
    skill_specials: frozenset[str] = frozenset()


def _listed(path: str) -> bool:
    segments = path.split("/")
    hidden = any(segment.startswith(".") for segment in segments)
    return path.endswith(NOTE_SUFFIX) and not is_personal_folder(segments[0]) and not hidden


class FakeHubFileReader:
    """A ``HubFileReader`` over ``FakeHub`` values keyed by path; ``aliases`` play links.

    ``snapshots`` counts the doctor snapshots built per hub, so a test sees the cache work;
    ``feature_reads`` records each feature read, ``("*", hub_path)`` for a listing and
    ``(slug, hub_path)`` for one folder, so a test sees how much a request read;
    ``skill_listings`` records each ``skill_sources`` call's hub and ``skill_reads`` each
    ``read_skill_file`` call as ``(hub_path, path)``, refused paths included.
    """

    def __init__(
        self, hubs: dict[str, FakeHub] | None = None, *, aliases: dict[str, str] | None = None
    ) -> None:
        self.hubs = dict(hubs or {})
        self.aliases = dict(aliases or {})
        self.snapshots: dict[str, int] = {}
        self.feature_reads: list[tuple[str, str]] = []
        self.skill_listings: list[str] = []
        self.skill_reads: list[tuple[str, str]] = []

    def resolve(self, path: str) -> str:
        """The aliased path, or the path itself."""
        return self.aliases.get(path, path)

    def read_hub_json(self, hub_path: str) -> bytes | UnreadHubFile:
        """The hub's ``hub.json`` bytes, or ``MISSING``."""
        return self._hub(hub_path).hub_json

    def read_lock(self, hub_path: str) -> LockState | None:
        """The hub's lock state."""
        return self._hub(hub_path).lock

    def read_local(self, hub_path: str) -> LocalConfig | tuple[ConfigProblem, ...]:
        """The hub's local config."""
        return self._hub(hub_path).local

    def doctor_snapshot(
        self,
        hub_path: str,
        *,
        config: HubConfig,
        running_version: str,
        selection: Selection,
        local: LocalConfig | tuple[ConfigProblem, ...],
    ) -> DoctorSnapshot:
        """A snapshot of the hub's ``files``, every one listed; no repo checkout, no hooks."""
        del selection
        hub = self._hub(hub_path)
        self.snapshots[hub_path] = self.snapshots.get(hub_path, 0) + 1
        entries = {
            path: FileEntry(executable=False, content=content)
            for path, content in sorted(hub.files.items())
        }
        return DoctorSnapshot(
            config=config,
            running_version=running_version,
            hub=HubFiles(entries=entries, listed=tuple(entries), problem=None, paths_read=True),
            lock=hub.lock,
            base_hooks=None,
            repos=(),
            local=local,
            workflow_folders=hub.folders,
        )

    def modified_times(self, hub_path: str, paths: Sequence[str]) -> tuple[int | None, ...]:
        """The hub's recorded times of ``paths``."""
        mtimes = self._hub(hub_path).mtimes
        return tuple(mtimes.get(path) for path in paths)

    def read_now(self, hub_path: str) -> bytes | UnreadHubFile:
        """The hub's ``brain/now.md`` bytes, or ``MISSING``."""
        return self._hub(hub_path).now

    def agents_md_lines(self, hub_path: str, repo_dir: str) -> int | None:
        """The recorded line count of the repo's ``AGENTS.md``."""
        return self._hub(hub_path).agents_md_lines.get(repo_dir)

    def feature_folders(self, hub_path: str) -> tuple[FeatureFolder, ...]:
        """The hub's feature folders."""
        self.feature_reads.append(("*", hub_path))
        return self._hub(hub_path).features

    def feature_folder(self, hub_path: str, slug: str) -> FeatureFolder | None:
        """The hub's feature folder ``slug``, or None."""
        self.feature_reads.append((slug, hub_path))
        return next((f for f in self._hub(hub_path).features if f.slug == slug), None)

    def brain_tree(self, hub_path: str) -> BrainListing:
        """The hub's ``.md`` brain files by path, without ``auto/``, hidden names or links."""
        hub = self._hub(hub_path)
        entries = tuple(
            BrainEntry(path=path, size=len(content))
            for path, content in sorted(hub.brain.items())
            if _listed(path) and path not in hub.brain_links
        )
        return BrainListing(entries=entries)

    def brain_folders(self, hub_path: str) -> tuple[str, ...]:
        """The top-level folders of the hub's listed brain files (a folder holding a link only
        is left out)."""
        hub = self._hub(hub_path)
        folders = {
            path.split("/", 1)[0]
            for path in hub.brain
            if "/" in path and _listed(path) and path not in hub.brain_links
        }
        return tuple(sorted(folders))

    def read_brain_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The brain file's bytes, or why not (missing, a link, over ``max_bytes``)."""
        hub = self._hub(hub_path)
        if path in hub.brain_links:
            return UnreadHubFile(
                message="cannot read: a link", is_missing=False, kind="not_regular"
            )
        content = hub.brain.get(path)
        if content is None:
            return UnreadHubFile(message=MISSING.message, is_missing=True, kind="missing")
        if len(content) > max_bytes:
            message = f"cannot read: over {max_bytes} bytes"
            return UnreadHubFile(message=message, is_missing=False, kind="too_large")
        return content

    def brain_file_size(self, hub_path: str, path: str) -> int | None:
        """The brain file's size; None when absent or a link."""
        hub = self._hub(hub_path)
        content = hub.brain.get(path)
        return None if content is None or path in hub.brain_links else len(content)

    def skill_sources(self, hub_path: str, *, limits: SkillLimits = DEFAULT_LIMITS) -> SkillSources:
        """The hub's skill files, links and FIFOs under the roots, in path order, within
        ``limits`` (folders per kind, files per skill, names examined); a link is never
        followed, so nothing under a linked path is listed."""
        self.skill_listings.append(hub_path)
        return _skill_listing(self._hub(hub_path), limits)

    def read_skill_file(self, hub_path: str, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
        """The skill file's bytes, or why not: a refused path or an absent file ``missing``, a
        link or FIFO (or a path under a link) ``not_regular``, over ``max_bytes`` ``too_large``."""
        self.skill_reads.append((hub_path, path))
        hub = self._hub(hub_path)
        try:
            skill_relative(path)
        except SkillPathError:
            return UnreadHubFile(message=MISSING.message, is_missing=True, kind="missing")
        if path in hub.skill_specials or _under_link(path, hub.skill_links):
            return UnreadHubFile(
                message="cannot read: not a regular file", is_missing=False, kind="not_regular"
            )
        content = hub.skill_files.get(path)
        if content is None:
            return UnreadHubFile(message=MISSING.message, is_missing=True, kind="missing")
        if len(content) > max_bytes:
            message = f"cannot read: over {max_bytes} bytes"
            return UnreadHubFile(message=message, is_missing=False, kind="too_large")
        return content

    def _hub(self, hub_path: str) -> FakeHub:
        return self.hubs.get(hub_path) or FakeHub()


def _under_link(path: str, links: dict[str, str]) -> bool:
    """Whether ``path`` is a link or lies under a linked folder."""
    return any(path == link or path.startswith(f"{link}/") for link in links)


def _skill_entries(hub: FakeHub) -> Iterator[SourceFile]:
    for path, content in hub.skill_files.items():
        mtime = hub.mtimes.get(path, 0)
        yield SourceFile(path=path, size=len(content), mtime_ns=mtime, regular=True)
    for path, target in hub.skill_links.items():
        mtime = hub.mtimes.get(path, 0)
        yield SourceFile(
            path=path, size=len(target), mtime_ns=mtime, regular=False, link_target=target
        )
    for path in hub.skill_specials:
        yield SourceFile(path=path, size=0, mtime_ns=hub.mtimes.get(path, 0), regular=False)


def _listed_skill_path(path: str) -> bool:
    try:
        skill_relative(path)
    except SkillPathError:
        return False
    return True


def _item_key(path: str) -> tuple[str, str] | None:
    """The skill folder or agent file an entry belongs to, by kind; None for single files."""
    segments = path.split("/")
    folder_index = 1 if segments[0] == ".claude" else 2
    if len(segments) <= folder_index + 1 or segments[folder_index] == "hooks":
        return None
    return segments[folder_index], "/".join(segments[: folder_index + 2])


def _skill_listing(hub: FakeHub, limits: SkillLimits) -> SkillSources:
    candidates = sorted(_skill_entries(hub), key=lambda entry: entry.path)
    kept: list[SourceFile] = []
    items: dict[str, set[str]] = {}
    files_per_item: dict[str, int] = {}
    skipped = 0
    for examined, entry in enumerate(candidates):
        if examined >= limits.names_examined:
            return SkillSources(files=tuple(kept), truncated=True, skipped=skipped)
        listed = _listed_skill_path(entry.path) and not _inside_link(entry.path, hub.skill_links)
        if not listed:
            continue
        key = _item_key(entry.path)
        if key is not None:
            kind, item = key
            seen = items.setdefault(kind, set())
            if item not in seen and len(seen) >= limits.items_per_kind:
                skipped += 1
                continue
            seen.add(item)
            files_per_item[item] = files_per_item.get(item, 0) + 1
            if files_per_item[item] > limits.files_per_skill + 1:
                skipped += 1
                continue
        kept.append(entry)
    return SkillSources(files=tuple(kept), truncated=skipped > 0, skipped=skipped)


def _inside_link(path: str, links: dict[str, str]) -> bool:
    """Whether ``path`` lies under a linked folder (the link itself is listed)."""
    return any(path.startswith(f"{link}/") for link in links)
