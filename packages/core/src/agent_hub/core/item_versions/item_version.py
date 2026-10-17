"""An item version: one stored snapshot of a unit (AGH-295, S1, S3).

A unit is keyed by ``(project, unit_path)``, ``unit_path`` hub-relative with ``/`` separators and
no trailing slash. ``seq`` counts a unit's versions from 1 without gaps. An ``external`` version
was seen on disk and has no author (D11), and only it can be a unit's ``first`` (D20); a
``publish`` or ``restore`` carries the hub's effective identity, and a ``restore`` names the
version it restored. ``recorded_at`` must carry an offset and is kept in UTC.
"""

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_hub.core.events.event import UtcTimestamp

# ``sha256:`` and 64 lowercase hex digits (S2).
CONTENT_HASH: Final = r"^sha256:[0-9a-f]{64}$"

type ContentHash = Annotated[str, Field(pattern=CONTENT_HASH)]


class VersionOrigin(StrEnum):
    """Where a version came from: the app's Publish or Restore, or the disk as the app read it."""

    PUBLISH = "publish"
    RESTORE = "restore"
    EXTERNAL = "external"


class UnitKind(StrEnum):
    """What a unit is: a skill's folder, an agent's file, a hook file or a hub workflow file."""

    SKILL = "skill"
    AGENT = "agent"
    HOOK = "hook"
    WORKFLOW = "workflow"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VersionAuthor(_Frozen):
    """Who wrote a ``publish`` or ``restore`` version: the hub's effective identity (ADR 0016)."""

    name: str = Field(min_length=1)
    email: str = Field(min_length=1)


class _VersionFacts(_Frozen):
    """What every version holds besides its id and content."""

    project: str = Field(min_length=1)
    unit_path: str = Field(min_length=1)
    kind: UnitKind
    seq: int = Field(ge=1)
    origin: VersionOrigin
    first: bool = False
    author: VersionAuthor | None = None
    recorded_at: UtcTimestamp
    content_hash: ContentHash
    size: int = Field(ge=0)
    restored_from: str | None = None

    @model_validator(mode="after")
    def _origin_rules(self) -> Self:
        external = self.origin is VersionOrigin.EXTERNAL
        if external != (self.author is None):
            msg = "author is set exactly when the origin is publish or restore"
            raise ValueError(msg)
        if self.first and not external:
            msg = "first is only an external version"
            raise ValueError(msg)
        if (self.origin is VersionOrigin.RESTORE) != (self.restored_from is not None):
            msg = "restored_from is set exactly when the origin is restore"
            raise ValueError(msg)
        return self


class ItemVersionMeta(_VersionFacts):
    """A stored version without its content; ``id`` is the store's UUIDv7."""

    id: str = Field(min_length=1)


class ItemVersion(ItemVersionMeta):
    """A stored version with its content: a file unit's bytes, or a folder's frames
    (``unit_content.encode``)."""

    content: bytes

    def meta(self) -> ItemVersionMeta:
        """This version without its content."""
        return ItemVersionMeta.model_validate(self.model_dump(exclude={"content"}))


class NewItemVersion(_VersionFacts):
    """A version to append: the store mints its id."""

    content: bytes
