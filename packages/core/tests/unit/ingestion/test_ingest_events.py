import pytest

from agent_hub.core.errors import EventConflictError
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore


def test_returns_counts_when_batch_valid() -> None:
    event = an_event()

    result = IngestEvents(InMemoryEventStore()).execute([event, an_event(), event])

    assert result == AppendResult(appended=2, duplicates=1)


def test_reports_duplicates_when_batch_ingested_twice() -> None:
    ingest = IngestEvents(InMemoryEventStore())
    batch = [an_event(), an_event()]
    ingest.execute(batch)

    result = ingest.execute(batch)

    assert result == AppendResult(appended=0, duplicates=2)


def test_propagates_conflict_when_batch_conflicts() -> None:
    event_store = InMemoryEventStore()
    stored = an_event(payload={"version": 1})
    event_store.append([stored])
    before = event_store.read_all()
    changed = an_event(source_id=stored.source_id, payload={"version": 2})

    with pytest.raises(EventConflictError):
        IngestEvents(event_store).execute([an_event(), changed])

    assert event_store.read_all() == before
