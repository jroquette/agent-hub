"""``RecordAndWrite``: the write step Publish and Restore share (AGH-295, S4, D3, D9, D12, D22,
O2, O6, A1, A2, A8, A13, A15, A18, A20).

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
   write succeeded (every ``seq`` race lost, ``ItemWrittenRaceLostError``; the store failing, as
   a database busy past its timeout does) raises ``ItemWrittenUnrecordedError``: the request fails
   although the disk changed, and the next read records the written content as ``external``. A
   race lost or a store failure at step 3 is raised as it is: nothing was written.

``publish`` is the same step over every unit a Publish touches (``units``: an edit's target, a
rename's old and new unit, a new item's destination), under the same one lock and holding all of
them at once (the lock is not reentrant, so a Publish never calls ``write``). First, before step
1's checks and any read, a draft that a version of the project already names as its ``publish``
is spent (A20, ``refuse_spent``): ``draft_already_published``, and nothing is read, written,
recorded or removed. ``PublishDraft`` asks ``refuse_spent`` at its entry too, before any lookup;
the repeat here, under the lock, makes the second of two publishes of one draft find the first's
``publish``. Then
each unit is read (``unreadable`` refuses); ``place`` says where the draft lands from what was
read (``Destination``, which may refuse). A hook script already on disk with other bytes refuses
(``item_exists``); one with the same bytes is not written again. A destination equal to the disk
with no rename and no script to write answers ``changed: false``. Each unit's disk content is
recorded as in step 3, then step 4's managed check runs over every unit (O6); the scripts are
written (only scripts, the unit equal: ``changed: true, versioned: false, reason: script_only``,
A13), then the unit (a renamed skill carrying the old folder's hidden entries), recorded at once
as a ``publish`` naming ``draft_id`` (A5), as in step 6; then a rename's old unit is removed
(A15). A failed removal raises ``HubItemWriteError`` (``old_not_removed``, A18): both units stay,
the new one's history starting with its ``publish``, and the old one stays until the user
removes it (the draft is spent); so does a removal the writer refuses (``link_in_path``,
``hub_read_only``). A record failing after the write raises as in step 6 and the old unit is not
removed. A new hook's scripts may stay on disk after a failed unit write; a retry with the same
bytes skips them.

Accepted: the lock holds only this process's captures. Another process can capture the written
content as ``external`` between the write and its record, so one write can show as an
``external`` version followed by its ``publish`` or ``restore`` of the same content.
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadUnit
from agent_hub.core.item_versions.append_version import append_next, unit_hash
from agent_hub.core.item_versions.capture_item_versions import CaptureItemVersions
from agent_hub.core.item_versions.hub_item_writer import (
    OLD_NOT_REMOVED_CAUSE,
    HubItemWriteError,
    HubItemWriter,
    ItemWriteRefusedError,
)
from agent_hub.core.item_versions.item_units import ItemUnit, is_managed
from agent_hub.core.item_versions.item_version import UnitKind, VersionAuthor, VersionOrigin
from agent_hub.core.item_versions.item_version_ports import (
    ItemWriteResult,
    UnversionedReason,
    version_view,
)
from agent_hub.core.item_versions.publish_rules import Destination
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent, UnitFile
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError, ItemVersionStore
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, MAX_SKILL_FILE_BYTES


@dataclass(frozen=True, slots=True)
class NoAuthor:
    """Why a project has no effective identity to write as (O2)."""

    reason: str


type AuthorLookup = Callable[[str], VersionAuthor | NoAuthor]

# What a Publish read of each unit it touches, by unit path (``unreadable`` is refused first).
type UnitReads = Mapping[str, UnitContent | UnreadUnit]


class Placement(Protocol):
    """Where a Publish's draft lands, from what the disk holds now (see the module doc)."""

    def __call__(self, reads: UnitReads) -> Destination: ...


class OldNotRemovedError(HubItemWriteError):
    """A18: a rename's new unit was written (``result``, its ``publish`` recorded unless not
    versioned), but its old unit could not be removed and stays; so does the draft, which a
    recorded ``publish`` spends (A20). ``kind`` is ``old_not_removed``; no path is named."""

    def __init__(self, result: ItemWriteResult) -> None:
        super().__init__(OLD_NOT_REMOVED_CAUSE, kind="old_not_removed")
        self.result = result


class ItemWrittenUnrecordedError(AgentHubError):
    """The unit was written, but its version could not be recorded: the disk holds the new
    content and no version records it yet (the next read records it as ``external``). The
    store's error is the ``__cause__``; no path is named."""

    def __init__(self, cause: str = "the version could not be recorded") -> None:
        self.cause = cause
        super().__init__(f"item written, not recorded: {cause}")


class ItemWrittenRaceLostError(ItemWrittenUnrecordedError, ItemVersionSequenceError):
    """``ItemWrittenUnrecordedError`` because every race for the version's ``seq`` was lost."""

    def __init__(self, lost: ItemVersionSequenceError) -> None:
        ItemVersionSequenceError.__init__(
            self, lost.project, lost.unit_path, expected=lost.expected, got=lost.got
        )
        self.cause = "every race for its seq was lost"


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
            author = self._refuse_before_read(hub_path, [unit])
            on_disk = _content(self._read(hub_path, unit))
            if on_disk is not None and unit_hash(unit, on_disk) == unit_hash(unit, content):
                return _UNCHANGED
            self._record_external(unit, on_disk)
            restoring = origin is VersionOrigin.RESTORE
            if restoring and on_disk is not None and has_secret_match(on_disk):
                # D22: Publish proceeds and overwrites it unrecorded (A8).
                raise ItemWriteRefusedError("secret_unversioned")
            self._refuse_managed(hub_path, [unit], confirm_managed=confirm_managed)
            self._writer.write_unit(hub_path, unit.unit_path, content, kind=unit.kind)
            return self._record_written(
                unit, content, origin=origin, author=author, restored_from=restored_from
            )

    def publish(
        self,
        hub_path: str,
        units: Sequence[ItemUnit],
        place: Placement,
        *,
        confirm_managed: bool,
        draft_id: str,
    ) -> ItemWriteResult:
        """Land a draft where ``place`` says, over every unit in ``units``, and record a
        ``publish`` version naming ``draft_id``; a draft already published is refused."""
        with self._write_lock, self._capture.holding(units):
            # Again under the lock: of two publishes of one draft, the second finds the first's.
            self.refuse_spent(units[0].project, draft_id)
            author = self._refuse_before_read(hub_path, units)
            reads = {unit.unit_path: self._read(hub_path, unit) for unit in units}
            destination = place(reads)
            unit, removed = destination.unit, destination.removed
            if {unit.unit_path, *([] if removed is None else [removed.unit_path])} - reads.keys():
                msg = "a destination outside the units read"
                raise ValueError(msg)
            scripts = self._scripts_to_write(hub_path, destination.scripts)
            on_disk = _content(reads[unit.unit_path])
            held = on_disk is not None and unit_hash(unit, on_disk) == unit_hash(
                unit, destination.content
            )
            equal = removed is None and held
            if equal and not scripts:
                return _UNCHANGED
            for touched in units:
                self._record_external(touched, _content(reads[touched.unit_path]))
            self._refuse_managed(hub_path, units, confirm_managed=confirm_managed)
            for script in scripts:
                self._writer.write_file(
                    hub_path, script.path, script.content, executable=script.executable
                )
            if equal:
                return _SCRIPT_ONLY
            carry = removed.unit_path if removed and unit.kind is UnitKind.SKILL else None
            self._writer.write_unit(
                hub_path, unit.unit_path, destination.content, kind=unit.kind, carry_from=carry
            )
            result = self._record_written(
                unit,
                destination.content,
                origin=VersionOrigin.PUBLISH,
                author=author,
                draft_id=draft_id,
            )
            if removed is not None:
                self._remove_old(hub_path, removed, result)
            return result

    def refuse_spent(self, project: str, draft_id: str) -> None:
        """A20: ``draft_already_published`` when a version of ``project`` names ``draft_id`` as
        its ``publish`` (the server cannot prove a kept draft is the one it published)."""
        if self._store.has_publish(project, draft_id):
            raise ItemWriteRefusedError("draft_already_published")

    def _remove_old(self, hub_path: str, removed: ItemUnit, result: ItemWriteResult) -> None:
        """A rename's old unit removed; a failure is ``OldNotRemovedError`` carrying what was
        published (A18)."""
        try:
            self._writer.remove_unit(hub_path, removed.unit_path, kind=removed.kind)
        except (HubItemWriteError, ItemWriteRefusedError) as failed:
            raise OldNotRemovedError(result) from failed

    def _scripts_to_write(self, hub_path: str, scripts: Sequence[UnitFile]) -> tuple[UnitFile, ...]:
        """The scripts not on disk yet; one there with other bytes refuses (``item_exists``)."""
        paths = [script.path for script in scripts]
        if paths and not self._writer.is_writable(hub_path, paths):
            raise ItemWriteRefusedError("hub_read_only")
        self._writer.check_targets(hub_path, paths)
        missing: list[UnitFile] = []
        for script in scripts:
            found = self._writer.read_script(hub_path, script.path)
            if found is None:
                missing.append(script)
            elif found != script.content:
                raise ItemWriteRefusedError("item_exists")
        return tuple(missing)

    def _record_written(  # noqa: PLR0913 -- the version's facts, each named by the caller
        self,
        unit: ItemUnit,
        content: UnitContent,
        *,
        origin: VersionOrigin,
        author: VersionAuthor,
        restored_from: str | None = None,
        draft_id: str | None = None,
    ) -> ItemWriteResult:
        """Step 6: record the written content, unless it is too large or a secret match."""
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
                draft_id=draft_id,
            )
        except ItemVersionSequenceError as lost:
            raise ItemWrittenRaceLostError(lost) from lost
        except AgentHubError as failed:
            # The store's adapter errors are domain errors (a busy or unreadable database).
            raise ItemWrittenUnrecordedError from failed
        return ItemWriteResult(
            changed=True, versioned=True, reason=None, version=version_view(version)
        )

    def _refuse_before_read(self, hub_path: str, units: Sequence[ItemUnit]) -> VersionAuthor:
        """Step 1: the author to record, or why the write is refused."""
        paths = [unit.unit_path for unit in units]
        if not self._writer.is_writable(hub_path, paths):
            raise ItemWriteRefusedError("hub_read_only")
        author = self._author_of(units[0].project)
        if isinstance(author, NoAuthor):
            raise ItemWriteRefusedError("no_author", author.reason)
        self._writer.check_targets(hub_path, paths)
        return author

    def _read(self, hub_path: str, unit: ItemUnit) -> UnitContent | UnreadUnit:
        """Step 2's read: the unit's content, or why not (``unreadable`` refuses)."""
        on_disk = self._reader.read_unit(hub_path, unit.unit_path, kind=unit.kind)
        if isinstance(on_disk, UnreadUnit) and on_disk.kind == "unreadable":
            raise ItemWriteRefusedError("unit_unreadable")
        return on_disk

    def _record_external(self, unit: ItemUnit, on_disk: UnitContent | None) -> None:
        """Step 3: record the disk's content unless it is a secret match."""
        if on_disk is not None and not has_secret_match(on_disk):
            append_next(
                self._store, unit, on_disk, origin=VersionOrigin.EXTERNAL, clock=self._clock
            )

    def _refuse_managed(
        self, hub_path: str, units: Sequence[ItemUnit], *, confirm_managed: bool
    ) -> None:
        """Step 4's managed check, after the record of step 3 (O6)."""
        if confirm_managed:
            return
        lock = self._reader.read_lock(hub_path)
        if any(is_managed(lock, unit) for unit in units):
            raise ItemWriteRefusedError("managed_confirmation_required")


_UNCHANGED: Final = ItemWriteResult(changed=False, versioned=False, reason=None, version=None)
# Only a new hook's scripts were written: the hooks file was equal, no version (A13).
_SCRIPT_ONLY: Final = ItemWriteResult(
    changed=True, versioned=False, reason="script_only", version=None
)


def _content(read: UnitContent | UnreadUnit) -> UnitContent | None:
    """A read's content, None when the unit is missing or too large."""
    return read if isinstance(read, UnitContent) else None


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
