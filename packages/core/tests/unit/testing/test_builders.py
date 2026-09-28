from agent_hub.core.events.event import Event, EventType
from agent_hub.core.testing.builders import a_hub_document, an_event, events_to_jsonl


def test_gives_unique_source_id_when_called_twice() -> None:
    assert an_event().source_id != an_event().source_id


def test_applies_overrides_when_fields_given() -> None:
    event = an_event(project="other", type="message", payload={"text": "hi"})

    assert event.project == "other"
    assert event.type == EventType.MESSAGE
    assert event.payload == {"text": "hi"}


def test_round_trips_when_events_written_as_jsonl() -> None:
    events = [an_event(), an_event(repo="org/a")]

    text = events_to_jsonl(events)

    assert text.endswith("\n")
    lines = text.splitlines()
    assert len(lines) == len(events)
    assert [Event.model_validate_json(line) for line in lines] == events


def test_returns_fresh_copy_when_hub_document_built() -> None:
    first = a_hub_document()
    first["project"]["name"] = "changed"
    first["repos"].append({"dir": "extra"})

    second = a_hub_document()

    assert second["project"]["name"] == "demo"
    assert [repo["dir"] for repo in second["repos"]] == ["demo-api"]
