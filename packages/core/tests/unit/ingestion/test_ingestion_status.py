import json
from datetime import UTC, datetime

from agent_hub.core.events.event import EventSource
from agent_hub.core.ingestion.ingestion_status import (
    REDACTION_RULESET,
    CollectorStatus,
    SourceStatus,
)


def test_serializes_collector_status_with_ruleset_when_dumped() -> None:
    status = CollectorStatus(
        db_path="/home/demo/.local/share/agent-hub/agent-hub.db",
        running_version="0.8.0",
        started_at=datetime(2026, 10, 9, tzinfo=UTC),
        events_total=0,
        hooks_received=0,
        appended=0,
        duplicates=0,
        transcript_refused=1,
        transcript_lines_skipped=0,
        last_event_at=None,
        sources=(SourceStatus(source=EventSource.CLAUDE_CODE, last_event_at=None, state="never"),),
    )

    document = json.loads(status.model_dump_json())

    assert REDACTION_RULESET == "r1"
    assert (document["state"], document["redaction_ruleset"]) == ("running", "r1")
    assert document["sources"] == [
        {"source": "claude_code", "last_event_at": None, "state": "never"}
    ]
