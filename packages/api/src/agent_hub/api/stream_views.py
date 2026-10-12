"""What each stream sends: the global stream, one session, the live tiles and one run.

Each view keeps the last state it sent and, after a batch of events, sends only what changed:
``session`` and ``run`` patches carry the changed fields, ``tile.upsert`` and ``step`` the
changed items (design spec 02, "SSE contract"). Every message's id is the last event id of the
batch, so a client that resumes from it misses nothing.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, JsonValue

from agent_hub.api.sse import SseMessage, heartbeat_data
from agent_hub.core.events.event import EventType
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.readmodels.read_ports import EntityNotFoundError, EventReadModels
from agent_hub.core.readmodels.view_types import timestamp_text
from agent_hub.core.sessions.session import TimelineEvent

GATE_TYPES = frozenset({EventType.GATE_REQUEST, EventType.GATE_RESULT})

type JsonObject = dict[str, JsonValue]


def _dump(model: BaseModel) -> JsonObject:
    return model.model_dump(mode="json")


def _or_none[T](read: Callable[[str], T], entity_id: str) -> T | None:
    try:
        return read(entity_id)
    except EntityNotFoundError:
        return None


def changed_fields(before: Mapping[str, JsonValue] | None, after: JsonObject) -> JsonObject:
    """The fields of ``after`` whose value differs from ``before`` (every field when None)."""
    if before is None:
        return after
    return {name: value for name, value in after.items() if before.get(name) != value}


def timeline_event(stored: StoredEvent) -> TimelineEvent:
    """A stored event as the timeline shows it, before any fold (no fact key, no conflict)."""
    event = stored.event
    latency = None
    if stored.received_at is not None:
        latency = int((stored.received_at - event.timestamp).total_seconds() * 1000)
    return TimelineEvent(
        event_id=stored.event_id,
        seq=stored.seq,
        project=event.project,
        session=event.session,
        type=event.type,
        timestamp=event.timestamp,
        received_at=stored.received_at,
        latency_ms=latency,
        source=event.source,
        source_id=event.source_id,
        repo=event.repo,
        agent=event.agent,
        workflow=event.workflow,
        step=event.step,
        payload=event.payload,
    )


def _last_id(events: Sequence[StoredEvent]) -> str | None:
    return events[-1].event_id if events else None


class SessionStreamView:
    """``/sessions/{id}/events/stream``: ``event`` per event, a ``session`` patch, ``end``."""

    def __init__(self, models: EventReadModels, session_id: str) -> None:
        self._models = models
        self._session_id = session_id
        self._session: JsonObject | None = None

    def scope(self) -> EventQuery:
        """The session's events."""
        return EventQuery(session=self._session_id)

    def prime(self) -> None:
        """The session as it is now."""
        self._session = self._read()

    def replay(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The missed events, one ``event`` each."""
        return [self._event_message(stored) for stored in events]

    def changes(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The new events, then the session's changed fields, then ``end`` if it ended."""
        messages = [self._event_message(stored) for stored in events]
        session = self._read()
        if session is not None:
            patch = changed_fields(self._session, session)
            if patch:
                messages.append(SseMessage("session", patch, id=_last_id(events)))
            self._session = session
        ends = [stored for stored in events if stored.event.type is EventType.SESSION_END]
        if ends:
            data: JsonObject = {"session_id": self._session_id}
            messages.append(SseMessage("end", data, id=ends[-1].event_id))
        return messages

    def heartbeat(self, now: datetime) -> JsonObject:
        """When it was sent."""
        return heartbeat_data(now)

    def _read(self) -> JsonObject | None:
        session = _or_none(self._models.get_session, self._session_id)
        return None if session is None else _dump(session)

    @staticmethod
    def _event_message(stored: StoredEvent) -> SseMessage:
        return SseMessage("event", _dump(timeline_event(stored)), id=stored.event_id)


class LiveStreamView:
    """``/live-sessions/stream``: ``tile.upsert`` for new or changed tiles, ``tile.remove``."""

    def __init__(self, models: EventReadModels, scope: Scope) -> None:
        self._models = models
        self._scope = scope
        self._tiles: dict[str, JsonObject] = {}

    def scope(self) -> EventQuery:
        """Every event of the scoped project (or of all projects)."""
        return EventQuery(project=self._scope.project)

    def prime(self) -> None:
        """The tiles as they are now."""
        self._tiles = self._read()

    def replay(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """Every current tile: the client's copy may be older than the missed events."""
        last_id = _last_id(events)
        return [SseMessage("tile.upsert", tile, id=last_id) for tile in self._tiles.values()]

    def changes(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """Tiles that are new or differ, then tiles that are gone."""
        tiles = self._read()
        last_id = _last_id(events)
        messages = [
            SseMessage("tile.upsert", tile, id=last_id)
            for tile_id, tile in tiles.items()
            if self._tiles.get(tile_id) != tile
        ]
        messages.extend(
            SseMessage("tile.remove", {"id": tile_id}, id=last_id)
            for tile_id in self._tiles
            if tile_id not in tiles
        )
        self._tiles = tiles
        return messages

    def heartbeat(self, now: datetime) -> JsonObject:
        """When it was sent."""
        return heartbeat_data(now)

    def _read(self) -> dict[str, JsonObject]:
        page = self._models.list_live_sessions(self._scope)
        return {tile.id: _dump(tile) for tile in page.items}


def _step_key(step: Mapping[str, JsonValue]) -> str:
    return f"{step.get('key')}:{step.get('attempt')}"


class RunStreamView:
    """``/workflow-runs/{id}/stream``: a ``run`` patch, changed ``step``s and ``gate`` events.

    The run's events are its executor events (session ``run:<id>``) and the events of its
    sessions that name it in ``payload.run``.
    """

    def __init__(self, models: EventReadModels, run_id: str) -> None:
        self._models = models
        self._run_id = run_id
        self._project: str | None = None
        self._run: JsonObject | None = None
        self._steps: dict[str, JsonObject] = {}

    def scope(self) -> EventQuery:
        """The run's project once known, else its executor session."""
        if self._project is None:
            return EventQuery(session=f"run:{self._run_id}")
        return EventQuery(project=self._project)

    def prime(self) -> None:
        """The run and its steps as they are now."""
        self._run, self._steps = self._read()

    def replay(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The whole run, every step and the missed gate events."""
        last_id = _last_id(events)
        messages = [] if self._run is None else [SseMessage("run", self._run, id=last_id)]
        messages.extend(SseMessage("step", step, id=last_id) for step in self._steps.values())
        messages.extend(self._gates(events))
        return messages

    def changes(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The run's changed fields, its new or changed steps, its gate events."""
        mine = [stored for stored in events if self._concerns(stored)]
        if not mine:
            return []
        run, steps = self._read()
        last_id = _last_id(mine)
        messages: list[SseMessage] = []
        if run is not None:
            patch = changed_fields(self._run, run)
            if patch:
                messages.append(SseMessage("run", patch, id=last_id))
        messages.extend(
            SseMessage("step", step, id=last_id)
            for key, step in steps.items()
            if self._steps.get(key) != step
        )
        messages.extend(self._gates(mine))
        self._run, self._steps = run, steps
        return messages

    def heartbeat(self, now: datetime) -> JsonObject:
        """When it was sent."""
        return heartbeat_data(now)

    def _concerns(self, stored: StoredEvent) -> bool:
        event = stored.event
        return event.session == f"run:{self._run_id}" or event.payload.get("run") == self._run_id

    def _gates(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        return [
            SseMessage("gate", _dump(timeline_event(stored)), id=stored.event_id)
            for stored in events
            if stored.event.type in GATE_TYPES and self._concerns(stored)
        ]

    def _read(self) -> tuple[JsonObject | None, dict[str, JsonObject]]:
        run = _or_none(self._models.get_run, self._run_id)
        if run is None:
            return None, {}
        self._project = run.project
        document = _dump(run)
        raw_steps = document.pop("steps", [])
        steps: dict[str, JsonObject] = {}
        if isinstance(raw_steps, list):
            steps = {_step_key(step): step for step in raw_steps if isinstance(step, dict)}
        return document, steps


class GlobalStreamView:
    """``/events/stream``: ``counts`` when a badge count changes, ``collector`` when a source
    sends; heartbeats carry each source's last event time."""

    def __init__(
        self, models: EventReadModels, counters: IngestionCounters | None, scope: Scope
    ) -> None:
        self._models = models
        self._counters = counters
        self._scope = scope
        self._counts: JsonObject | None = None
        self._sources: JsonObject = {}

    def scope(self) -> EventQuery:
        """Every event of the scoped project (or of all projects)."""
        return EventQuery(project=self._scope.project)

    def prime(self) -> None:
        """The counts and the sources' times as they are now."""
        self._counts = _dump(self._models.stream_counts())
        self._sources = self._source_times()

    def replay(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """The current counts."""
        if self._counts is None:
            return []
        return [SseMessage("counts", self._counts, id=_last_id(events))]

    def changes(self, events: Sequence[StoredEvent]) -> list[SseMessage]:
        """``counts`` when they differ, ``collector`` when a source's last event time moved."""
        last_id = _last_id(events)
        messages: list[SseMessage] = []
        counts = _dump(self._models.stream_counts())
        if counts != self._counts:
            messages.append(SseMessage("counts", counts, id=last_id))
            self._counts = counts
        sources = self._source_times()
        if sources != self._sources:
            messages.append(SseMessage("collector", {"sources": sources}, id=last_id))
            self._sources = sources
        return messages

    def heartbeat(self, now: datetime) -> JsonObject:
        """When it was sent and when each source last sent an event."""
        return heartbeat_data(now) | {"sources": self._source_times()}

    def _source_times(self) -> JsonObject:
        if self._counters is None:
            return {}
        times = self._counters.source_times()
        return {source: timestamp_text(at) for source, at in times.items()}
