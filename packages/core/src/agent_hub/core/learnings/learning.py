"""The Learning read model: a proposal and its first terminal decision (read-only in Phase 2)."""

from enum import StrEnum
from typing import Literal

from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import ApiTimestamp, DerivedView, ViewModel


class LearningStatus(StrEnum):
    """Where a learning is: proposed until a terminal event in source order decides it."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LearningTarget(ViewModel):
    """Where a learning would go: team brain, a repo's AGENTS.md, or personal memory."""

    kind: Literal["team", "repo", "personal"] | None
    path: str | None


class Learning(DerivedView):
    """A learning; ``text`` is its title (120 characters at most, redacted)."""

    id: str
    project: str
    text: str
    target: LearningTarget
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
