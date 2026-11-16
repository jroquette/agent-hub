from typing import Any

from agent_hub.core.events.event import EventSource
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.testing.builders import an_event


def test_maps_counters_and_store_total_when_status_requested(wired: Any) -> None:
    wired.reader.add(an_event(), an_event())
    wired.counters.record_hook()
    wired.counters.record_append(
        AppendResult(appended=1, duplicates=0), sources={EventSource.CLAUDE_CODE}
    )

    body = wired.client.get("/api/v1/collector/status").json()

    assert body["db_path"].endswith("agent-hub.db")
    assert body["running_version"] == "0.8.0"
    assert (body["events_total"], body["hooks_received"], body["appended"]) == (2, 1, 1)
    assert body["started_at"] == "2026-10-11T12:00:00.000Z"
    assert body["sources"][0] == {
        "source": "claude_code",
        "last_event_at": "2026-10-11T12:00:00.000Z",
        "state": "fresh",
    }


def test_answers_not_implemented_when_collector_not_wired(client: Any) -> None:
    assert client.get("/api/v1/collector/status").status_code == 501
