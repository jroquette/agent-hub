"""The Approval read model: a gate request waiting for a person, or how it was decided (D24)."""

from enum import StrEnum
from typing import Literal

from agent_hub.core.events.stored_event import EventId
from agent_hub.core.readmodels.view_types import ApiTimestamp, DerivedView


class ApprovalKind(StrEnum):
    """The kinds of request D24 lists."""

    GUARD_ASK = "guard_ask"
    PLAN = "plan"
    SPEC = "spec"
    HUMAN_GATE = "human_gate"
    PERMISSION = "permission"


type ApprovalStatus = Literal["open", "approved", "declined", "changes_requested", "rejected"]


class Approval(DerivedView):
    """An approval. ``decided`` once a matching result exists; ``inferred`` when the decision is
    deduced (a guard ask with no tool run before the next prompt or stop is declined).

    ``how_to_decide`` is the terminal command that answers it, since Phase 2 is read-only:
    ``cd <hub path> && claude --resume <session id>``.
    """

    id: str
    project: str
    repo: str | None
    kind: ApprovalKind
    title: str
    status: ApprovalStatus
    decided: bool
    inferred: bool = False
    gate_id: str
    session_id: str
    requested_by: str | None
    requested_at: ApiTimestamp
    decided_at: ApiTimestamp | None = None
    issue: str | None = None
    path: str | None = None
    rule: str | None = None
    feature: str | None = None
    hub_path: str | None = None
    how_to_decide: str | None = None
    request_event_id: EventId
    decision_event_id: EventId | None = None
