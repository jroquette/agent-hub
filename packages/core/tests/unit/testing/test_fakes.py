from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore


def test_keeps_stored_event_when_caller_mutates_appended_payload() -> None:
    event_store = InMemoryEventStore()
    event = an_event(payload={"items": [1, 2]})
    original = event.model_copy(deep=True)
    event_store.append([event])

    event.payload["items"].append(3)  # type: ignore[union-attr]
    event.payload["added"] = True

    assert event_store.read_all() == [original]


def test_keeps_stored_event_when_caller_mutates_read_payload() -> None:
    event_store = InMemoryEventStore()
    event = an_event(payload={"items": [1, 2]})
    original = event.model_copy(deep=True)
    event_store.append([event])

    read = event_store.read_all()[0]
    read.payload["items"].append(3)  # type: ignore[union-attr]
    read.payload["added"] = True

    assert event_store.read_all() == [original]
