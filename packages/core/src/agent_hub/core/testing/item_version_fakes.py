"""``InMemoryItemVersionStore``: the ``ItemVersionStore`` port over a dictionary;
``FakeHubItemWriter``: the ``HubItemWriter`` port over ``FakeHub`` values (``skill_files``,
``skill_links``, ``skill_specials``, ``executable``), with ``read_only`` hubs and ``fail_on``
units for fault injection; ``InMemoryWriterTree``: the ``writer_tree`` fixture of the fake."""

import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from agent_hub.core.hub_files.tree_snapshot import is_leftover_name
from agent_hub.core.item_versions.hub_item_writer import (
    HubItemWriteError,
    HubItemWriter,
    ItemWriteRefusedError,
    check_version_names,
    checked_unit_parts,
    plain_parts,
    script_parts,
)
from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    ItemVersionMeta,
    NewItemVersion,
    UnitKind,
)
from agent_hub.core.item_versions.unit_content import UnitContent
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError
from agent_hub.core.testing.hub_fakes import FakeHub

type _UnitKey = tuple[str, str]

_NOT_FOLDER: Final = "Not a directory"


class InMemoryItemVersionStore:
    """Each unit's versions in ``seq`` order, behind one lock; behaves as
    ``ItemVersionStoreContract`` says."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._units: dict[_UnitKey, list[ItemVersion]] = {}

    def append(self, version: NewItemVersion) -> ItemVersion:
        """Store ``version`` when its ``seq`` is the unit's next one, minting a UUIDv7 id."""
        key = (version.project, version.unit_path)
        with self._lock:
            versions = self._units.setdefault(key, [])
            expected = len(versions) + 1
            if version.seq != expected:
                raise ItemVersionSequenceError(
                    version.project, version.unit_path, expected=expected, got=version.seq
                )
            stored = ItemVersion.model_validate(version.model_dump() | {"id": str(uuid.uuid7())})
            versions.append(stored)
            return stored

    def last(self, project: str, unit_path: str) -> ItemVersionMeta | None:
        """The unit's newest version, or None."""
        with self._lock:
            versions = self._units.get((project, unit_path))
            return versions[-1].meta() if versions else None

    def page(
        self, project: str, unit_path: str, *, limit: int = 50, before_seq: int | None = None
    ) -> tuple[ItemVersionMeta, ...]:
        """The unit's versions newest first, below ``before_seq`` when given."""
        with self._lock:
            versions = list(self._units.get((project, unit_path), ()))
        below = [v for v in reversed(versions) if before_seq is None or v.seq < before_seq]
        return tuple(version.meta() for version in below[:limit])

    def get(self, project: str, unit_path: str, version_id: str) -> ItemVersion | None:
        """The version ``version_id`` of that unit, or None."""
        with self._lock:
            versions = list(self._units.get((project, unit_path), ()))
        return next((version for version in versions if version.id == version_id), None)


class FakeHubItemWriter:
    """A ``HubItemWriter`` over ``hubs`` (shared with a ``FakeHubFileReader``, so a write is read
    back); behaves as ``HubItemWriterContract`` says. A hub in ``read_only`` refuses every write
    with ``hub_read_only``; a unit or file path in ``fail_on`` raises ``HubItemWriteError`` and
    leaves the hub as it was (a write failing midway). ``writes`` records each applied write as
    ``(hub_path, path)``."""

    def __init__(
        self,
        hubs: dict[str, FakeHub] | None = None,
        *,
        read_only: set[str] | None = None,
        fail_on: set[str] | None = None,
    ) -> None:
        self.hubs = hubs if hubs is not None else {}
        self.read_only = read_only if read_only is not None else set()
        self.fail_on = fail_on if fail_on is not None else set()
        self.writes: list[tuple[str, str]] = []

    def is_writable(self, hub_path: str, unit_paths: Sequence[str] = ()) -> bool:
        """False for a hub in ``read_only``."""
        for path in unit_paths:
            plain_parts(path)
        return hub_path not in self.read_only

    def check_targets(self, hub_path: str, unit_paths: Sequence[str]) -> None:
        """Refuse a path one of whose components is in ``skill_links``."""
        hub = self._hub(hub_path)
        for path in unit_paths:
            parts = plain_parts(path)
            for depth in range(1, len(parts) + 1):
                if "/".join(parts[:depth]) in hub.skill_links:
                    raise ItemWriteRefusedError("link_in_path")

    def write_unit(
        self, hub_path: str, unit_path: str, content: UnitContent, *, kind: UnitKind
    ) -> None:
        """Make the unit equal to ``content``, keeping a folder's hidden entries."""
        parts = checked_unit_parts(unit_path, kind)
        if kind is not UnitKind.SKILL and [file.path for file in content.files] != [parts[-1]]:
            msg = "a file unit holds one file named after it"
            raise ValueError(msg)
        if kind is UnitKind.SKILL:
            check_version_names(content)
        hub = self._writable(hub_path, unit_path)
        if kind is not UnitKind.SKILL:
            _put(hub, unit_path, content.files[0].content, executable=content.files[0].executable)
        else:
            below = f"{unit_path}/"
            carried = [p for p in _under(hub, below) if _carried(p.removeprefix(below))]
            _check_folder_write(hub, unit_path, content, carried=carried)
            for path in _under(hub, below):
                if path not in carried:
                    _drop(hub, path)
            for file in content.files:
                _put(hub, below + file.path, file.content, executable=file.executable)
        self.writes.append((hub_path, unit_path))

    def write_file(
        self, hub_path: str, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        """Put the one hook script ``path``."""
        script_parts(path)
        hub = self._writable(hub_path, path)
        _put(hub, path, content, executable=executable)
        self.writes.append((hub_path, path))

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        """Drop the unit's file, or everything under its folder."""
        checked_unit_parts(unit_path, kind)
        hub = self._writable(hub_path, unit_path)
        paths = _under(hub, f"{unit_path}/") if kind is UnitKind.SKILL else [unit_path]
        for path in paths:
            _drop(hub, path)
        self.writes.append((hub_path, unit_path))

    def _writable(self, hub_path: str, path: str) -> FakeHub:
        if hub_path in self.read_only:
            raise ItemWriteRefusedError("hub_read_only")
        self.check_targets(hub_path, [path])
        if path in self.fail_on:
            raise HubItemWriteError
        return self._hub(hub_path)

    def _hub(self, hub_path: str) -> FakeHub:
        return self.hubs.setdefault(hub_path, FakeHub())


def _check_folder_write(
    hub: FakeHub, unit_path: str, content: UnitContent, *, carried: list[str]
) -> None:
    """Fail as the disk does, before anything changes: the skill path is no folder, or a
    version file sits where a carried hidden entry's folder is."""
    if unit_path in hub.skill_files or unit_path in hub.skill_specials:
        raise HubItemWriteError(_NOT_FOLDER)
    below = f"{unit_path}/"
    written = {below + file.path for file in content.files}
    if any(path.startswith(f"{file}/") for path in carried for file in written):
        raise HubItemWriteError(_NOT_FOLDER)


def _under(hub: FakeHub, below: str) -> list[str]:
    paths = {*hub.skill_files, *hub.skill_links, *hub.skill_specials}
    return sorted(path for path in paths if path.startswith(below))


def _carried(relative: str) -> bool:
    """Whether a folder write keeps ``relative``: its first hidden segment is not a temp
    leftover (a hidden folder is kept whole)."""
    for segment in relative.split("/"):
        if segment.startswith("."):
            return not is_leftover_name(segment)
    return False


def _drop(hub: FakeHub, path: str) -> None:
    hub.skill_files.pop(path, None)
    hub.skill_links.pop(path, None)
    hub.skill_specials = hub.skill_specials - {path}
    hub.executable = hub.executable - {path}


def _put(hub: FakeHub, path: str, content: bytes, *, executable: bool) -> None:
    _drop(hub, path)
    hub.skill_files[path] = content
    if executable:
        hub.executable = hub.executable | {path}


@dataclass
class InMemoryWriterTree:
    """The ``writer_tree`` fixture of the fake: a ``FakeHub`` at ``hub_path`` written by
    ``FakeHubItemWriter``."""

    hub_path: str = "/hubs/demo-hub"
    hub: FakeHub = field(default_factory=FakeHub)
    fake: FakeHubItemWriter = field(init=False)

    def __post_init__(self) -> None:
        self.fake = FakeHubItemWriter({self.hub_path: self.hub})

    @property
    def writer(self) -> HubItemWriter:
        """The writer under test."""
        return self.fake

    def write(self, path: str, content: bytes) -> None:
        """Add a regular file."""
        self.hub.skill_files[path] = content

    def link(self, path: str, target: str) -> None:
        """Add a link to ``target``."""
        self.hub.skill_links[path] = target

    def make_executable(self, path: str) -> None:
        """Set the file's executable bit."""
        self.hub.executable = self.hub.executable | {path}

    def make_read_only(self) -> None:
        """Refuse every write to the hub."""
        self.fake.read_only.add(self.hub_path)

    def files(self, below: str) -> dict[str, bytes]:
        """The regular files under ``below``."""
        prefix = f"{below}/"
        return {
            path.removeprefix(prefix): content
            for path, content in self.hub.skill_files.items()
            if path.startswith(prefix)
        }

    def is_executable(self, path: str) -> bool:
        """Whether ``path`` is in ``executable``."""
        return path in self.hub.executable

    def exists(self, path: str) -> bool:
        """Whether an entry is at ``path`` or below it (a folder exists while it holds one)."""
        return any(entry == path or entry.startswith(f"{path}/") for entry in self._paths())

    def names(self, folder: str) -> set[str]:
        """The first segment below ``folder`` of every entry under it."""
        prefix = f"{folder}/"
        return {
            entry.removeprefix(prefix).split("/")[0]
            for entry in self._paths()
            if entry.startswith(prefix)
        }

    def _paths(self) -> set[str]:
        return {*self.hub.skill_files, *self.hub.skill_links, *self.hub.skill_specials}
