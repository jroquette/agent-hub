"""One fact counted once (D16): fact keys, source precedence, winners and conflicting losers.

Several sources can report the same fact: a tool call comes from the hook and again from the
transcript; a step from the executor and from the session. A fact key names the fact; among
the events sharing one, the source the precedence prefers wins, then the earliest, then the
smallest ``source_id``. The losers stay readable (Raw events marks them ``conflict``).

Every fold starts from ``canonical_events``: duplicates of one event dropped and the rest in
an order that depends only on the events themselves, never on the order they arrived in.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent

_HOOKS_FIRST = (
    EventSource.CLAUDE_CODE,
    EventSource.TRANSCRIPT,
    EventSource.OTEL,
    EventSource.EXECUTOR,
    EventSource.GITHUB,
    EventSource.LINEAR,
    EventSource.CONTROL_PLANE,
)
_EXECUTOR_FIRST = (
    EventSource.EXECUTOR,
    EventSource.CLAUDE_CODE,
    EventSource.TRANSCRIPT,
    EventSource.OTEL,
    EventSource.GITHUB,
    EventSource.LINEAR,
    EventSource.CONTROL_PLANE,
)
# Tool calls, statuses, timings, errors and learning proposals: hooks then transcript. Steps,
# gates and run state: executor then hooks. Tokens and model come only from the transcript
# (usage_key). The app's own decisions (control plane) come last: never over a session's source.
PRECEDENCE: Mapping[EventType, tuple[EventSource, ...]] = {
    EventType.TOOL_CALL: _HOOKS_FIRST,
    EventType.TOOL_RESULT: _HOOKS_FIRST,
    EventType.LEARNING_PROPOSED: _HOOKS_FIRST,
    EventType.STEP_START: _EXECUTOR_FIRST,
    EventType.STEP_END: _EXECUTOR_FIRST,
    EventType.RUN_END: _EXECUTOR_FIRST,
    EventType.GATE_REQUEST: _EXECUTOR_FIRST,
    EventType.GATE_RESULT: _EXECUTOR_FIRST,
}


class FactResolution(BaseModel):
    """The events a fold counts, and what Raw events shows about the others.

    ``winners`` are in canonical order (events without a fact key always win). ``keys`` maps
    an ``event_id`` to its fact key, ``merged_sources`` maps a winner whose fact several
    sources reported to those sources (precedence order), ``conflicts`` holds the losers.
    """

    model_config = ConfigDict(frozen=True)

    winners: tuple[StoredEvent, ...]
    keys: Mapping[str, str]
    merged_sources: Mapping[str, tuple[EventSource, ...]]
    conflicts: frozenset[str]


def _text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)):
        return str(value)
    return None


def fact_key(event: Event) -> str | None:
    """The key of the fact ``event`` reports, or None when no other event can report it."""
    payload = event.payload
    match_type = event.type
    if match_type in {EventType.TOOL_CALL, EventType.TOOL_RESULT}:
        tool_use_id = _text(payload.get("tool_use_id"))
        return None if tool_use_id is None else f"{match_type}:{tool_use_id}"
    if match_type in {EventType.STEP_START, EventType.STEP_END}:
        run = _text(payload.get("run"))
        step = event.step or _text(payload.get("step"))
        attempt = _text(payload.get("attempt")) or "1"
        return None if run is None or step is None else f"{match_type}:{run}:{step}:{attempt}"
    if match_type == EventType.RUN_END:
        run = _text(payload.get("run"))
        if run is None:
            return None
        # A workflow engine run ends once more per resume, each end its own fact (ADR 0032).
        index = engine_end_index(run, event.source_id)
        return f"run.end:{run}" if index is None else f"run.end:{run}:{index}"
    if match_type in {EventType.GATE_REQUEST, EventType.GATE_RESULT}:
        gate_id = _text(payload.get("gate_id"))
        return None if gate_id is None else f"{match_type}:{gate_id}"
    if match_type == EventType.LEARNING_PROPOSED:
        # A Write under brain/_inbox/ is seen by its hook and again in the transcript.
        proposal = _text(payload.get("proposal"))
        return None if proposal is None else f"{match_type}:{proposal}"
    return None


# An engine run ends at most once per resume; a longer number is not an engine end (and
# ``int`` refuses digit runs past 4300).
MAX_END_INDEX_DIGITS = 9


def engine_end_index(run: str, source_id: str) -> int | None:
    """``n`` when ``source_id`` is a workflow engine's ``<run>:run:<n>:end``, else None."""
    prefix, suffix = f"{run}:run:", ":end"
    if not (source_id.startswith(prefix) and source_id.endswith(suffix)):
        return None
    index = source_id[len(prefix) : len(source_id) - len(suffix)]
    is_index = 0 < len(index) <= MAX_END_INDEX_DIGITS and index.isascii() and index.isdecimal()
    return int(index) if is_index else None


def usage_key(event: Event) -> str | None:
    """The key under which ``event``'s token usage is counted once (E5): its message id."""
    message_id = _text(event.payload.get("message_id"))
    return None if message_id is None else f"usage:{message_id}"


def _canonical_sort_key(stored: StoredEvent) -> tuple[datetime, str, str]:
    return (stored.event.timestamp, str(stored.event.source), stored.event.source_id)


class _CanonicalEvents(list[StoredEvent]):
    """What ``canonical_events`` returns; passed to it again, it is returned as is.

    Folds call ``canonical_events`` on each other's output many times per read; the marker
    spares re-keying and re-sorting events already in canonical order. Never mutated.
    """


def canonical_part(events: Iterable[StoredEvent]) -> list[StoredEvent]:
    """``events``, marked canonical: the caller took them, in order, from canonical events.

    Any subsequence of canonical events is canonical; marking it spares the next fold that
    takes it a new sort.
    """
    return _CanonicalEvents(events)


def canonical_events(events: Iterable[StoredEvent]) -> list[StoredEvent]:
    """``events`` without repeats of one event, ordered by timestamp then identity.

    Of two copies of one event (same ``(source, source_id)``), the one stored first is kept.
    """
    if isinstance(events, _CanonicalEvents):
        return events
    # Keyed like ``Event.key`` but without building one per event: folds call this often.
    unique: dict[tuple[str, str], StoredEvent] = {}
    for stored in events:
        key = (stored.event.source, stored.event.source_id)
        known = unique.get(key)
        if known is None or stored.seq < known.seq:
            unique[key] = stored
    return _CanonicalEvents(sorted(unique.values(), key=_canonical_sort_key))


def _precedence_key(stored: StoredEvent) -> tuple[int, datetime, str]:
    order = PRECEDENCE.get(stored.event.type, _HOOKS_FIRST)
    rank = order.index(stored.event.source)
    return (rank, stored.event.timestamp, stored.event.source_id)


def resolve_facts(events: Iterable[StoredEvent]) -> FactResolution:
    """Split ``events`` into the winner of each fact and the conflicting copies."""
    ordered = canonical_events(events)
    groups: dict[str, list[StoredEvent]] = {}
    keys: dict[str, str] = {}
    for stored in ordered:
        key = fact_key(stored.event)
        if key is not None:
            groups.setdefault(key, []).append(stored)
            keys[stored.event_id] = key
    losers: set[str] = set()
    merged: dict[str, tuple[EventSource, ...]] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        ranked = sorted(group, key=_precedence_key)
        losers.update(stored.event_id for stored in ranked[1:])
        sources = dict.fromkeys(stored.event.source for stored in ranked)
        merged[ranked[0].event_id] = tuple(sources)
    winners = tuple(stored for stored in ordered if stored.event_id not in losers)
    return FactResolution(
        winners=winners, keys=keys, merged_sources=merged, conflicts=frozenset(losers)
    )
