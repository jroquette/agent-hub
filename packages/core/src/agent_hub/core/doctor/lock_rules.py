"""``lock.drift``: the hub against its ``hub.lock`` (docs/design/hub-sync.md § hub.lock, Q-13).

Each managed file must hold the bytes and executable bit its entry records, and each managed
link its target, looked at without following links; seeded paths are the project's and never
compared. The lock's ``platform_version`` is compared with the pin as numbers; its other header
fields are ``hub sync``'s to judge. ``lock_state`` reads the lock as ``hub sync`` does, returning
what it found instead of exiting.
"""

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import replace
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, LockAbsent, LockNotRegular, LockState
from agent_hub.core.hub_config.doctor_rules import LOCK_DRIFT_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.hub_lock import (
    HUB_LOCK_PATH,
    LOCK_NOT_REGULAR,
    LOCK_WAY_OUT,
    HubLock,
    LockEntry,
    ManagedFileEntry,
    ManagedLinkEntry,
    read_hub_lock,
)
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry

SYNC_FIX: Final = "run hub sync"
ADOPT_FIX: Final = "run hub sync --adopt"
NOT_ADOPTED: Final = "not adopted: no hub.lock records this hub's files"
MISSING: Final = "missing; hub sync restores it"
NOT_READ: Final = "content was not read, so it cannot be compared with its hub.lock entry"
NOT_READ_FIX: Final = "run hub doctor again"


def lock_state(entry: TreeEntry | None) -> LockState:
    """What the ``hub.lock`` entry holds: only a regular file read with its content is parsed."""
    if entry is None:
        return LockAbsent()
    if not isinstance(entry, FileEntry) or entry.content is None:
        return LockNotRegular()
    return read_hub_lock(entry.content)


def lock_paths(lock: LockState | None) -> tuple[str, ...]:
    """The managed paths of a lock read, sorted: what ``lock.drift`` looks at by path."""
    if not isinstance(lock, HubLock):
        return ()
    return tuple(
        sorted(
            path
            for path, entry in lock.files.items()
            if isinstance(entry, ManagedFileEntry | ManagedLinkEntry)
        )
    )


def _lock_drift(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    lock = snapshot.lock
    if lock is None:
        # Not read: the hub's files name the read that failed.
        return ()
    if isinstance(lock, LockAbsent):
        return (_warning(path=HUB_LOCK_PATH, message=NOT_ADOPTED, fix=ADOPT_FIX),)
    if isinstance(lock, LockNotRegular):
        return (LOCK_DRIFT.finding(path=HUB_LOCK_PATH, message=LOCK_NOT_REGULAR, fix=LOCK_WAY_OUT),)
    if not isinstance(lock, HubLock):
        return tuple(
            LOCK_DRIFT.finding(
                path=HUB_LOCK_PATH, message=f"{problem.path}: {problem.message}", fix=LOCK_WAY_OUT
            )
            for problem in lock
        )
    header = _header_finding(lock, pin=snapshot.hub_config.platform.version)
    return (*(() if header is None else (header,)), *_entry_findings(lock, snapshot))


def _warning(*, path: str, message: str, fix: str) -> Finding:
    return replace(
        LOCK_DRIFT.finding(path=path, message=message, fix=fix), severity=Severity.WARNING
    )


def _release_key(release: str) -> tuple[tuple[int, str], ...]:
    """A release as numbers, compared without ``int`` (a pin may hold thousands of digits)."""
    parts = (part.lstrip("0") for part in release.split("."))
    return tuple((len(part), part) for part in parts)


def _header_finding(lock: HubLock, *, pin: str) -> Finding | None:
    locked, pinned = _release_key(lock.platform_version), _release_key(pin)
    written = f"hub.lock was written by {cut_echo(lock.platform_version)}"
    if locked < pinned:
        return _warning(
            path=HUB_LOCK_PATH,
            message=f"sync pending: {written}, hub.json pins {cut_echo(pin)}",
            fix=SYNC_FIX,
        )
    if locked > pinned:
        return _warning(
            path=HUB_LOCK_PATH,
            message=f"downgrade: {written}, newer than the {cut_echo(pin)} hub.json pins",
            fix=f"pin {cut_echo(lock.platform_version)} in hub.json, or run hub sync to downgrade",
        )
    return None


def _entry_findings(lock: HubLock, snapshot: DoctorSnapshot) -> Iterator[Finding]:
    # With a failed path read, an absent path may be one the read never reached: not "missing".
    # A failed listing alone reads every path by path, so an absent one is missing.
    all_read = snapshot.hub.paths_read
    for path, locked in lock.files.items():
        on_disk = snapshot.hub.entries.get(path)
        if on_disk is None:
            message = MISSING if all_read and _is_managed(locked) else None
        elif isinstance(locked, ManagedFileEntry) and _unread(on_disk):
            yield LOCK_DRIFT.finding(path=path, message=NOT_READ, fix=NOT_READ_FIX)
            continue
        else:
            message = _drift(locked, on_disk)
        if message is not None:
            yield LOCK_DRIFT.finding(path=path, message=message, fix=SYNC_FIX)


def _unread(on_disk: TreeEntry) -> bool:
    return isinstance(on_disk, FileEntry) and on_disk.content is None


def _is_managed(locked: LockEntry) -> bool:
    return isinstance(locked, ManagedFileEntry | ManagedLinkEntry)


def _drift(locked: LockEntry, on_disk: TreeEntry) -> str | None:
    if isinstance(locked, ManagedFileEntry):
        return _file_drift(locked, on_disk)
    if isinstance(locked, ManagedLinkEntry):
        return _link_drift(locked, on_disk)
    return None


def _bit(executable: bool) -> str:  # noqa: FBT001 - one flag shown as +x or -x
    return "+x" if executable else "-x"


def _file_drift(locked: ManagedFileEntry, on_disk: TreeEntry) -> str | None:
    if not isinstance(on_disk, FileEntry):
        return "not a regular file; hub.lock records a file"
    if on_disk.content is not None and hashlib.sha256(on_disk.content).hexdigest() != locked.sha256:
        return "content differs from its hub.lock entry"
    if on_disk.executable != locked.executable:
        return (
            "executable bit differs from its hub.lock entry"
            f" (on disk {_bit(on_disk.executable)}, hub.lock {_bit(locked.executable)})"
        )
    return None


def _link_drift(locked: ManagedLinkEntry, on_disk: TreeEntry) -> str | None:
    if not isinstance(on_disk, LinkEntry):
        return "not a link; hub.lock records a link"
    if on_disk.target != locked.symlink:
        return (
            "link target differs from its hub.lock entry"
            f" (on disk -> {cut_echo(on_disk.target)}, hub.lock -> {cut_echo(locked.symlink)})"
        )
    return None


LOCK_DRIFT: Final = Rule(
    id=LOCK_DRIFT_RULE,
    severity=Severity.ERROR,
    summary="each managed file and link matches its hub.lock entry, and the lock the pin",
    module=RULE_MODULES.get(LOCK_DRIFT_RULE),
    reads=frozenset({Read.LOCK_PATHS}),
    check=_lock_drift,
)
