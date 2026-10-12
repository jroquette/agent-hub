"""The Learning read model: a proposal, its first terminal decision and, read on request from
the hub, its note and what the app may do with it (AGH-201)."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from agent_hub.core.brain.brain_note import BrainNote
from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import (
    DEPRECATED_FIELD,
    ApiTimestamp,
    DerivedView,
    ViewModel,
)


class LearningStatus(StrEnum):
    """Where a learning is: proposed until a terminal event in source order decides it."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LearningState(StrEnum):
    """Where the learning's note is (L11): in the inbox, in an open PR, or moved by a merge.

    ``in_brain`` and ``archived`` are inferred from the hub checkout (the note sits at its
    destination), since GitHub is not connected.
    """

    PROPOSED = "proposed"
    ACCEPTED_PR_OPEN = "accepted_pr_open"
    REJECTED_PR_OPEN = "rejected_pr_open"
    IN_BRAIN = "in_brain"
    ARCHIVED = "archived"


class LearningTarget(ViewModel):
    """Where a learning would go: team brain, a repo's AGENTS.md, or personal memory."""

    kind: Literal["team", "repo", "personal"] | None
    path: str | None


class Learning(DerivedView):
    """A learning; ``text`` is its title (120 characters at most, redacted).

    ``target`` is deprecated (it names the inbox note); ``note_path`` says so explicitly (L12).
    ``state`` is ``None`` until read with the hub. ``summary`` is the note's first paragraph,
    read on request; ``note_unavailable`` and ``actions_unavailable`` give the reason the note
    cannot be read or the learning cannot be accepted or rejected here.
    """

    id: str
    project: str
    text: str
    target: LearningTarget = Field(json_schema_extra=DEPRECATED_FIELD)
    author: str | None
    provenance: Literal["human", "agent", "agent-from-code", "agent-from-external"] | None
    status: LearningStatus
    source_session_id: str | None
    source_event_id: EventId | None
    proposed_at: ApiTimestamp | None
    decided_at: ApiTimestamp | None = None
    decided_by: str | None = None
    brain_path: str | None = None
    commit: str | None = None
    rejection_reason: str | None = None
    note_path: str | None = None
    state: LearningState | None = None
    summary: str | None = None
    note_unavailable: str | None = None
    actions_unavailable: str | None = None
    pr_url: str | None = None
    branch: str | None = None


class LearningDetail(Learning):
    """A learning with its note (``None`` when unavailable), the destination folder the accept
    dialog suggests and the folders it offers (L9)."""

    note: BrainNote | None = None
    suggested_target: str
    target_choices: tuple[str, ...] = ()


class LearningActionResult(ViewModel):
    """What an accept or reject did: the pull request it opened and its branch."""

    state: LearningState
    pr_url: str
    branch: str
