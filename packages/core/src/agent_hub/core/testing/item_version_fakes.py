"""``InMemoryItemVersionStore``: the ``ItemVersionStore`` port over a dictionary."""

import threading
import uuid

from agent_hub.core.item_versions.item_version import ItemVersion, ItemVersionMeta, NewItemVersion
from agent_hub.core.item_versions.version_store import ItemVersionSequenceError

type _UnitKey = tuple[str, str]


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
