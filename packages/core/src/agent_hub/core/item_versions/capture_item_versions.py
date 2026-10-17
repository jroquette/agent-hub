"""``CaptureItemVersions``: capture on read (AGH-295, D2, D9, D17, D20, O4, A9).

A read hands each unit it shows with its stat mark (``unit_fingerprint``, or a workflow
source's fingerprint). The memo keeps, per ``(project, unit_path)``, the last mark captured and
the state it gave: an equal mark is skipped without a read, so a warm read touches neither the
disk nor the database. Otherwise the unit is read whole through ``HubFileReader.read_unit``: a
secret match, a unit past the bounds or one that cannot be read is kept as its state and never
stored; a hash that differs from the unit's last version is appended as ``external``
(``first`` when the unit has none). An append that loses the race for its ``seq`` reads the
last version again and stops once that hash equals, up to ``ATTEMPTS`` tries, so racing reads
store one row. A unit is marked only after it is settled: a store error (the database busy past
its timeout, a 503) leaves it, and every unit after it, for the next read. One call stops reading
new units once ``budget_bytes`` (the catalog's 16 MiB) have been read; the read that crosses it
still finishes, and the units left are read by a later call. A unit gone before its read is
left out of the answer.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Final

from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadUnit
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import NewItemVersion, UnitKind, VersionOrigin
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent, encode, size_of
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.item_versions.version_store import (
    ItemVersionSequenceError,
    ItemVersionStore,
)
from agent_hub.core.skills.skill_sources import CATALOG_BUDGET_BYTES

ATTEMPTS: Final = 3
# The units the memo remembers; past it the oldest is read again (and stores nothing new).
MEMO_UNITS: Final = 50_000

type UnitMark = Hashable


class UnitState(StrEnum):
    """What the last read found in a unit: stored (or equal to its last version), or why not."""

    OK = "ok"
    TOO_LARGE = "too_large"
    SECRET = "secret"  # noqa: S105 -- a state name, not a password
    UNREADABLE = "unreadable"


_UNREAD_STATES: Final = {"too_large": UnitState.TOO_LARGE, "unreadable": UnitState.UNREADABLE}


class CaptureItemVersions:
    """Records the units a read shows (see the module doc); one instance per app."""

    def __init__(
        self,
        store: ItemVersionStore,
        reader: HubFileReader,
        clock: Callable[[], datetime],
        *,
        budget_bytes: int = CATALOG_BUDGET_BYTES,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._budget = budget_bytes
        self._memo: OrderedDict[tuple[str, str], tuple[UnitMark, UnitState]] = OrderedDict()
        self._guard = threading.Lock()

    def capture(
        self, project: str, hub_path: str, units: Iterable[tuple[ItemUnit, UnitMark]]
    ) -> Mapping[str, UnitState]:
        """Capture each unit of ``project`` in the hub at ``hub_path``; answers the state of
        every unit settled now or before under the same mark."""
        states: dict[str, UnitState] = {}
        spent = 0
        for unit, mark in units:
            key = (project, unit.unit_path)
            with self._guard:
                known = self._memo.get(key)
            if known is not None and known[0] == mark:
                states[unit.unit_path] = known[1]
                continue
            if spent >= self._budget:
                continue
            read = self._reader.read_unit(hub_path, unit.unit_path, kind=unit.kind)
            if isinstance(read, UnreadUnit):
                if read.kind == "missing":
                    continue
                state = _UNREAD_STATES[read.kind]
            else:
                spent += size_of(read)
                state = UnitState.SECRET if has_secret_match(read) else UnitState.OK
                if state is UnitState.OK and not self._record(unit, read):
                    continue
            self._mark(key, mark, state)
            states[unit.unit_path] = state
        return states

    def _record(self, unit: ItemUnit, content: UnitContent) -> bool:
        """Append ``content`` unless the unit's last version holds it; False when every try lost
        the race (left for the next read)."""
        folder = unit.kind is UnitKind.SKILL
        content_hash = folder_hash(content.files) if folder else file_hash(content.files[0].content)
        for _ in range(ATTEMPTS):
            last = self._store.last(unit.project, unit.unit_path)
            if last is not None and last.content_hash == content_hash:
                return True
            seq = 1 if last is None else last.seq + 1
            version = NewItemVersion(
                project=unit.project,
                unit_path=unit.unit_path,
                kind=unit.kind,
                seq=seq,
                origin=VersionOrigin.EXTERNAL,
                first=seq == 1,
                recorded_at=self._clock(),
                content_hash=content_hash,
                size=size_of(content),
                content=encode(content, folder=folder),
            )
            try:
                self._store.append(version)
            except ItemVersionSequenceError:
                continue
            return True
        return False

    def _mark(self, key: tuple[str, str], mark: UnitMark, state: UnitState) -> None:
        with self._guard:
            self._memo[key] = (mark, state)
            self._memo.move_to_end(key)
            while len(self._memo) > MEMO_UNITS:
                self._memo.popitem(last=False)
