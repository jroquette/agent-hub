"""Append a unit's next version, retrying a lost ``seq`` race (AGH-295, S3, S4).

Capture on read and the write step share it. An ``external`` version is appended only when the
unit's last version does not hold the content (that last one is answered then). An append whose
``seq`` was taken meanwhile (another reader or process appended first) reads the last version
again and tries once more, up to ``ATTEMPTS`` tries; after the last lost race the
``ItemVersionSequenceError`` is raised, for each caller to handle its own way.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import (
    ItemVersionMeta,
    NewItemVersion,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.unit_content import UnitContent, encode, size_of
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.item_versions.version_store import (
    ItemVersionSequenceError,
    ItemVersionStore,
)

ATTEMPTS: Final = 3


def unit_hash(unit: ItemUnit, content: UnitContent) -> str:
    """The content hash of ``content`` as a version of ``unit`` (a folder or a file, S2)."""
    if unit.kind is UnitKind.SKILL:
        return folder_hash(content.files)
    return file_hash(content.files[0].content)


def append_next(  # noqa: PLR0913 -- the version's facts, each named by the caller
    store: ItemVersionStore,
    unit: ItemUnit,
    content: UnitContent,
    *,
    origin: VersionOrigin,
    clock: Callable[[], datetime],
    author: VersionAuthor | None = None,
    restored_from: str | None = None,
    draft_id: str | None = None,
) -> ItemVersionMeta:
    """Append ``content`` as ``unit``'s next version (see the module doc)."""
    content_hash = unit_hash(unit, content)
    attempt = 1
    while True:
        last = store.last(unit.project, unit.unit_path)
        if (
            origin is VersionOrigin.EXTERNAL
            and last is not None
            and last.content_hash == content_hash
        ):
            return last
        seq = 1 if last is None else last.seq + 1
        version = NewItemVersion(
            project=unit.project,
            unit_path=unit.unit_path,
            kind=unit.kind,
            seq=seq,
            origin=origin,
            first=seq == 1,
            author=author,
            recorded_at=clock(),
            content_hash=content_hash,
            size=size_of(content),
            content=encode(content, folder=unit.kind is UnitKind.SKILL),
            restored_from=restored_from,
            draft_id=draft_id,
        )
        try:
            return store.append(version).meta()
        except ItemVersionSequenceError:
            if attempt == ATTEMPTS:
                raise
            attempt += 1
