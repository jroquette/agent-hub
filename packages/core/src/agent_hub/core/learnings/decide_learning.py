"""Accept or reject a learning from the app: the ``LearningDecisions`` use case (ADR 0024).

The order is fixed: the learning's state, the hub's availability, the destination rules, the
change (title, body and reason redacted with r1), the port that opens the hub pull request,
then one ``learning.accepted`` or ``learning.rejected`` event from the ``control_plane`` source.
A refusal or a failed port call stores nothing. One action runs per hub at a time: a second one
started meanwhile is refused, not queued.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import PurePosixPath
from typing import Final

from pydantic import JsonValue

from agent_hub.core.brain.brain_path import (
    BRAIN_FOLDER,
    MAX_NOTE_BYTES,
    BrainPathError,
    LearningAction,
    accept_destination,
    archive_destination,
    branch_slug,
    inbox_note,
    learning_branch,
)
from agent_hub.core.brain.frontmatter import first_paragraph
from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    BrainChangeRequests,
    ChangeRequestResult,
)
from agent_hub.core.learnings.learning import (
    LearningActionResult,
    LearningDetail,
    LearningState,
    LearningStatus,
)
from agent_hub.core.learnings.learning_ports import (
    HubReadOnlyError,
    LearningConflictError,
    LearningHub,
    LearningReads,
)
from agent_hub.core.learnings.read_learnings import NOTE_OUTSIDE_INBOX, HubLookup
from agent_hub.core.redaction.redact import clip, redact_text

CONTROL_PLANE_SESSION: Final = "control-plane"
CONTROL_PLANE_AGENT: Final = "you"
MAX_TITLE_CHARS: Final = 72
MAX_SUMMARY_CHARS: Final = 200
MAX_REASON_CHARS: Final = 300
ACTION_RUNNING: Final = "Another learning action is running for this hub"
REASON_REQUIRED: Final = "A reason is required to reject a learning"
EDIT_EMPTY: Final = "The edited note is empty"
EDIT_TOO_LARGE: Final = "The edited note is larger than the note size limit"

_ALREADY: Final = {
    LearningState.ACCEPTED_PR_OPEN: "Learning already accepted, PR open",
    LearningState.REJECTED_PR_OPEN: "Learning already rejected, PR open",
    LearningState.IN_BRAIN: "Learning already in the brain",
    LearningState.ARCHIVED: "Learning already archived",
}
_DECIDED: Final = {
    LearningStatus.ACCEPTED: "Learning already accepted",
    LearningStatus.REJECTED: "Learning already rejected",
}
_EVENT_TYPE: Final[dict[LearningAction, EventType]] = {
    "accept": EventType.LEARNING_ACCEPTED,
    "reject": EventType.LEARNING_REJECTED,
}
_PR_OPEN: Final[dict[LearningAction, LearningState]] = {
    "accept": LearningState.ACCEPTED_PR_OPEN,
    "reject": LearningState.REJECTED_PR_OPEN,
}
_VERB: Final[dict[LearningAction, str]] = {"accept": "Accept", "reject": "Reject"}


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _redacted(text: str, limit: int) -> str:
    """``text`` redacted (r1), whitespace collapsed, then clipped (redaction goes first)."""
    return clip(_one_line(redact_text(text)), limit)


def _refuse_decided(learning: LearningDetail) -> None:
    if learning.status == LearningStatus.PROPOSED:
        return
    reason = _ALREADY.get(learning.state) if learning.state is not None else None
    raise LearningConflictError(
        reason or _DECIDED.get(learning.status, "Learning already decided"),
        pr_url=learning.pr_url,
    )


def _edited_body(note_body: str | None) -> str | None:
    """The edited note body, refused when blank or past the note size limit."""
    if note_body is None:
        return None
    if not note_body.strip():
        raise LearningConflictError(EDIT_EMPTY)
    if len(note_body.encode("utf-8")) > MAX_NOTE_BYTES:
        raise LearningConflictError(EDIT_TOO_LARGE)
    return note_body


def _note(learning: LearningDetail) -> PurePosixPath:
    if learning.note_path is None:
        raise LearningConflictError(NOTE_OUTSIDE_INBOX)
    try:
        note = inbox_note(learning.note_path)
    except BrainPathError as error:
        raise LearningConflictError(error.reason) from None
    if learning.note_unavailable is not None:
        raise LearningConflictError(learning.note_unavailable)
    return note


class DecideLearning:
    """The ``LearningDecisions`` port: opens the hub PR through ``changes`` and stores the event.

    ``hub_of`` names a project's hub (as ``ReadLearnings`` does); ``today`` is the clock that
    stamps the event and the frontmatter dates.
    """

    def __init__(
        self,
        reads: LearningReads,
        ingest: IngestEvents,
        changes: BrainChangeRequests,
        *,
        hub_of: HubLookup,
        today: Callable[[], datetime],
    ) -> None:
        self._reads = reads
        self._ingest = ingest
        self._changes = changes
        self._hub_of = hub_of
        self._today = today
        self._guard = threading.Lock()
        self._running: set[str] = set()

    def accept(
        self, learning_id: str, *, target: str, note_body: str | None = None
    ) -> LearningActionResult:
        """Open a PR that moves the note to ``target`` (a folder or a ``.md`` path); with
        ``note_body``, the same commit replaces the note's text after its frontmatter."""
        return self._decide(learning_id, "accept", target=target, reason="", note_body=note_body)

    def reject(self, learning_id: str, *, reason: str) -> LearningActionResult:
        """Open a PR that archives the note with ``reason``."""
        return self._decide(learning_id, "reject", target="", reason=reason)

    def _decide(
        self,
        learning_id: str,
        action: LearningAction,
        *,
        target: str,
        reason: str,
        note_body: str | None = None,
    ) -> LearningActionResult:
        hub = self._usable_hub(self._reads.get_learning(learning_id).project)
        with self._one_action(hub.path):
            # Read again inside the lock: an action that just ended has stored its event.
            learning = self._reads.get_learning(learning_id)
            _refuse_decided(learning)
            unavailable = self._changes.availability(hub.path)
            if unavailable is not None:
                raise HubReadOnlyError(unavailable)
            now = self._today()
            change = self._change(
                learning, hub, action, target=target, reason=reason, note_body=note_body, now=now
            )
            opened = (
                self._changes.accept(change) if action == "accept" else self._changes.reject(change)
            )
            state = _PR_OPEN[action]
            event = self._event(learning, change=change, state=state, opened=opened, now=now)
            self._ingest.execute([event])
        return LearningActionResult(state=state, pr_url=opened.pr_url, branch=opened.branch)

    def _usable_hub(self, project: str) -> LearningHub:
        hub = self._hub_of(project)
        if not isinstance(hub, LearningHub):
            raise HubReadOnlyError(hub.reason)
        return hub

    @contextmanager
    def _one_action(self, hub_path: str) -> Iterator[None]:
        with self._guard:
            if hub_path in self._running:
                raise LearningConflictError(ACTION_RUNNING)
            self._running.add(hub_path)
        try:
            yield
        finally:
            with self._guard:
                self._running.discard(hub_path)

    def _change(
        self,
        learning: LearningDetail,
        hub: LearningHub,
        action: LearningAction,
        *,
        target: str,
        reason: str,
        note_body: str | None,
        now: datetime,
    ) -> BrainChange:
        note = _note(learning)
        edited = _edited_body(note_body)
        day = now.date().isoformat()
        why = _redacted(reason, MAX_REASON_CHARS)
        try:
            if action == "accept":
                destination = accept_destination(target, note)
                frontmatter = {"status": "accepted", "last_verified": day}
            else:
                if not why:
                    raise LearningConflictError(REASON_REQUIRED)
                destination = archive_destination(note)
                frontmatter = {"status": "rejected", "rejected_reason": why, "rejected_at": day}
        except BrainPathError as error:
            raise LearningConflictError(error.reason) from None
        title = _redacted(f"{_VERB[action]} learning: {learning.text}", MAX_TITLE_CHARS)
        return BrainChange(
            hub_path=hub.path,
            hub_repo=hub.hub_repo,
            default_branch=hub.default_branch,
            action=action,
            note=str(note),
            destination=destination,
            frontmatter=frontmatter,
            note_body=edited,
            author=hub.author,
            branch=learning_branch(branch_prefix=hub.branch_prefix, action=action, note=note),
            title=title,
            body=self._body(learning, note=note, destination=destination, why=why, edited=edited),
            commit_message=f"docs(brain): {action} learning {branch_slug(note)}",
        )

    @staticmethod
    def _body(
        learning: LearningDetail,
        *,
        note: PurePosixPath,
        destination: str,
        why: str,
        edited: str | None = None,
    ) -> str:
        """The PR body: the move, whether the note was edited, its first paragraph and, for a
        reject, the reason."""
        lines = [f"Moves `{BRAIN_FOLDER}/{note}` to `{BRAIN_FOLDER}/{destination}`."]
        if edited is not None:
            lines += ["", "The note was edited in agent-hub before it was accepted."]
        summary = first_paragraph(edited) if edited is not None else learning.summary
        if summary:
            lines += ["", f"> {_redacted(summary, MAX_SUMMARY_CHARS)}"]
        if why:
            lines += ["", f"Reason: {why}"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _event(
        learning: LearningDetail,
        *,
        change: BrainChange,
        state: LearningState,
        opened: ChangeRequestResult,
        now: datetime,
    ) -> Event:
        decision = "accepted" if change.action == "accept" else "rejected"
        payload: dict[str, JsonValue] = {
            "proposal": learning.id,
            "brain_path": f"{BRAIN_FOLDER}/{change.destination}",
            "pr_url": opened.pr_url,
            "branch": opened.branch,
            "state": state.value,
            "author": CONTROL_PLANE_AGENT,
        }
        if change.action == "reject":
            payload["reason"] = change.frontmatter["rejected_reason"]
        return Event(
            project=learning.project,
            session=CONTROL_PLANE_SESSION,
            type=_EVENT_TYPE[change.action],
            timestamp=now,
            source=EventSource.CONTROL_PLANE,
            source_id=f"learning:{learning.id}:{decision}",
            payload=payload,
            agent=CONTROL_PLANE_AGENT,
        )
