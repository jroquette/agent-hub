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
  not hold gone (a link among them removed, never followed), and the target's hidden entries
  (which no version records) carried over unchanged. A version holding a hidden name is a
  caller bug (``ValueError``): the reader never records one. A completed or failed write never
  leaves a mix of old and new files, but for a failed roll back (below). With ``carry_from`` (a
  skill rename's old folder, a sibling of the unit), the hidden entries moved into the new folder
  are that folder's instead (the owner's PR 3 decision); the unit must be absent then, else
  ``HubItemWriteError`` (``failed``) before anything moves, and a failed write moves them back.
- ``write_file`` writes one new hook's script, ``plugin/<p>/scripts/…`` (no hidden segment),
  the same way as a file unit.
- ``read_script`` reads a hook script ``write_file`` may write (None when absent; a link on the
  way or at it ``link_in_path``, another non-regular file ``HubItemWriteError``), at most one byte
  past ``MAX_SKILL_FILE_BYTES``: enough to tell it from a draft's script.
- ``remove_unit`` removes a unit (a rename's old unit), a skill folder whole, its hidden entries
  too (a rename has carried them to the new folder first, through ``carry_from``); an absent one
  is fine.
- ``read_draft`` reads a Studio draft, ``.hub-drafts/<draft_id>/``, whole (``DraftFiles``),
  bounded as a skill folder unit (S8) but with its hidden names, which publish refuses:
  ``EntityNotFoundError`` (entity ``draft``) when the folder is missing, empty or no folder,
  ``ItemWriteRefusedError("link_in_path")`` when it, the drafts folder or anything in it is a
  link or a special file, ``DraftTooLargeError`` past the bounds. The draft is untrusted (a
  Claude session wrote it): never followed through a link, each file's executable bit from the
  opened file.
- ``remove_draft`` removes that folder whole, a link inside it removed and never followed, a link
  at the folder or the drafts folder refused (``link_in_path``), a file at the draft's path or a
  ``.hub-drafts`` that is a file a ``HubItemWriteError``; an absent draft is fine.

A refusal is ``ItemWriteRefusedError`` (``hub_read_only`` or ``link_in_path``); any other I/O
failure is ``HubItemWriteError``. Its ``kind`` is ``failed`` when the unit was left as it was,
and ``rollback_failed`` when a folder swap failed and putting the old folder back failed too:
the unit's name may then be missing, and two ``.<name>.hub-tmp-<8 hex>`` folders stay beside
it, which ``hub doctor``'s ``items.leftovers`` lists: the stage (the version, with the hidden
entries moved into it and not put back) and the old folder (the rest of the old content).
No message names a path. A unit path that is not a unit of its kind, or a path that is not
plain and relative, is a caller bug (``ValueError``).
"""

import re
from collections.abc import Sequence
from typing import Annotated, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.errors import AgentHubError
from agent_hub.core.item_versions.item_units import unit_parts
from agent_hub.core.item_versions.item_version import DRAFT_ID, UnitKind
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent
from agent_hub.core.skills.skill_sources import (
    DEFAULT_LIMITS,
    MAX_SKILL_FILE_BYTES,
    PLUGIN_FOLDER,
    SkillPathError,
)

# Where the Studio's drafts live in a hub, outside ``plugin/`` and ``.claude/`` so nothing loads
# them.
DRAFTS_FOLDER: Final = ".hub-drafts"
_DRAFT_ID: Final = re.compile(DRAFT_ID)
# The bounds a draft is read within, in the words a 413 answer gives.
DRAFT_LIMIT: Final = (
    f"a draft holds at most {MAX_UNIT_FILES} files of {MAX_SKILL_FILE_BYTES} bytes each, "
    f"at most {DEFAULT_LIMITS.skill_depth} segments deep"
)

_NOT_PLAIN: Final = frozenset({"", ".", ".."})
_SCRIPT_FOLDERS: Final = frozenset({"scripts"})
# ``plugin/<p>/<folder>/<name>`` at the least, ``skill_depth`` segments below the folder at most.
_SCRIPT_MIN_SEGMENTS: Final = 4
_SCRIPT_MAX_SEGMENTS: Final = 3 + DEFAULT_LIMITS.skill_depth

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


# Whether a failed write left the unit as it was (``failed``), could not put it back
# (``rollback_failed``), or wrote and recorded a rename's new unit but could not remove the old
# one (``old_not_removed``, A18; raised by ``RecordAndWrite``, never by a writer).
type WriteFailure = Literal["failed", "rollback_failed", "old_not_removed"]
ROLLBACK_FAILED_CAUSE: Final = "the old folder was not put back"
OLD_NOT_REMOVED_CAUSE: Final = "the renamed item's old unit was not removed"


class HubItemWriteError(AgentHubError):
    """A write that failed on I/O. ``kind`` ``failed``: the hub keeps the unit as it was;
    ``rollback_failed``: the old folder could not be put back either (see the module);
    ``old_not_removed``: a rename's new unit is written and recorded, its old unit stays. No
    path is named."""

    def __init__(self, cause: str = "the write failed", *, kind: WriteFailure = "failed") -> None:
        self.cause = cause
        self.kind: WriteFailure = kind
        super().__init__(f"item write failed: {cause}")


def rollback_failed() -> HubItemWriteError:
    """The error of a folder swap whose roll back failed too."""
    return HubItemWriteError(ROLLBACK_FAILED_CAUSE, kind="rollback_failed")


def old_not_removed() -> HubItemWriteError:
    """The error of a rename whose old unit could not be removed after the new one was
    written and recorded (A18)."""
    return HubItemWriteError(OLD_NOT_REMOVED_CAUSE, kind="old_not_removed")


class DraftTooLargeError(AgentHubError):
    """A draft past the bounds a unit is read within (answers 413); ``limit`` says them."""

    def __init__(self) -> None:
        self.limit = DRAFT_LIMIT
        super().__init__(f"draft too large: {DRAFT_LIMIT}")


class DraftFiles(BaseModel):
    """A Studio draft read whole: its id and every file in it, hidden ones included, with their
    executable bits; ``kind`` is its id's prefix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_id: Annotated[str, Field(pattern=DRAFT_ID)]
    content: UnitContent

    @property
    def kind(self) -> UnitKind:
        """The draft's kind, from its id."""
        return UnitKind(self.draft_id.partition("-")[0])


def draft_parts(draft_id: str) -> tuple[str, str]:
    """The draft folder's hub-relative segments, or ``ValueError`` naming no id when
    ``draft_id`` is outside ``(skill|agent|hook)-[a-z0-9]{6}`` (the route refuses it first)."""
    if not _DRAFT_ID.fullmatch(draft_id):
        msg = "not a draft id"
        raise ValueError(msg)
    return (DRAFTS_FOLDER, draft_id)


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


def script_parts(path: str) -> tuple[str, ...]:
    """``path``'s segments when it is a hook's script ``write_file`` may write:
    ``plugin/<p>/scripts/…``, plain, no hidden segment, at most ``skill_depth`` segments below
    that folder; else ``ValueError`` naming no path."""
    parts = plain_parts(path)
    shaped = (
        _SCRIPT_MIN_SEGMENTS <= len(parts) <= _SCRIPT_MAX_SEGMENTS
        and parts[0] == PLUGIN_FOLDER
        and parts[2] in _SCRIPT_FOLDERS
        and not any(segment.startswith(".") for segment in parts)
    )
    if not shaped:
        msg = "not a hook script path"
        raise ValueError(msg)
    return parts


def checked_carry_parts(
    unit_path: str, carry_from: str | None, *, kind: UnitKind
) -> tuple[str, ...] | None:
    """``carry_from``'s segments when it is a skill folder beside ``unit_path`` (another name in
    the same folder), None when it is None; else ``ValueError`` naming no path."""
    if carry_from is None:
        return None
    parts = checked_unit_parts(carry_from, UnitKind.SKILL)
    target = checked_unit_parts(unit_path, kind)
    if kind is not UnitKind.SKILL or parts[:-1] != target[:-1] or parts == target:
        msg = "carry_from is not a sibling skill folder"
        raise ValueError(msg)
    return parts


def check_version_names(content: UnitContent) -> None:
    """Refuse a folder version holding a hidden name (``ValueError``, naming no path): the
    reader never records one, and the swap keeps the disk's hidden entries."""
    if any(segment.startswith(".") for file in content.files for segment in file.path.split("/")):
        msg = "a version holds a hidden name"
        raise ValueError(msg)


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
        self,
        hub_path: str,
        unit_path: str,
        content: UnitContent,
        *,
        kind: UnitKind,
        carry_from: str | None = None,
    ) -> None:
        """Make the unit at ``unit_path`` equal to ``content``; a skill written with
        ``carry_from`` takes that sibling folder's hidden entries."""
        ...

    def read_script(self, hub_path: str, path: str) -> bytes | None:
        """The hook script ``path``'s bytes (``script_parts``), None when absent."""
        ...

    def write_file(
        self, hub_path: str, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        """Write the hook script ``path`` (``script_parts``) through a temp file and a rename."""
        ...

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        """Remove the unit at ``unit_path``, a folder with its hidden entries; absent is fine."""
        ...

    def read_draft(self, hub_path: str, draft_id: str) -> DraftFiles:
        """The draft ``.hub-drafts/<draft_id>/`` read whole, within the bounds."""
        ...

    def remove_draft(self, hub_path: str, draft_id: str) -> None:
        """Remove the draft's folder whole; absent is fine."""
        ...
