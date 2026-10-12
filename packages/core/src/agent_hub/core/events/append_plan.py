"""The one rule that splits a batch into new events, duplicates and conflicts.

Every ``EventStore`` implementation plans an append with ``plan_append`` before it writes
anything, so a conflict leaves the store untouched and all implementations classify alike.
"""

import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event import Event, EventKey
from agent_hub.core.events.payload_keys import ADDED_KEYS_V2


class AppendPlan(BaseModel):
    """What appending a batch would do: the events to write, in order, and the duplicates."""

    model_config = ConfigDict(frozen=True)

    new_events: tuple[Event, ...]
    duplicates: int


def _same_content(first: Event, second: Event) -> bool:
    """Equal events, or equal once a key this release added is kept by only one of them (L2).

    An event stored before ``ADDED_KEYS_V2`` existed and re-ingested with them is the same event:
    each added key must be missing from one side or hold the same value on both.
    """
    first_json, second_json = _as_json(first), _as_json(second)
    if first_json == second_json:
        return True
    shared = first.payload.keys() & second.payload.keys()
    upgrade_only = ADDED_KEYS_V2 - shared
    return _as_json(first, without=upgrade_only) == _as_json(second, without=upgrade_only)


def _as_json(event: Event, *, without: frozenset[str] = frozenset()) -> str:
    # Compare as JSON values (P1): Python's == treats true, 1 and 1.0 as equal, JSON does not.
    dumped = event.model_dump(mode="json")
    if without:
        dumped["payload"] = {
            key: value for key, value in dumped["payload"].items() if key not in without
        }
    return json.dumps(dumped, sort_keys=True)


def plan_append(batch: Sequence[Event], stored: Mapping[EventKey, Event]) -> AppendPlan:
    """Classify each event of ``batch`` against ``stored`` and the events before it.

    An event equal to a stored one, or to an earlier one in the batch with the same key, is a
    duplicate; so is one that differs only by keys of ``ADDED_KEYS_V2`` the other lacks (the
    stored or earlier copy is kept). A different event with the same key raises
    ``EventConflictError`` naming its position in the batch.
    """
    seen: dict[EventKey, Event] = {}
    new_events: list[Event] = []
    duplicates = 0
    for position, event in enumerate(batch):
        known = seen.get(event.key, stored.get(event.key))
        if known is None:
            new_events.append(event)
            seen[event.key] = event
        elif _same_content(known, event):
            duplicates += 1
        else:
            raise EventConflictError(
                source=event.source, source_id=event.source_id, position=position
            )
    return AppendPlan(new_events=tuple(new_events), duplicates=duplicates)
