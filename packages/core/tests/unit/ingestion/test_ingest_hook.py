from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event import Event
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.ingestion.ingest_hook import IngestHook
from agent_hub.core.ingestion.ingestion_ports import (
    HookMapping,
    TailPosition,
    TailResult,
    TranscriptRef,
)
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _envelope(hook_event_name: str = "PreToolUse") -> HookEnvelope:
    return HookEnvelope.model_validate(
        {
            "v": 1,
            "project": "demo",
            "sent_at": "2026-10-11T12:00:00Z",
            "hook": {"hook_event_name": hook_event_name, "session_id": "session-1"},
        }
    )


class _Mapper:
    def __init__(self, mapping: HookMapping) -> None:
        self.mapping = mapping
        self.envelopes: list[HookEnvelope] = []

    def map(self, envelope: HookEnvelope) -> HookMapping:
        self.envelopes.append(envelope)
        return self.mapping


class _Tailer:
    def __init__(self, result: TailResult) -> None:
        self.result = result
        self.refs: list[TranscriptRef] = []
        self.committed: list[TailPosition] = []

    def read_new(self, ref: TranscriptRef) -> TailResult:
        self.refs.append(ref)
        return self.result

    def commit(self, position: TailPosition) -> None:
        self.committed.append(position)


class _FailingOnceStore(InMemoryEventStore):
    """Fails the first append that carries transcript events, then works."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def append(self, events: Sequence[Event]) -> AppendResult:
        if not self.failed and any(event.source == "transcript" for event in events):
            self.failed = True
            raise _StoreDownError
        return super().append(events)


class _StoreDownError(Exception):
    pass


def _use_case(
    mapping: HookMapping, tail: TailResult | None = None
) -> tuple[IngestHook, InMemoryEventStore, _Tailer, IngestionCounters]:
    store = InMemoryEventStore()
    tailer = _Tailer(tail or TailResult(events=()))
    counters = IngestionCounters(clock=lambda: NOW)
    return IngestHook(store, _Mapper(mapping), tailer, status=counters), store, tailer, counters


def _snapshot(counters: IngestionCounters) -> tuple[int, int, int, int, int]:
    status = counters.snapshot(
        db_path="/home/demo/agent-hub.db", running_version="0.8.0", events_total=0
    )
    return (
        status.hooks_received,
        status.appended,
        status.duplicates,
        status.transcript_refused,
        status.transcript_lines_skipped,
    )


def test_appends_mapped_events_when_envelope_ingested() -> None:
    event = an_event()
    use_case, store, tailer, counters = _use_case(HookMapping(events=(event,)))

    result = use_case.execute(_envelope())

    assert result == AppendResult(appended=1, duplicates=0)
    assert store.read_all() == [event]
    assert tailer.refs == []
    assert _snapshot(counters) == (1, 1, 0, 0, 0)


def test_counts_duplicates_when_same_envelope_ingested_twice() -> None:
    use_case, store, _, counters = _use_case(HookMapping(events=(an_event(),)))

    use_case.execute(_envelope())
    second = use_case.execute(_envelope())

    assert second == AppendResult(appended=0, duplicates=1)
    assert len(store.read_all()) == 1
    assert _snapshot(counters) == (2, 1, 1, 0, 0)


def test_counts_hook_when_mapping_yields_no_event() -> None:
    use_case, store, _, counters = _use_case(HookMapping(events=()))

    result = use_case.execute(_envelope("SubagentStart"))

    assert result == AppendResult(appended=0, duplicates=0)
    assert store.read_all() == []
    assert _snapshot(counters) == (1, 0, 0, 0, 0)


def test_tails_transcript_and_adds_its_events_when_mapping_names_one() -> None:
    hook_event = an_event(type="session.end")
    transcript_events: tuple[Event, ...] = (
        an_event(source="transcript", type="message", payload={"role": "user"}),
        an_event(source="transcript", type="message", payload={"role": "assistant"}),
    )
    ref = TranscriptRef(project="demo", session="session-1", path="/home/demo/t.jsonl", kind="main")
    use_case, store, tailer, counters = _use_case(
        HookMapping(events=(hook_event,), transcript=ref),
        TailResult(events=transcript_events, skipped_lines=2),
    )

    result = use_case.execute(_envelope("Stop"))

    assert result == AppendResult(appended=3, duplicates=0)
    assert tailer.refs == [ref]
    assert store.read_all() == [hook_event, *transcript_events]
    assert _snapshot(counters) == (1, 3, 0, 0, 2)


def test_counts_refusal_when_transcript_path_refused() -> None:
    ref = TranscriptRef(project="demo", session="session-1", path="/etc/passwd", kind="main")
    use_case, store, _, counters = _use_case(
        HookMapping(events=(), transcript=ref), TailResult(events=(), refused=True)
    )

    result = use_case.execute(_envelope("Stop"))

    assert result == AppendResult(appended=0, duplicates=0)
    assert store.read_all() == []
    assert _snapshot(counters) == (1, 0, 0, 1, 0)


def test_raises_conflict_and_appends_nothing_when_event_differs_from_stored() -> None:
    stored = an_event(source_id="same-key")
    changed = an_event(source_id="same-key", payload={"tool": "Read"})
    use_case, store, _, _ = _use_case(HookMapping(events=(changed,)))
    store.append([stored])

    with pytest.raises(EventConflictError):
        use_case.execute(_envelope())

    assert store.read_all() == [stored]


def _stop_mapping() -> HookMapping:
    ref = TranscriptRef(project="demo", session="session-1", path="/home/demo/t.jsonl", kind="main")
    return HookMapping(events=(an_event(type="session.end"),), transcript=ref)


def test_commits_tail_position_when_transcript_events_appended() -> None:
    position = TailPosition(path="/home/demo/t.jsonl", version=3)
    tail = TailResult(events=(an_event(source="transcript"),), position=position)
    use_case, _, tailer, _ = _use_case(_stop_mapping(), tail)

    use_case.execute(_envelope("Stop"))

    assert tailer.committed == [position]


def test_leaves_tail_position_uncommitted_when_transcript_append_fails() -> None:
    position = TailPosition(path="/home/demo/t.jsonl", version=1)
    tail = TailResult(events=(an_event(source="transcript"),), position=position)
    store = _FailingOnceStore()
    tailer = _Tailer(tail)
    counters = IngestionCounters(clock=lambda: NOW)
    use_case = IngestHook(store, _Mapper(_stop_mapping()), tailer, status=counters)

    with pytest.raises(_StoreDownError):
        use_case.execute(_envelope("Stop"))

    assert tailer.committed == []
