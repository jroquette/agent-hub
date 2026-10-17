"""The ``ItemVersionStore`` port: a unit's versions, append-only (AGH-295, S3, ADR 0039).

Synchronous (SQLAlchemy Core over SQLite in production). ``ItemVersionStoreContract`` checks
every implementation:

- ``append`` mints the version's UUIDv7 id and stores it only when its ``seq`` is the unit's
  last ``seq`` + 1 (1 for a unit with no version), else ``ItemVersionSequenceError`` and nothing
  is written: a unit's ``seq`` is gap-free, and of two writers racing for one ``seq`` one loses.
- ``last`` answers a unit's newest version; ``page`` its versions newest first, below
  ``before_seq`` when given (the cursor), at most ``limit``.
- ``get`` answers a version only within its own unit: an id of another unit or project is None.
- Nothing is ever updated or deleted: the port has no such method.
"""

from typing import Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.item_versions.item_version import ItemVersion, ItemVersionMeta, NewItemVersion


class ItemVersionSequenceError(AgentHubError):
    """An append whose ``seq`` is not the unit's next one (a gap, a repeat or a lost race)."""

    def __init__(self, project: str, unit_path: str, *, expected: int, got: int) -> None:
        self.project = project
        self.unit_path = unit_path
        self.expected = expected
        self.got = got
        super().__init__(f"item version: expected seq {expected}, got {got}")


class ItemVersionStore(Protocol):
    """Where the versions of a project's units are kept."""

    def append(self, version: NewItemVersion) -> ItemVersion:
        """Store ``version`` as its unit's next one; answers it with its new id."""
        ...

    def last(self, project: str, unit_path: str) -> ItemVersionMeta | None:
        """The unit's newest version, or None when it has none."""
        ...

    def page(
        self, project: str, unit_path: str, *, limit: int = 50, before_seq: int | None = None
    ) -> tuple[ItemVersionMeta, ...]:
        """The unit's versions newest first, with ``seq`` below ``before_seq`` when given."""
        ...

    def get(self, project: str, unit_path: str, version_id: str) -> ItemVersion | None:
        """The version ``version_id`` of that unit, with its content, or None."""
        ...
