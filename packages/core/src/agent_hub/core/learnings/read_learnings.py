"""Learnings read with their hub's inbox note: the ``LearningReads`` use case (L9 to L11).

The folded learnings come from the event store; the note is read from the registered hub's
checkout on request and never stored. A list reads at most ``SUMMARY_READ_BYTES`` of each note
for its summary, the detail at most ``MAX_NOTE_BYTES``. A learning whose note cannot be read
says why in ``note_unavailable`` (L10); one that cannot be accepted or rejected here says why
in ``actions_unavailable``. ``in_brain`` and ``archived`` are inferred from where the note sits
in the checkout once its PR is merged and pulled (L11).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, Protocol

from agent_hub.core.brain.brain_note import BrainNote
from agent_hub.core.brain.brain_path import (
    BRAIN_FOLDER,
    DEFAULT_ACCEPT_FOLDER,
    MAX_NOTE_BYTES,
    NOTE_SUFFIX,
    BrainPathError,
    accept_destination,
    archive_destination,
    brain_relative,
    inbox_note,
    is_refused_destination,
)
from agent_hub.core.brain.frontmatter import Frontmatter, first_paragraph, split_frontmatter
from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadHubFile
from agent_hub.core.learnings.learning import (
    Learning,
    LearningDetail,
    LearningState,
    LearningStatus,
)
from agent_hub.core.learnings.learning_ports import LearningHub
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.readmodels.page import Page

# The most a list reads of one note for its summary.
SUMMARY_READ_BYTES: Final = 16 * 1024
HUB_NOT_REGISTERED: Final = "Hub not registered"
NOTE_NOT_IN_CHECKOUT: Final = "Note not in the hub checkout"
NOTE_OUTSIDE_INBOX: Final = "Note outside brain/_inbox/"
NOTE_TOO_LARGE: Final = "Note too large"
NOT_REGULAR_FILE: Final = "Not a regular file"
NOTE_UNREADABLE: Final = "Note could not be read"

_UNREAD_REASONS: Final = {
    "missing": NOTE_NOT_IN_CHECKOUT,
    "not_regular": NOT_REGULAR_FILE,
    "too_large": NOTE_TOO_LARGE,
}
_BRAIN_PREFIX: Final = f"{BRAIN_FOLDER}/"


@dataclass(frozen=True, kw_only=True, slots=True)
class UnavailableHub:
    """Why a project's hub cannot take learning actions (``reason``); ``path`` is its checkout
    when it is registered, so its notes can still be read, and None when it is not."""

    reason: str
    path: str | None = None


type HubLookup = Callable[[str], LearningHub | UnavailableHub]
type Availability = Callable[[str], str | None]


class FoldedLearnings(Protocol):
    """The learnings folded from the event store (``EventReadModels`` has these two)."""

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """Learnings matching the filter."""
        ...

    def get_learning(self, learning_id: str) -> Learning:
        """One learning; ``EntityNotFoundError`` when no learning has the id."""
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class _NoteRead:
    """A learning's note as read: its text split, or why it is unavailable."""

    location: PurePosixPath | None = None
    split: Frontmatter | None = None
    size: int = 0
    unavailable: str | None = None


def _inbox_location(learning: Learning) -> PurePosixPath:
    if learning.note_path is None:
        raise BrainPathError(NOTE_OUTSIDE_INBOX)
    return inbox_note(learning.note_path)


def _moved_to(learning: Learning) -> str | None:
    """Where the note goes once the decision's PR is merged (brain-relative), if known."""
    try:
        if learning.status == LearningStatus.ACCEPTED and learning.brain_path is not None:
            return str(brain_relative(learning.brain_path.removeprefix(_BRAIN_PREFIX)))
        if learning.status == LearningStatus.REJECTED:
            return archive_destination(_inbox_location(learning))
    except BrainPathError:
        return None
    return None


def _hub_reason(hub: LearningHub | UnavailableHub) -> str:
    return hub.reason if isinstance(hub, UnavailableHub) else HUB_NOT_REGISTERED


class ReadLearnings:
    """The ``LearningReads`` port over the folded learnings and the hubs' files.

    ``hub_of`` names a project's hub (or why it cannot take actions); ``availability`` is the
    change-request adapter's own check of a hub checkout (``BrainChangeRequests.availability``).
    """

    def __init__(
        self,
        events: FoldedLearnings,
        files: HubFileReader,
        *,
        hub_of: HubLookup,
        availability: Availability,
    ) -> None:
        self._events = events
        self._files = files
        self._hub_of = hub_of
        self._availability = availability

    def list_learnings(self, learning_filter: LearningFilter) -> Page[Learning]:
        """Learnings matching the filter, each with its summary or why its note is unavailable."""
        page = self._events.list_learnings(learning_filter)
        hubs: dict[str, tuple[LearningHub | UnavailableHub, str | None]] = {}
        items: list[Learning] = []
        for learning in page.items:
            if learning.project not in hubs:
                hub = self._hub_of(learning.project)
                hubs[learning.project] = (hub, self._actions_unavailable(hub))
            hub, actions = hubs[learning.project]
            state = self._state(learning, hub)
            read = self._read(learning, hub, state, max_bytes=SUMMARY_READ_BYTES)
            items.append(learning.model_copy(update=self._fields(read, state, actions)))
        return page.model_copy(update={"items": tuple(items)})

    def get_learning(self, learning_id: str) -> LearningDetail:
        """One learning with its note, the suggested destination and the folders offered."""
        learning = self._events.get_learning(learning_id)
        hub = self._hub_of(learning.project)
        state = self._state(learning, hub)
        read = self._read(learning, hub, state, max_bytes=MAX_NOTE_BYTES)
        fields = self._fields(read, state, self._actions_unavailable(hub))
        hub_path = hub.path
        note = None
        if read.split is not None and read.location is not None:
            note = BrainNote(
                project=learning.project,
                path=str(read.location),
                frontmatter=read.split.fields,
                frontmatter_problem=read.split.problem,
                markdown=read.split.body,
                size=read.size,
            )
        return LearningDetail.model_validate(
            learning.model_dump()
            | fields
            | {
                "note": note,
                "suggested_target": self._suggested_target(read, hub_path),
                "target_choices": self._target_choices(hub_path),
            }
        )

    def _actions_unavailable(self, hub: LearningHub | UnavailableHub) -> str | None:
        if isinstance(hub, UnavailableHub):
            return hub.reason
        return self._availability(hub.path)

    def _state(self, learning: Learning, hub: LearningHub | UnavailableHub) -> LearningState | None:
        if learning.status == LearningStatus.PROPOSED:
            return LearningState.PROPOSED
        hub_path = hub.path
        moved_to = _moved_to(learning)
        if hub_path is None or moved_to is None:
            return learning.state
        if self._files.brain_file_size(hub_path, moved_to) is None:
            return learning.state
        if learning.status == LearningStatus.ACCEPTED:
            return LearningState.IN_BRAIN
        return LearningState.ARCHIVED

    def _read(
        self,
        learning: Learning,
        hub: LearningHub | UnavailableHub,
        state: LearningState | None,
        *,
        max_bytes: int,
    ) -> _NoteRead:
        hub_path = hub.path
        if hub_path is None:
            return _NoteRead(unavailable=_hub_reason(hub))
        try:
            location = _inbox_location(learning)
        except BrainPathError as error:
            return _NoteRead(unavailable=error.reason)
        moved_to = _moved_to(learning)
        if state in {LearningState.IN_BRAIN, LearningState.ARCHIVED} and moved_to is not None:
            location = PurePosixPath(moved_to)
        content = self._files.read_brain_file(hub_path, str(location), max_bytes=max_bytes)
        if isinstance(content, UnreadHubFile):
            return _NoteRead(
                location=location, unavailable=self._unread(hub_path, location, content)
            )
        text = content.decode("utf-8", errors="replace")
        return _NoteRead(location=location, split=split_frontmatter(text), size=len(content))

    def _unread(self, hub_path: str, location: PurePosixPath, unread: UnreadHubFile) -> str | None:
        if unread.kind == "too_large":
            # Over the summary bound only: the note is fine, the list just shows no summary.
            size = self._files.brain_file_size(hub_path, str(location))
            return NOTE_TOO_LARGE if size is None or size > MAX_NOTE_BYTES else None
        if unread.kind is None:
            return NOTE_NOT_IN_CHECKOUT if unread.is_missing else NOTE_UNREADABLE
        return _UNREAD_REASONS.get(unread.kind, NOTE_UNREADABLE)

    @staticmethod
    def _fields(
        read: _NoteRead, state: LearningState | None, actions: str | None
    ) -> dict[str, object]:
        summary = None if read.split is None else first_paragraph(read.split.body) or None
        if actions is None and state == LearningState.PROPOSED:
            # A note the owner cannot read here is not decided from here.
            actions = read.unavailable
        return {
            "state": state,
            "summary": summary,
            "note_unavailable": read.unavailable,
            "actions_unavailable": actions,
        }

    def _suggested_target(self, read: _NoteRead, hub_path: str | None) -> str:
        """The note's frontmatter ``target:`` under ``brain/`` as a destination (its folder when
        the note it names exists already, since a move never overwrites), else ``learnings/``
        (L9)."""
        target = None if read.split is None else read.split.fields.get("target")
        # /learn writes the target hub-relative; a repo's AGENTS.md or a rule is not the brain.
        if not isinstance(target, str) or not target.startswith(_BRAIN_PREFIX):
            return DEFAULT_ACCEPT_FOLDER
        if read.location is None:
            return DEFAULT_ACCEPT_FOLDER
        cleaned = target.strip().removeprefix(_BRAIN_PREFIX)
        try:
            destination = accept_destination(cleaned, read.location)
        except BrainPathError:
            return DEFAULT_ACCEPT_FOLDER
        if not cleaned.endswith(NOTE_SUFFIX):
            return f"{cleaned.rstrip('/')}/"
        if hub_path is not None and self._files.brain_file_size(hub_path, destination) is not None:
            return f"{PurePosixPath(destination).parent}/"
        return destination

    def _target_choices(self, hub_path: str | None) -> tuple[str, ...]:
        """The brain's top folders a learning may go to, plus ``learnings/`` (L9)."""
        folders = {DEFAULT_ACCEPT_FOLDER}
        if hub_path is not None:
            for entry in self._files.brain_tree(hub_path).entries:
                parts = PurePosixPath(entry.path).parts
                if len(parts) > 1 and not is_refused_destination(parts[0]):
                    folders.add(f"{parts[0]}/")
        return tuple(sorted(folders))
