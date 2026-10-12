"""List the registered hubs as read now: each one's ``hub.json`` (Q4: any pin) and lock state.

The lock state is ``not_adopted`` without ``hub.lock``, ``sync_pending`` when the lock records
another release than the pin, ``drift`` when the doctor's ``lock.drift`` rule finds a managed
file changed (asked through ``has_drift``, only for a lock that matches the pin), else
``in_sync``; unknown (None) when the lock cannot be read or is no lock.
"""

from collections.abc import Callable
from dataclasses import dataclass

from agent_hub.core.doctor.snapshot import LockAbsent, LockState
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HubLock
from agent_hub.core.hubs.hub_document import HubDocument, read_hub_document
from agent_hub.core.hubs.hub_registry import HubFileReader, HubRegistry
from agent_hub.core.hubs.registered_hub import HubView, RegisteredHub
from agent_hub.core.projects.project_views import LockState as LockStateName

# Whether the hub's managed files drifted from its lock (the doctor's ``lock.drift``).
type DriftCheck = Callable[[str, HubDocument], bool]


def no_drift(_hub_path: str, _document: HubDocument) -> bool:
    """The drift check of a reader that runs no doctor: never drifted."""
    return False


@dataclass(frozen=True, kw_only=True, slots=True)
class HubRead:
    """A registry entry, its document and the view the API shows."""

    entry: RegisteredHub
    document: HubDocument
    view: HubView


class ListHubs:
    """Read every registered hub, valid or not, in registration order."""

    def __init__(
        self,
        registry: HubRegistry,
        reader: HubFileReader,
        *,
        running_version: str,
        has_drift: DriftCheck = no_drift,
    ) -> None:
        self._registry = registry
        self._reader = reader
        self._running = running_version
        self._has_drift = has_drift

    def __call__(self) -> tuple[HubRead, ...]:
        """Every registered hub as read now."""
        return tuple(self.read(entry) for entry in self._registry.entries())

    def read(self, entry: RegisteredHub) -> HubRead:
        """One registered hub as read now."""
        document = read_hub_document(
            self._reader.read_hub_json(entry.path), running_version=self._running
        )
        state: LockStateName | None = None
        version: str | None = None
        if document.config is not None:
            state, version = lock_view(
                self._reader.read_lock(entry.path),
                pin=document.pin,
                has_drift=lambda: self._has_drift(entry.path, document),
            )
        return HubRead(
            entry=entry,
            document=document,
            view=_view(entry, document, running=self._running, lock=(state, version)),
        )


def lock_view(
    lock: LockState | None, *, pin: str | None, has_drift: Callable[[], bool]
) -> tuple[LockStateName | None, str | None]:
    """The lock state's name and the lock's release; ``has_drift`` runs only when it matters."""
    if isinstance(lock, LockAbsent):
        return "not_adopted", None
    if not isinstance(lock, HubLock):
        return None, None
    if lock.platform_version != pin:
        return "sync_pending", lock.platform_version
    return ("drift" if has_drift() else "in_sync"), lock.platform_version


def _view(
    entry: RegisteredHub,
    document: HubDocument,
    *,
    running: str,
    lock: tuple[LockStateName | None, str | None],
) -> HubView:
    config = document.config
    state, version = lock
    return HubView(
        id=entry.id,
        path=entry.path,
        added_at=entry.added_at,
        project=document.project,
        platform_pin=document.pin,
        running_version=running,
        lock_version=version,
        lock_state=state,
        modules=() if config is None else module_ids(config),
        guard_ask_before_edit=() if config is None else config.guard.ask_before_edit,
        repos=() if config is None else tuple(repo.dir for repo in config.repos),
        valid=document.valid,
        validation_errors=document.problems,
        warnings=document.warnings,
    )


def module_ids(config: HubConfig) -> tuple[str, ...]:
    """The selected modules' ids, sorted."""
    return tuple(sorted(config.modules.model_dump(by_alias=True, exclude_none=True)))
