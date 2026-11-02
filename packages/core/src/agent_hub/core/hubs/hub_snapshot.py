"""Each registered hub's facts and last doctor check, kept off the request (AGH-608).

What it holds (Q8): for every hub in the registry, its entry, its ``hub.json`` document, its
``hub.lock`` state and its last check, the findings of its last doctor run with the time that
run ended (``checked_at``; no check before the first run, so health and a lock state that needs
the doctor are unknown until then, Q9).

When the doctor runs (Q7): only in a tick (``refresh``), which the background part of ``hub
web`` calls every 2 s. A tick reads the registry and the ``hub.json`` and ``hub.lock`` of a new
hub or of one whose two modification times changed, and drops the hubs no longer registered;
then, one hub at a time, it runs the doctor for each hub that names a project and is due. A hub
is due when it has no check and no failure yet; when ``reread(written=...)`` marked it since its
last run started (a write through the app: the spacing and any backoff skipped); when its last
run raised and its backoff passed (the next tick, then ``min_interval`` doubling up to ``ttl``:
10, 20, 40 ... 900 s; a success resets it); or, at least ``min_interval`` (10 s, Q31) after its
last run ended, when its check is ``ttl`` old or a watched path's time changed. A clock set back
before the end of a hub's last run makes it due at once (its age, negative, is unknown). The
facts check reads the times of ``hub.json`` and ``hub.lock`` through a link, as ``hub.json`` is
read; the doctor's watched paths keep the times of the paths themselves. A check keeps the
times its due test read before the run, so a write made during the run shows at the next due
test; a path the run saw first keeps the time read after the run, unless that time is later than
one second before the run started (a file system that keeps whole seconds could round a write
made during the run down to it), in which case the check keeps no time and the hub runs again.
A run that raises keeps the previous check and is reported.

Threads: a read (``hubs``, ``drift_of``) takes no lock and sees one published, immutable state.
The writers (``reread``, a tick's read of the facts, each run's publish) take one lock, and the
doctor runs outside it; a run whose hub was removed meanwhile is dropped when it ends. So an
edit made outside the app shows after the next due tick, and a write through the app shows once
``reread`` returns, its doctor at the next tick.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Final

from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.lock_rules import NOT_ADOPTED
from agent_hub.core.doctor.snapshot import LockState
from agent_hub.core.hub_config.doctor_rules import LOCK_DRIFT_RULE
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.core.hubs.doctor_cache import ALWAYS_WATCHED, DOCTOR_TTL, HUB_JSON, run_doctor
from agent_hub.core.hubs.hub_document import HubDocument, read_hub_document
from agent_hub.core.hubs.hub_registry import HubFileReader, HubRegistry, HubRegistryError
from agent_hub.core.hubs.list_hubs import HubRead, hub_read
from agent_hub.core.hubs.registered_hub import RegisteredHub

MIN_RUN_INTERVAL: Final = timedelta(seconds=10)
# A time read after a run is kept only when it is older than the run's start by this much.
_WHOLE_SECOND: Final = timedelta(seconds=1)
# The backoff doubles from ``min_interval``; long before this many doublings it is the TTL.
_MAX_DOUBLINGS: Final = 16
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


class _NoTime(Enum):
    """The time of a watched path that a check did not keep: it always reads as changed."""

    NO_TIME = auto()


type _KeptTime = int | None | _NoTime


class _Verdict(Enum):
    DUE = auto()
    NOT_DUE = auto()
    IF_CHANGED = auto()


@dataclass(frozen=True, kw_only=True, slots=True)
class HubCheck:
    """The findings of a hub's last doctor run, and when that run ended."""

    findings: tuple[Finding, ...]
    checked_at: datetime


@dataclass(frozen=True, kw_only=True, slots=True)
class HubState:
    """A registered hub as last read: its entry, document and view, its lock and its check."""

    read: HubRead
    lock: LockState | None
    check: HubCheck | None


@dataclass(frozen=True, kw_only=True, slots=True)
class RefreshFailure:
    """A doctor run that raised during a tick."""

    hub_path: str
    error: Exception


@dataclass(frozen=True, kw_only=True, slots=True)
class RefreshReport:
    """What one tick did: the hubs whose doctor ran, and the runs that raised."""

    checked: tuple[str, ...]
    failures: tuple[RefreshFailure, ...]


@dataclass(kw_only=True, slots=True, eq=False)
class _Hub:
    """One registered hub as the writers keep it; changed only under the writer lock."""

    entry: RegisteredHub
    document: HubDocument
    lock: LockState | None
    json_time: int | None
    lock_time: int | None
    check: HubCheck | None = None
    # The paths the next due test reads, and the times the check kept for them.
    watched: tuple[str, ...] = ALWAYS_WATCHED
    times: tuple[_KeptTime, ...] = ()
    failures: int = 0
    # When the last failed run ended, and when the backoff after it ends.
    failed_at: datetime | None = None
    retry_at: datetime | None = None
    marked: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class _Published:
    states: tuple[HubState, ...]
    error: HubRegistryError | None = None


class HubSnapshot:
    """The registered hubs' facts and last checks, read without a lock and refreshed by ticks."""

    def __init__(
        self,
        registry: HubRegistry,
        reader: HubFileReader,
        *,
        running_version: str,
        clock: Callable[[], datetime],
        ttl: timedelta = DOCTOR_TTL,
        min_interval: timedelta = MIN_RUN_INTERVAL,
    ) -> None:
        self._registry = registry
        self._reader = reader
        self._running = running_version
        self._clock = clock
        self._ttl = ttl
        self._min_interval = min_interval
        self._writer = threading.Lock()
        self._hubs: dict[str, _Hub] = {}
        self._published: _Published | None = None
        self._refreshed_at: datetime | None = None

    def hubs(self) -> tuple[HubState, ...]:
        """Every registered hub, in registration order; the facts are read here only when
        nothing read them before. ``HubRegistryError`` while the last registry read failed."""
        published = self._published or self._first_read()
        if published.error is not None:
            raise HubRegistryError(*published.error.args) from published.error
        return published.states

    def reread(self, written: str | None = None) -> None:
        """Read the registry and every hub's ``hub.json`` and ``hub.lock`` now, keeping the
        checks of the hubs still registered; ``written``, a hub a write through the app
        changed, is due at the next tick."""
        with self._writer:
            self._read_facts(every=True, written=written)

    def refresh(self) -> RefreshReport:
        """One tick: the facts that changed, then the doctor of each due hub, published as each
        run ends. ``HubRegistryError`` when the registry cannot be read (no doctor runs)."""
        with self._writer:
            self._read_facts(every=False)
            named = tuple(hub for hub in self._hubs.values() if hub.document.project is not None)
        checked: list[str] = []
        failures: list[RefreshFailure] = []
        for hub in named:
            outcome = self._check(hub)
            if isinstance(outcome, RefreshFailure):
                failures.append(outcome)
            elif outcome is not None:
                checked.append(outcome)
        self._refreshed_at = self._clock()
        return RefreshReport(checked=tuple(checked), failures=tuple(failures))

    def refreshed_at(self) -> datetime | None:
        """When the last tick that read the registry ended; None before the first one ends."""
        return self._refreshed_at

    def drift_of(self, hub_path: str, document: HubDocument) -> bool | None:
        """Whether the hub's last check found a managed file changed (``lock.drift``); None
        before its first check."""
        del document
        published = self._published
        states = () if published is None else published.states
        check = next((state.check for state in states if state.read.entry.path == hub_path), None)
        return None if check is None else _drifted(check)

    def _first_read(self) -> _Published:
        with self._writer:
            return self._published or self._read_facts(every=True)

    def _read_facts(self, *, every: bool, written: str | None = None) -> _Published:
        """Under the writer lock: the registry, then the facts of each hub that is new, whose
        times changed or, with ``every``, all of them; then publish."""
        try:
            entries = self._registry.entries()
        except HubRegistryError as error:
            last = self._published
            self._published = _Published(states=() if last is None else last.states, error=error)
            raise
        known = self._hubs
        self._hubs = {
            entry.path: self._facts(entry, known.get(entry.path), every=every) for entry in entries
        }
        marked = self._hubs.get(written) if written is not None else None
        if marked is not None:
            marked.marked = True
        return self._publish()

    def _facts(self, entry: RegisteredHub, known: _Hub | None, *, every: bool) -> _Hub:
        # Followed: ``hub.json`` is read through a link, so an edit to its target must show.
        json_time, lock_time = self._reader.followed_times(entry.path, (HUB_JSON, HUB_LOCK_PATH))
        if known is None:
            return _Hub(
                entry=entry,
                document=self._document(entry.path),
                lock=self._reader.read_lock(entry.path),
                json_time=json_time,
                lock_time=lock_time,
            )
        if every or known.json_time != json_time:
            known.document = self._document(entry.path)
        if every or known.lock_time != lock_time:
            known.lock = self._reader.read_lock(entry.path)
        known.entry, known.json_time, known.lock_time = entry, json_time, lock_time
        return known

    def _document(self, hub_path: str) -> HubDocument:
        return read_hub_document(
            self._reader.read_hub_json(hub_path), running_version=self._running
        )

    def _publish(self) -> _Published:
        self._published = _Published(states=tuple(self._state(hub) for hub in self._hubs.values()))
        return self._published

    def _state(self, hub: _Hub) -> HubState:
        check = hub.check
        read = hub_read(
            hub.entry,
            hub.document,
            hub.lock,
            running_version=self._running,
            has_drift=lambda: None if check is None else _drifted(check),
            checked_at=None if check is None else check.checked_at,
        )
        return HubState(read=read, lock=hub.lock, check=check)

    def _check(self, hub: _Hub) -> str | RefreshFailure | None:
        """The hub's doctor, when due and still registered."""
        path = hub.entry.path
        now = self._clock()
        with self._writer:
            if self._hubs.get(path) is not hub:
                return None
            verdict = self._verdict(hub, now)
            watched, kept = hub.watched, hub.times
        if verdict is _Verdict.NOT_DUE:
            return None
        before = self._reader.modified_times(path, watched)
        if verdict is _Verdict.IF_CHANGED and before == kept:
            return None
        with self._writer:
            if self._hubs.get(path) is not hub:
                return None
            hub.marked = False
        return self._run(hub, dict(zip(watched, before, strict=True)))

    def _verdict(self, hub: _Hub, now: datetime) -> _Verdict:
        """A negative age (``now`` before the last run ended: the clock was set back) is due."""
        if hub.marked:
            return _Verdict.DUE
        if hub.retry_at is not None and hub.failed_at is not None:
            due = now >= hub.retry_at or now < hub.failed_at
            return _Verdict.DUE if due else _Verdict.NOT_DUE
        if hub.check is None:
            return _Verdict.DUE
        age = now - hub.check.checked_at
        if age < timedelta(0):
            return _Verdict.DUE
        if age < self._min_interval:
            return _Verdict.NOT_DUE
        return _Verdict.DUE if age >= self._ttl else _Verdict.IF_CHANGED

    def _run(self, hub: _Hub, before: dict[str, int | None]) -> str | RefreshFailure:
        """One doctor run, outside the lock; its check published if the hub is still kept."""
        path = hub.entry.path
        started = self._clock()
        try:
            run = run_doctor(self._reader, path, running_version=self._running)
        except Exception as error:  # noqa: BLE001 - the previous check stays; the tick reports it
            self._fail(hub, ended=self._clock())
            return RefreshFailure(hub_path=path, error=error)
        ended = self._clock()
        times = self._kept_times(path, run.watched, before, started=started)
        with self._writer:
            if self._hubs.get(path) is hub:
                hub.check = HubCheck(findings=run.findings, checked_at=ended)
                hub.watched, hub.times = run.watched, times
                hub.failures, hub.failed_at, hub.retry_at = 0, None, None
                self._publish()
        return path

    def _fail(self, hub: _Hub, *, ended: datetime) -> None:
        with self._writer:
            if self._hubs.get(hub.entry.path) is hub:
                hub.failures += 1
                hub.failed_at = ended
                hub.retry_at = ended + self._backoff(hub.failures)

    def _backoff(self, failures: int) -> timedelta:
        """The first retry at the next tick, then ``min_interval`` doubling up to ``ttl``."""
        if failures <= 1:
            return timedelta(0)
        return min(self._min_interval * (1 << min(failures - 2, _MAX_DOUBLINGS)), self._ttl)

    def _kept_times(
        self,
        hub_path: str,
        watched: tuple[str, ...],
        before: dict[str, int | None],
        *,
        started: datetime,
    ) -> tuple[_KeptTime, ...]:
        """The times read before the run; for a path the run saw first, the time read after
        it, unless that is later than one second before the run started."""
        first_seen = tuple(path for path in watched if path not in before)
        after = dict(
            zip(first_seen, self._reader.modified_times(hub_path, first_seen), strict=True)
        )
        latest = _nanoseconds(started - _WHOLE_SECOND)

        def kept(path: str) -> _KeptTime:
            if path in before:
                return before[path]
            time = after[path]
            return _NoTime.NO_TIME if time is not None and time > latest else time

        return tuple(kept(path) for path in watched)


def _drifted(check: HubCheck) -> bool:
    return any(
        finding.rule == LOCK_DRIFT_RULE and finding.message != NOT_ADOPTED
        for finding in check.findings
    )


def _nanoseconds(moment: datetime) -> int:
    """``moment`` as a file time: nanoseconds since the epoch."""
    return (moment - _EPOCH) // timedelta(microseconds=1) * 1000
