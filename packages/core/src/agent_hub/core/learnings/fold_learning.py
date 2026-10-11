"""Learnings folded from ``learning.proposed``/``.accepted``/``.rejected`` (AC-200.26).

A learning exists once its proposal is stored. Its first terminal event in source order
(timestamp, then identity) decides it, whatever order the events arrived in; a decision stored
before its proposal applies as soon as the proposal arrives. Events name the learning by
``proposal``; a proposal that comes from a Write under ``brain/_inbox/`` has no proposal id and
is named by its path, which a decision may name instead (``brain_path`` or ``target``).
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from pydantic import JsonValue

from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.learnings.learning import Learning, LearningStatus, LearningTarget
from agent_hub.core.readmodels.fact_keys import canonical_events

type TargetKind = Literal["team", "repo", "personal"]
type Provenance = Literal["human", "agent", "agent-from-code", "agent-from-external"]

_TERMINAL: Mapping[EventType, LearningStatus] = {
    EventType.LEARNING_ACCEPTED: LearningStatus.ACCEPTED,
    EventType.LEARNING_REJECTED: LearningStatus.REJECTED,
}
_TARGET_KINDS: Mapping[str, TargetKind] = {"team": "team", "repo": "repo", "personal": "personal"}
_PROVENANCES: Mapping[str, Provenance] = {
    "human": "human",
    "agent": "agent",
    "agent-from-code": "agent-from-code",
    "agent-from-external": "agent-from-external",
}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _target_path(payload: Mapping[str, JsonValue]) -> str | None:
    target = payload.get("target")
    if isinstance(target, dict):
        return _text(target.get("path"))
    return _text(target)


def _references(payload: Mapping[str, JsonValue]) -> list[str]:
    candidates = (_text(payload.get("proposal")), _text(payload.get("brain_path")))
    return [ref for ref in (*candidates, _target_path(payload)) if ref is not None]


def _kind_of_path(path: str | None) -> TargetKind | None:
    if path is None:
        return None
    if path.startswith("brain/auto/"):
        return "personal"
    if path.startswith("brain/"):
        return "team"
    if path.endswith("AGENTS.md"):
        return "repo"
    return None


def _target(payload: Mapping[str, JsonValue]) -> LearningTarget:
    target = payload.get("target")
    path = _target_path(payload)
    declared = _TARGET_KINDS.get(str(target.get("kind"))) if isinstance(target, dict) else None
    return LearningTarget(kind=declared or _kind_of_path(path), path=path)


def _learning(proposal: StoredEvent, decision: StoredEvent | None) -> Learning:
    payload = proposal.event.payload
    decided = {} if decision is None else decision.event.payload
    status = LearningStatus.PROPOSED if decision is None else _TERMINAL[decision.event.type]
    return Learning(
        id=(_references(payload) or [proposal.event_id])[0],
        project=proposal.event.project,
        text=_text(payload.get("text")) or "",
        target=_target(payload),
        author=_text(payload.get("author")),
        provenance=_PROVENANCES.get(str(payload.get("provenance"))),
        status=status,
        source_session_id=proposal.event.session,
        source_event_id=proposal.event_id,
        proposed_at=proposal.event.timestamp,
        decided_at=None if decision is None else decision.event.timestamp,
        decided_by=_text(decided.get("author")),
        brain_path=_text(decided.get("brain_path")) or _text(payload.get("brain_path")),
        commit=_text(decided.get("commit")),
        rejection_reason=_text(decided.get("reason"))
        if status == LearningStatus.REJECTED
        else None,
    )


def _first_decision(proposal: StoredEvent, decisions: Sequence[StoredEvent]) -> StoredEvent | None:
    refs = set(_references(proposal.event.payload)) or {proposal.event_id}
    for stored in decisions:
        if refs & set(_references(stored.event.payload)):
            return stored
    return None


def fold_learnings(events: Iterable[StoredEvent]) -> dict[str, Learning]:
    """Every proposed learning in ``events``, by id, with its first decision applied."""
    ordered = canonical_events(events)
    decisions = [stored for stored in ordered if stored.event.type in _TERMINAL]
    learnings: dict[str, Learning] = {}
    for stored in ordered:
        if stored.event.type != EventType.LEARNING_PROPOSED:
            continue
        learning = _learning(stored, _first_decision(stored, decisions))
        learnings.setdefault(learning.id, learning)
    return learnings
