"""Who acted in a session (S2): the main agent, then each subagent by its first event.

A subagent is told apart by its ``agent_id`` (the hook writes it on every event of a subagent).
It is linked to the main agent's Agent (or Task) tool call of the same ``subagent_type`` that
starts before the subagent's first event and whose result, if any, comes after its last; with
two or more such calls the link is ambiguous and none is made. The fold is pure and
order-independent; ``parent_session_id`` is not involved (subagents share the session id).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events, resolve_facts
from agent_hub.core.sessions.session import Actor

MAIN_AGENT: Final = "main"
AGENT_TOOLS: Final = frozenset({"Agent", "Task"})
MAIN_ACTOR: Final = Actor(kind="main")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def is_main(stored: StoredEvent) -> bool:
    """Whether the main agent emitted ``stored`` (no subagent type, no ``agent_id``)."""
    agent = stored.event.agent
    return (agent is None or agent == MAIN_AGENT) and _text(
        stored.event.payload.get("agent_id")
    ) is None


def actor_key(stored: StoredEvent) -> tuple[str, str | None]:
    """The actor ``stored`` belongs to: ``("main", None)`` or ``(type, agent_id)``."""
    if is_main(stored):
        return (MAIN_AGENT, None)
    return (stored.event.agent or MAIN_AGENT, _text(stored.event.payload.get("agent_id")))


@dataclass(frozen=True, slots=True)
class _AgentCall:
    event_id: str
    subagent_type: str | None
    description: str | None
    at: datetime
    done_at: datetime | None


def _agent_calls(winners: Sequence[StoredEvent]) -> list[_AgentCall]:
    done = {
        stored.event.payload.get("tool_use_id"): stored.event.timestamp
        for stored in winners
        if stored.event.type == EventType.TOOL_RESULT
        and _text(stored.event.payload.get("tool_use_id")) is not None
    }
    return [
        _AgentCall(
            event_id=stored.event_id,
            subagent_type=_text(stored.event.payload.get("subagent_type")),
            description=_text(stored.event.payload.get("description")),
            at=stored.event.timestamp,
            done_at=done.get(stored.event.payload.get("tool_use_id")),
        )
        for stored in winners
        if stored.event.type == EventType.TOOL_CALL
        and stored.event.payload.get("tool") in AGENT_TOOLS
        and is_main(stored)
    ]


def _actor(
    key: tuple[str, str | None], spans: Sequence[datetime], calls: Sequence[_AgentCall]
) -> Actor:
    subagent_type, agent_id = key
    first, last = spans[0], spans[-1]
    candidates = [
        call
        for call in calls
        if call.subagent_type == subagent_type
        and call.at < first
        and (call.done_at is None or call.done_at > last)
    ]
    link = candidates[0] if len(candidates) == 1 else None
    return Actor(
        kind="subagent",
        type=subagent_type,
        agent_id=agent_id,
        description=None if link is None else link.description,
        started_by_event_id=None if link is None else link.event_id,
    )


def fold_actors(events: Iterable[StoredEvent]) -> tuple[Actor, ...]:
    """The main agent, then each subagent of one session in the order it first acted."""
    ordered = canonical_events(events)
    winners = resolve_facts(ordered).winners
    times: dict[tuple[str, str | None], list[datetime]] = {}
    for stored in ordered:
        if not is_main(stored):
            times.setdefault(actor_key(stored), []).append(stored.event.timestamp)
    identified = {subagent_type for subagent_type, agent_id in times if agent_id is not None}
    calls = _agent_calls(winners)
    subagents = tuple(
        _actor(key, spans, calls)
        for key, spans in times.items()
        # A subagent's transcript events may lack its id: one with an id already names it.
        if key[1] is not None or key[0] not in identified
    )
    return (MAIN_ACTOR, *subagents)
