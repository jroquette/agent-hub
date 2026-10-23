"""An item version: one stored snapshot of a unit (AGH-295, S1, S3).

A unit is keyed by ``(project, unit_path)``, ``unit_path`` hub-relative with ``/`` separators and
no trailing slash. ``seq`` counts a unit's versions from 1 without gaps. An ``external`` version
was seen on disk and has no author (D11); a ``publish`` or ``restore`` carries the hub's
effective identity, and a ``restore`` names the version it restored. A ``publish`` made from a
Studio draft names that draft (``draft_id``, A5); no other origin carries one. A unit's
``first`` version (``first``, exactly ``seq`` 1) is ``external`` (D20) or, for a new item,
``publish`` (AC-295.12), never a ``restore``.
``recorded_at`` must carry an offset and is kept in UTC.
"""

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_hub.core.events.event import UtcTimestamp

# ``sha256:`` and 64 lowercase hex digits (S2).
CONTENT_HASH: Final = r"^sha256:[0-9a-f]{64}$"

type ContentHash = Annotated[str, Field(pattern=CONTENT_HASH)]

# A Studio draft's id (the spec's vocabulary): its kind and six lowercase letters or digits.
DRAFT_ID: Final = r"^(skill|agent|hook)-[a-z0-9]{6}$"


class VersionOrigin(StrEnum):
    """Where a version came from: the app's Publish or Restore, or the disk as the app read it."""

    PUBLISH = "publish"
    RESTORE = "restore"
    EXTERNAL = "external"


class UnitKind(StrEnum):
    """What a unit is: a skill's folder, an agent's file, a hook file, a hub workflow file or a
    scenario file (the scenario builder's saves)."""

    SKILL = "skill"
    AGENT = "agent"
    HOOK = "hook"
    WORKFLOW = "workflow"
    SCENARIO = "scenario"


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
    draft_id: Annotated[str, Field(pattern=DRAFT_ID)] | None = None

    @model_validator(mode="after")
    def _origin_rules(self) -> Self:
        external = self.origin is VersionOrigin.EXTERNAL
        if external != (self.author is None):
            msg = "author is set exactly when the origin is publish or restore"
            raise ValueError(msg)
        if self.first and self.origin is VersionOrigin.RESTORE:
            msg = "first is never a restore version"
            raise ValueError(msg)
        if (self.origin is VersionOrigin.RESTORE) != (self.restored_from is not None):
            msg = "restored_from is set exactly when the origin is restore"
            raise ValueError(msg)
        if self.draft_id is not None and self.origin is not VersionOrigin.PUBLISH:
            msg = "draft_id is set only when the origin is publish"
            raise ValueError(msg)
        if self.first != (self.seq == 1):
            msg = "first is set exactly on a unit's seq 1"
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
