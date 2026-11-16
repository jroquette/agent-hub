import json
from datetime import UTC, datetime, timedelta

from agent_hub.core.events.event import EventSource
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingestion_status import (
    REDACTION_RULESET,
    SOURCE_STALE_AFTER,
    CollectorStatus,
    IngestionCounters,
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


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


STARTED = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _counters() -> tuple[IngestionCounters, _Clock]:
    clock = _Clock(STARTED)
    return IngestionCounters(clock=clock), clock


def test_counts_hooks_appends_and_duplicates_when_recorded() -> None:
    counters, clock = _counters()
    clock.now = STARTED + timedelta(seconds=5)

    counters.record_hook()
    counters.record_hook()
    counters.record_append(
        AppendResult(appended=2, duplicates=1), sources={EventSource.CLAUDE_CODE}
    )
    counters.record_tail(refused=True, skipped_lines=3)
    status = counters.snapshot(
        db_path="/home/demo/agent-hub.db", running_version="0.8.0", events_total=7
    )

    assert (status.hooks_received, status.appended, status.duplicates) == (2, 2, 1)
    assert (status.transcript_refused, status.transcript_lines_skipped) == (1, 3)
    assert (status.events_total, status.started_at) == (7, STARTED)
    assert status.last_event_at == STARTED + timedelta(seconds=5)


def test_keeps_last_event_time_when_append_only_has_duplicates() -> None:
    counters, clock = _counters()
    clock.now = STARTED + timedelta(seconds=1)
    counters.record_append(
        AppendResult(appended=1, duplicates=0), sources={EventSource.CLAUDE_CODE}
    )
    clock.now = STARTED + timedelta(seconds=9)

    counters.record_append(
        AppendResult(appended=0, duplicates=4), sources={EventSource.CLAUDE_CODE}
    )
    status = counters.snapshot(
        db_path="/home/demo/agent-hub.db", running_version="0.8.0", events_total=1
    )

    assert status.last_event_at == STARTED + timedelta(seconds=1)


def test_states_source_freshness_when_snapshot_taken() -> None:
    counters, clock = _counters()
    counters.record_append(
        AppendResult(appended=1, duplicates=0), sources={EventSource.CLAUDE_CODE}
    )
    counters.record_append(AppendResult(appended=1, duplicates=0), sources={EventSource.TRANSCRIPT})
    clock.now = STARTED + SOURCE_STALE_AFTER[EventSource.CLAUDE_CODE] + timedelta(seconds=1)

    status = counters.snapshot(
        db_path="/home/demo/agent-hub.db", running_version="0.8.0", events_total=2
    )

    states = {source.source: source.state for source in status.sources}
    assert states == {
        EventSource.CLAUDE_CODE: "stale",
        EventSource.TRANSCRIPT: "fresh",
        EventSource.EXECUTOR: "never",
    }


def test_lists_last_event_time_per_source_when_asked() -> None:
    counters, _ = _counters()
    counters.record_append(AppendResult(appended=1, duplicates=0), sources={EventSource.TRANSCRIPT})

    assert counters.source_times() == {"transcript": STARTED}
