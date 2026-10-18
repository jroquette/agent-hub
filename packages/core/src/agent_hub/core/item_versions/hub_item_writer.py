"""The ``HubItemWriter`` port: the one way a request writes a Toolkit or workflow unit into a
hub's tree (AGH-295, S3, S4, D3, D4, D7, D12, A6; ADR 0039).

Synchronous. ``HubItemWriterContract`` checks every implementation:

- ``is_writable`` answers whether the hub (and, for each unit path given, its nearest existing
  folder) can be written at all; a read-only mount answers False.
- ``check_targets`` refuses, before anything is written, a unit path one of whose components
  is a link (``ItemWriteRefusedError("link_in_path")``); a component that does not exist yet is
  fine.
- ``write_unit`` makes the unit equal to ``content``: a file unit (one ``UnitFile`` named after
  the file) is written to a temporary file beside it and renamed into place; a folder unit (a
  skill) is staged whole beside the target and swapped in, so it ends holding exactly the
  version's files with their executable bits, the files and now-empty folders the version does
  not hold gone, and the target's hidden entries (which no version records) carried over
  unchanged. A completed or failed write never leaves a mix of old and new files.
- ``write_file`` writes one plain file (a new hook's script) the same way as a file unit.
- ``remove_unit`` removes a unit (a rename's old unit); an absent one is fine.

A refusal is ``ItemWriteRefusedError`` (``hub_read_only`` or ``link_in_path``); any other I/O
failure is ``HubItemWriteError``. Neither message names a path. A unit path that is not a unit
of its kind, or a path that is not plain and relative, is a caller bug (``ValueError``).
"""

from collections.abc import Sequence
from typing import Final, Literal, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.item_versions.item_units import unit_parts
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent
from agent_hub.core.skills.skill_sources import SkillPathError

_NOT_PLAIN: Final = frozenset({"", ".", ".."})

# Why a write is refused, as the API's 409 ``code`` says it.
type WriteRefusal = Literal[
    "hub_read_only",
    "link_in_path",
    "item_exists",
    "managed_confirmation_required",
    "secret_unversioned",
    "unit_unreadable",
    "no_author",
    "draft_invalid",
]

_REASONS: dict[WriteRefusal, str] = {
    "hub_read_only": "The hub folder is not writable here",
    "link_in_path": "A path of the item is a link",
    "item_exists": "An item of that kind and name already exists",
    "managed_confirmation_required": "The item is managed: the next hub sync rewrites it",
    "secret_unversioned": "The item on disk holds a secret match and has no version",
    "unit_unreadable": "The item on disk cannot be read whole",
    "no_author": "No author identity is set for this hub",
    "draft_invalid": "The draft is not a valid item",
}


class ItemWriteRefusedError(AgentHubError):
    """A write refused before or instead of writing: ``code`` says why, ``reason`` in words."""

    def __init__(self, code: WriteRefusal, reason: str | None = None) -> None:
        self.code: WriteRefusal = code
        self.reason = reason if reason is not None else _REASONS[code]
        super().__init__(f"item write refused: {code}")


class HubItemWriteError(AgentHubError):
    """A write that failed on I/O; the hub keeps the unit as it was. No path is named."""

    def __init__(self, cause: str = "the write failed") -> None:
        self.cause = cause
        super().__init__(f"item write failed: {cause}")


def plain_parts(path: str) -> tuple[str, ...]:
    """``path``'s segments when it is plain and relative (no empty, ``.`` or ``..`` segment, no
    NUL), else ``ValueError`` naming no path: ``openat`` with ``O_NOFOLLOW`` still climbs out
    through ``..``."""
    segments = tuple(path.split("/"))
    if "\0" in path or not _NOT_PLAIN.isdisjoint(segments):
        msg = "not a relative path inside the hub"
        raise ValueError(msg)
    return segments


def checked_unit_parts(unit_path: str, kind: UnitKind) -> tuple[str, ...]:
    """``unit_parts`` with a refused path as ``ValueError`` (a caller bug), naming no path."""
    try:
        return unit_parts(unit_path, kind)
    except SkillPathError as error:
        msg = "not a unit of its kind"
        raise ValueError(msg) from error


class HubItemWriter(Protocol):
    """Writes units into a hub's tree, never through a link, never outside the unit's path."""

    def is_writable(self, hub_path: str, unit_paths: Sequence[str] = ()) -> bool:
        """Whether the hub, and the nearest existing folder of each of ``unit_paths``, can be
        written."""
        ...

    def check_targets(self, hub_path: str, unit_paths: Sequence[str]) -> None:
        """Raise ``ItemWriteRefusedError("link_in_path")`` when a component of a path is a link."""
        ...

    def write_unit(
        self, hub_path: str, unit_path: str, content: UnitContent, *, kind: UnitKind
    ) -> None:
        """Make the unit at ``unit_path`` equal to ``content``."""
        ...

    def write_file(
        self, hub_path: str, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        """Write the one file ``path`` (hub-relative) through a temporary file and a rename."""
        ...

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        """Remove the unit at ``unit_path``; an absent one is fine."""
        ...
