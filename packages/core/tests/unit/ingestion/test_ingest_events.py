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
    stored = an_event(payload={"command": "make v1"})
    event_store.append([stored])
    before = event_store.read_all()
    changed = an_event(source_id=stored.source_id, payload={"command": "make v2"})

    with pytest.raises(EventConflictError):
        IngestEvents(event_store).execute([an_event(), changed])

    assert event_store.read_all() == before


def _token() -> str:
    # Built from fragments: never one format-valid literal.
    return "gh" + "p_" + "A1b2C3d4" * 4


def test_redacts_payload_and_labels_when_events_hold_secrets() -> None:
    event_store = InMemoryEventStore()
    secret = _token()
    event = an_event(
        payload={"command": f"curl -H 'x: {secret}'", "arg_keys": [{"deep": secret}, 3]},
        repo=f"repo-{secret}",
        agent=f"agent-{secret}",
        workflow=f"flow-{secret}",
        step=f"step-{secret}",
    )

    IngestEvents(event_store).execute([event])

    [stored] = event_store.read_all()
    assert secret not in stored.model_dump_json()
    assert stored.payload == {
        "command": "curl -H 'x: [redacted: github token]'",
        "arg_keys": [{"deep": "[redacted: github token]"}, 3],
    }
    assert stored.repo == "repo-[redacted: github token]"
    assert stored.agent == "agent-[redacted: github token]"
    assert stored.workflow == "flow-[redacted: github token]"
    assert stored.step == "step-[redacted: github token]"


def test_counts_duplicate_when_redacted_event_ingested_again() -> None:
    ingest = IngestEvents(InMemoryEventStore())
    event = an_event(payload={"command": f"echo {_token()}"})
    ingest.execute([event])

    result = ingest.execute([event])

    assert result == AppendResult(appended=0, duplicates=1)


def test_keeps_none_labels_when_redacting_events() -> None:
    event_store = InMemoryEventStore()

    IngestEvents(event_store).execute([an_event(repo=None, agent=None)])

    [stored] = event_store.read_all()
    assert stored.repo is None
    assert stored.agent is None


def test_drops_keys_outside_payload_kept_when_any_entry_point_sends_them() -> None:
    event_store = InMemoryEventStore()
    event = an_event(
        type="tool.call",
        payload={
            "tool": "Write",
            "path": "src/app.py",
            "content": "the file body",
            "tool_input": {"content": "the file body"},
            "run": "9c8d7e6f",
        },
    )

    IngestEvents(event_store).execute([event])

    [stored] = event_store.read_all()
    assert stored.payload == {"tool": "Write", "path": "src/app.py", "run": "9c8d7e6f"}


def test_drops_redacted_key_when_key_held_secret() -> None:
    event_store = InMemoryEventStore()
    event = an_event(type="message", payload={"role": "user", _token(): "x"})

    IngestEvents(event_store).execute([event])

    [stored] = event_store.read_all()
    assert stored.payload == {"role": "user"}


def test_stores_one_row_when_error_event_ingested_twice() -> None:
    event_store = InMemoryEventStore()
    ingest = IngestEvents(event_store)
    before_upgrade = an_event(
        type="tool.result", payload={"tool": "Bash", "tool_use_id": "toolu_1", "status": "error"}
    )
    ingest.execute([before_upgrade])
    after_upgrade = an_event(
        type="tool.result",
        source_id=before_upgrade.source_id,
        payload=before_upgrade.payload | {"error_message": f"denied {_token()}"},
    )

    result = ingest.execute([after_upgrade])

    assert result == AppendResult(appended=0, duplicates=1)
    assert event_store.read_all() == [before_upgrade]
