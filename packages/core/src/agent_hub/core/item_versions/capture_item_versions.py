"""``CaptureItemVersions``: capture on read (AGH-295, D2, D9, D17, D20, O4, A9).

A read hands each unit it shows with its stat mark (``unit_fingerprint``, or a workflow
source's fingerprint). The memo keeps, per ``(project, unit_path)``, the last mark captured and
the state it gave: an equal mark is skipped without a read, so a warm read touches neither the
disk nor the database. Otherwise the unit is read whole through ``HubFileReader.read_unit``: a
secret match, a unit past the bounds or one that cannot be read is kept as its state and never
stored; a hash that differs from the unit's last version is appended as ``external``
(``first`` when the unit has none). An append that loses the race for its ``seq`` reads the
last version again and stops once that hash equals, up to ``ATTEMPTS`` tries, so racing reads
store one row. A unit's cold path (memo check, read, record, mark) runs with its key held, so of
two reads of one unit the older is never appended after the newer. A unit is marked only after
it is settled: a store error (the database busy past its timeout, a 503) leaves it, and every
unit after it, for the next read. One request stops reading
new units once ``budget_bytes`` (the catalog's 16 MiB) have been read; the read that crosses it
still finishes, and the units left are read by a later request. A call spends its own budget
unless it is handed one (``budget()``), which a request reading several hubs shares across its
calls. A unit gone before its read is left out of the answer. A write of units (S4) runs
``holding`` them: no capture of one reads or records meanwhile, and their memo entries are
dropped, so the next read reads them again (and finds the version the write recorded).
"""

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from datetime import datetime
from enum import StrEnum
from typing import Final

from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadUnit
from agent_hub.core.item_versions.append_version import append_next
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import VersionOrigin
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent, size_of
from agent_hub.core.item_versions.version_store import (
    ItemVersionSequenceError,
    ItemVersionStore,
)
from agent_hub.core.skills.skill_sources import CATALOG_BUDGET_BYTES

# The units the memo remembers; past it the oldest is read again (and stores nothing new).
MEMO_UNITS: Final = 50_000

# The cold path of a unit runs under one of these, chosen by its key: a unit's reads and appends
# are serialised in this process, while other units mostly proceed in parallel.
UNIT_LOCKS: Final = 64

type UnitMark = Hashable


class UnitState(StrEnum):
    """What the last read found in a unit: stored (or equal to its last version), or why not."""

    OK = "ok"
    TOO_LARGE = "too_large"
    SECRET = "secret"  # noqa: S105 -- a state name, not a password
    UNREADABLE = "unreadable"


class CaptureBudget:
    """The unit bytes one request may still read; the read that crosses it still finishes."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.spent = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.total


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
        self._unit_locks = tuple(threading.Lock() for _ in range(UNIT_LOCKS))

    def budget(self) -> CaptureBudget:
        """A fresh budget for one request, to share across its ``capture`` calls."""
        return CaptureBudget(self._budget)

    def capture(
        self,
        project: str,
        hub_path: str,
        units: Iterable[tuple[ItemUnit, UnitMark]],
        *,
        budget: CaptureBudget | None = None,
    ) -> Mapping[str, UnitState]:
        """Capture each unit of ``project`` in the hub at ``hub_path`` within ``budget`` (a
        fresh one when None); answers the state of every unit settled now or before under the
        same mark."""
        states: dict[str, UnitState] = {}
        spending = self.budget() if budget is None else budget
        for unit, mark in units:
            key = (project, unit.unit_path)
            with self._guard:
                known = self._memo.get(key)
            if known is not None and known[0] == mark:
                states[unit.unit_path] = known[1]
                continue
            if spending.exhausted:
                continue
            settled, read_bytes = self._settle(key, hub_path, unit, mark=mark)
            spending.spent += read_bytes
            if settled is not None:
                states[unit.unit_path] = settled
        return states

    def _settle(
        self, key: tuple[str, str], hub_path: str, unit: ItemUnit, *, mark: UnitMark
    ) -> tuple[UnitState | None, int]:
        """Read, record and mark one unit with its key held, so an older read of it is never
        appended after a newer one; answers its state (None: not settled) and the bytes read."""
        with self._unit_locks[_lock_index(key)]:
            with self._guard:
                known = self._memo.get(key)
            if known is not None and known[0] == mark:
                return known[1], 0
            read = self._reader.read_unit(hub_path, unit.unit_path, kind=unit.kind)
            if isinstance(read, UnreadUnit):
                if read.kind == "missing":
                    return None, 0
                state = _UNREAD_STATES[read.kind]
                read_bytes = 0
            else:
                read_bytes = size_of(read)
                state = UnitState.SECRET if has_secret_match(read) else UnitState.OK
                if state is UnitState.OK and not self._record(unit, read):
                    return None, read_bytes
            self._mark(key, mark, state)
            return state, read_bytes

    @contextmanager
    def holding(self, units: Iterable[ItemUnit]) -> Iterator[None]:
        """Hold the keys of ``units`` while a write of them runs, then forget their marks."""
        keys = {(unit.project, unit.unit_path) for unit in units}
        with ExitStack() as held:
            # Each lock once (two keys may share one) and in one order, so writes never deadlock.
            for index in sorted({_lock_index(key) for key in keys}):
                held.enter_context(self._unit_locks[index])
            try:
                yield
            finally:
                with self._guard:
                    for key in keys:
                        self._memo.pop(key, None)

    def _record(self, unit: ItemUnit, content: UnitContent) -> bool:
        """Append ``content`` unless the unit's last version holds it; False when every try lost
        the race (left for the next read)."""
        try:
            append_next(
                self._store, unit, content, origin=VersionOrigin.EXTERNAL, clock=self._clock
            )
        except ItemVersionSequenceError:
            return False
        return True

    def _mark(self, key: tuple[str, str], mark: UnitMark, state: UnitState) -> None:
        with self._guard:
            self._memo[key] = (mark, state)
            self._memo.move_to_end(key)
            while len(self._memo) > MEMO_UNITS:
                self._memo.popitem(last=False)


def _lock_index(key: tuple[str, str]) -> int:
    return hash(key) % UNIT_LOCKS
