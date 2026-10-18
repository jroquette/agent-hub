"""``RecordAndWrite``: the write step Publish and Restore share (AGH-295, S4, D3, D9, D12, D22,
O2, O6, A1, A2, A8).

One write runs at a time in the process (the instance's lock: one instance per app, shared by
Publish and Restore), holding its unit in the app's
``CaptureItemVersions``, so a catalog read never records what it read before the write after
the write's version, and the next read reads the unit again. In this order:

1. the hub is writable (else ``hub_read_only``), the project has an effective identity (else
   ``no_author`` with the lookup's reason), and no component of the unit's path is a link
   (``link_in_path``; before the read, which would find such a unit ``unreadable``);
2. the unit is read whole: ``unreadable`` refuses (``unit_unreadable``: its content could not be
   recorded first); content equal to the disk's answers ``changed: false`` and nothing is
   written or recorded;
3. the disk's content is recorded as ``external`` when its hash differs from the unit's last
   version, unless it is a secret match or too large (a missing unit has nothing to record);
4. a Restore over a secret match on disk refuses (``secret_unversioned``, D22; Publish proceeds
   and overwrites it unrecorded, A8); a managed unit (A4) without ``confirm_managed`` refuses
   (``managed_confirmation_required``), after the record of step 3 (O6);
5. the unit is written; a failure raises the writer's ``HubItemWriteError`` and records nothing
   more (step 3's row stays: it is a true fact about the disk);
6. the written content is recorded with the origin given and the author, unless it is too large
   or a secret match (``versioned: false`` and that ``reason``). A record failing after the
   write succeeded (every ``seq`` race lost, ``ItemWrittenUnrecordedError``; the database busy
   past its timeout) fails the request although the disk changed; the next read records the
   written content as ``external``. A race lost at step 3 is the plain
   ``ItemVersionSequenceError``: nothing was written.

Accepted: the lock holds only this process's captures. Another process can capture the written
content as ``external`` between the write and its record, so one write can show as an
``external`` version followed by its ``publish`` or ``restore`` of the same content.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from agent_hub.core.hubs.hub_registry import HubFileReader
from agent_hub.core.item_versions.append_version import append_next, unit_hash
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import HubItemWriter, ItemWriteRefusedError
from agent_hub.core.item_versions.item_units import ItemUnit, is_managed
from agent_hub.core.item_versions.item_version import VersionAuthor, VersionOrigin
from agent_hub.core.item_versions.item_version_ports import (
    ItemWriteResult,
    UnversionedReason,
    version_view,
)
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError, ItemVersionStore
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, MAX_SKILL_FILE_BYTES


@dataclass(frozen=True, slots=True)
class NoAuthor:
    """Why a project has no effective identity to write as (O2)."""

    reason: str


type AuthorLookup = Callable[[str], VersionAuthor | NoAuthor]


class ItemWrittenUnrecordedError(ItemVersionSequenceError):
    """The unit was written, but every race for its version's ``seq`` was lost: the disk holds
    the new content and no version records it yet (the next read records it as ``external``)."""

    def __init__(self, lost: ItemVersionSequenceError) -> None:
        super().__init__(lost.project, lost.unit_path, expected=lost.expected, got=lost.got)


class RecordAndWrite:
    """The shared write step (see the module doc); one instance per app."""

    def __init__(
        self,
        store: ItemVersionStore,
        *,
        reader: HubFileReader,
        writer: HubItemWriter,
        author_of: AuthorLookup,
        clock: Callable[[], datetime],
        capture: CaptureItemVersions,
    ) -> None:
        self._store = store
        self._reader = reader
        self._writer = writer
        self._author_of = author_of
        self._clock = clock
        self._capture = capture
        # Publish and Restore are rare and user-driven, and share this one instance: one write
        # at a time in the process; a second waits for the first.
        self._write_lock = threading.Lock()

    def write(
        self,
        hub_path: str,
        unit: ItemUnit,
        content: UnitContent,
        *,
        origin: VersionOrigin,
        confirm_managed: bool = False,
        restored_from: str | None = None,
    ) -> ItemWriteResult:
        """Make ``unit`` in the hub at ``hub_path`` equal to ``content`` and record it as a
        ``origin`` version (a ``restore`` names ``restored_from``)."""
        with self._write_lock, self._capture.holding([unit]):
            author = self._refuse_before_read(hub_path, unit)
            on_disk = self._read(hub_path, unit)
            if on_disk is not None and unit_hash(unit, on_disk) == unit_hash(unit, content):
                return ItemWriteResult(changed=False, versioned=False, reason=None, version=None)
            self._record_first(
                hub_path, unit, on_disk, origin=origin, confirm_managed=confirm_managed
            )
            self._writer.write_unit(hub_path, unit.unit_path, content, kind=unit.kind)
            reason = _unversioned(content)
            if reason is not None:
                return ItemWriteResult(changed=True, versioned=False, reason=reason, version=None)
            try:
                version = append_next(
                    self._store,
                    unit,
                    content,
                    origin=origin,
                    clock=self._clock,
                    author=author,
                    restored_from=restored_from,
                )
            except ItemVersionSequenceError as lost:
                raise ItemWrittenUnrecordedError(lost) from lost
            return ItemWriteResult(
                changed=True, versioned=True, reason=None, version=version_view(version)
            )

    def _refuse_before_read(self, hub_path: str, unit: ItemUnit) -> VersionAuthor:
        """Step 1: the author to record, or why the write is refused."""
        if not self._writer.is_writable(hub_path, [unit.unit_path]):
            raise ItemWriteRefusedError("hub_read_only")
        author = self._author_of(unit.project)
        if isinstance(author, NoAuthor):
            raise ItemWriteRefusedError("no_author", author.reason)
        self._writer.check_targets(hub_path, [unit.unit_path])
        return author

    def _read(self, hub_path: str, unit: ItemUnit) -> UnitContent | None:
        """Step 2's read: the unit's content, None when it is missing or too large."""
        on_disk = self._reader.read_unit(hub_path, unit.unit_path, kind=unit.kind)
        if isinstance(on_disk, UnitContent):
            return on_disk
        if on_disk.kind == "unreadable":
            raise ItemWriteRefusedError("unit_unreadable")
        return None

    def _record_first(
        self,
        hub_path: str,
        unit: ItemUnit,
        on_disk: UnitContent | None,
        *,
        origin: VersionOrigin,
        confirm_managed: bool,
    ) -> None:
        """Steps 3 and 4: record the disk's content, then refuse a secret Restore or an
        unconfirmed managed write."""
        secret_on_disk = on_disk is not None and has_secret_match(on_disk)
        if on_disk is not None and not secret_on_disk:
            append_next(
                self._store, unit, on_disk, origin=VersionOrigin.EXTERNAL, clock=self._clock
            )
        if secret_on_disk and origin is VersionOrigin.RESTORE:
            raise ItemWriteRefusedError("secret_unversioned")
        if not confirm_managed and is_managed(self._reader.read_lock(hub_path), unit):
            raise ItemWriteRefusedError("managed_confirmation_required")


def _unversioned(content: UnitContent) -> UnversionedReason | None:
    """Why ``content`` is not stored: past the bounds a unit read holds the disk to (as the
    capture would find it), or a secret match; None when it is stored."""
    too_large = len(content.files) > MAX_UNIT_FILES or any(
        len(file.content) > MAX_SKILL_FILE_BYTES
        or file.path.count("/") >= DEFAULT_LIMITS.skill_depth
        for file in content.files
    )
    if too_large:
        return "too_large"
    if has_secret_match(content):
        return "secret"
    return None
