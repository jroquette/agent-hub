"""The pure path rules of the brain browser and the learning actions (S8, L6, L9, AC-201.34).

Every path here is relative to the hub's ``brain/`` folder with ``/`` separators, except a
learning's ``note_path``, which is relative to the hub root (``brain/_inbox/<name>.md``). A path
is refused before any file is opened: these rules never touch the disk, so the adapter that
reads still refuses links and non-regular files on its own.
"""

import re
from pathlib import PurePosixPath
from typing import Final, Literal

from agent_hub.core.errors import AgentHubError

MAX_NOTE_BYTES: Final = 262_144
MAX_PATH_CHARS: Final = 512
MAX_SEGMENTS: Final = 16
NOTE_SUFFIX: Final = ".md"
BRAIN_FOLDER: Final = "brain"
INBOX_FOLDER: Final = "_inbox"
ARCHIVE_FOLDER: Final = "_archive"
# Never listed or served (L7): the developer's personal, gitignored memory.
PERSONAL_FOLDER: Final = "auto"
# Folders a learning may not be accepted into: the inbox itself, personal memory, and decisions,
# which are superseded and never edited.
REFUSED_DESTINATIONS: Final = frozenset({INBOX_FOLDER, PERSONAL_FOLDER, "decisions"})
MAX_SLUG_CHARS: Final = 50

type LearningAction = Literal["accept", "reject"]

# A note inside a folder has at least a folder segment and its name.
_FOLDER_AND_NAME: Final = 2
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_NOT_SLUG: Final = re.compile(r"[^a-z0-9]+")


class BrainPathError(AgentHubError):
    """A path the brain rules refuse; ``reason`` says why in the owner's words."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _refuse_characters(path: str) -> None:
    if not path:
        raise BrainPathError("Path is empty")
    if len(path) > MAX_PATH_CHARS:
        raise BrainPathError(f"Path is longer than {MAX_PATH_CHARS} characters")
    if "\\" in path or _CONTROL.search(path):
        raise BrainPathError("Path holds a backslash or a control character")
    if path.startswith("/"):
        raise BrainPathError("Path must be relative to brain/")


def _refuse_segments(segments: list[str]) -> None:
    if len(segments) > MAX_SEGMENTS:
        raise BrainPathError(f"Path is deeper than {MAX_SEGMENTS} folders")
    if any(not segment or segment.startswith(".") for segment in segments):
        raise BrainPathError("Path has an empty, hidden or parent segment")
    if segments[0] == PERSONAL_FOLDER:
        raise BrainPathError("brain/auto/ is personal memory and is never served")
    last = segments[-1]
    if not last.endswith(NOTE_SUFFIX) or len(last) == len(NOTE_SUFFIX):
        raise BrainPathError("Only .md notes are served")


def brain_relative(path: str) -> PurePosixPath:
    """``path`` as a note path under ``brain/``, or ``BrainPathError`` naming the reason.

    Refused: an empty, absolute or over-long path, a backslash or control character, an empty,
    hidden, ``.`` or ``..`` segment, more than ``MAX_SEGMENTS`` segments, ``auto/``, and a name
    not ending in ``.md``.
    """
    _refuse_characters(path)
    segments = path.split("/")
    _refuse_segments(segments)
    return PurePosixPath(*segments)


def inbox_note(note_path: str) -> PurePosixPath:
    """A learning's ``note_path`` (``brain/_inbox/<name>.md``, hub-relative) as a brain path.

    Refused when it is not under ``brain/_inbox/`` or is already in ``_inbox/_archive/``.
    """
    outside = BrainPathError("Note outside brain/_inbox/")
    prefix = f"{BRAIN_FOLDER}/"
    if not note_path.startswith(prefix):
        raise outside
    note = brain_relative(note_path.removeprefix(prefix))
    parts = note.parts
    if len(parts) < _FOLDER_AND_NAME or parts[0] != INBOX_FOLDER or parts[1] == ARCHIVE_FOLDER:
        raise outside
    return note


def accept_destination(target: str, note: PurePosixPath) -> str:
    """Where an accepted ``note`` goes: ``target`` when it names a ``.md`` file, else the note's
    name inside the folder ``target``; always inside a folder of the brain.

    Refused: any path ``brain_relative`` refuses, a note at the brain's root, and the folders
    ``_inbox``, ``auto`` and ``decisions``.
    """
    cleaned = target.strip()
    if cleaned.endswith(NOTE_SUFFIX):
        destination = brain_relative(cleaned)
    else:
        folder = cleaned.rstrip("/")
        destination = brain_relative(f"{folder}/{note.name}" if folder else "")
    if len(destination.parts) < _FOLDER_AND_NAME:
        raise BrainPathError("Pick a folder of the brain")
    if destination.parts[0] in REFUSED_DESTINATIONS:
        raise BrainPathError(f"A learning cannot be accepted into {destination.parts[0]}/")
    return str(destination)


def archive_destination(note: PurePosixPath) -> str:
    """Where a rejected ``note`` goes (L6): ``_inbox/_archive/<name>``."""
    return f"{INBOX_FOLDER}/{ARCHIVE_FOLDER}/{note.name}"


def branch_slug(note: PurePosixPath) -> str:
    """The note's name as a branch-safe slug: lowercase ``a-z0-9`` words joined by ``-``, at most
    ``MAX_SLUG_CHARS`` characters, ``note`` when nothing is left."""
    slug = _NOT_SLUG.sub("-", note.stem.lower()).strip("-")
    return slug[:MAX_SLUG_CHARS].rstrip("-") or "note"


def learning_branch(*, branch_prefix: str, action: LearningAction, note: PurePosixPath) -> str:
    """The branch an app-opened PR uses (L5): ``<prefix>learning-<action>-<note slug>``."""
    return f"{branch_prefix}learning-{action}-{branch_slug(note)}"
