from datetime import UTC, datetime
from typing import Any

from agent_hub.api.stream_views import (
    GlobalStreamView,
    RunStreamView,
    SessionStreamView,
    changed_fields,
    timeline_event,
)
from agent_hub.core.events.event import EventSource
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingestion_status import IngestionCounters
from agent_hub.core.readmodels.filters import Scope
from agent_hub.core.runs.workflow_run import RunStep
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.read_model_builders import a_run

AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def test_lists_changed_fields_only_when_patch_built() -> None:
    assert changed_fields({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == {"b": 3, "c": 4}
    assert changed_fields(None, {"a": 1}) == {"a": 1}


def test_computes_latency_when_received_time_known(fakes: Any) -> None:
    reader = fakes.EventReader()
    (stored,) = reader.add(an_event())

    event = timeline_event(stored)

    assert event.event_id == stored.event_id
    assert event.latency_ms == int((AT - stored.event.timestamp).total_seconds() * 1000)


def test_sends_events_only_when_session_unknown(fakes: Any) -> None:
    reader = fakes.EventReader()
    stored = reader.add(an_event(session="ghost"))
    view = SessionStreamView(fakes.EventReadModels(), "ghost")
    view.prime()

    messages = view.changes(stored)

    assert [message.event for message in messages] == ["event"]


def test_replays_whole_run_and_gates_when_run_resumed(fakes: Any) -> None:
    models = fakes.EventReadModels(runs=[a_run()])
    reader = fakes.EventReader()
    stored = reader.add(
        an_event(session="session-9", type="gate.request", payload={"run": "1a2b3c4d"}),
        an_event(session="session-9", type="gate.request", payload={"run": "other"}),
    )
    view = RunStreamView(models, "1a2b3c4d")
    view.prime()

    messages = view.replay(stored)

    assert [message.event for message in messages] == ["run", "step", "gate"]
    assert "steps" not in messages[0].data  # type: ignore[operator]
    assert view.scope().project == "demo"


def test_sends_changed_step_when_run_step_ends(fakes: Any) -> None:
    models = fakes.EventReadModels(runs=[a_run()])
    reader = fakes.EventReader()
    view = RunStreamView(models, "1a2b3c4d")
    view.prime()
    ended = RunStep(
        key="implement", attempt=1, max_attempts=1, status="ok", started_at=AT, ended_at=AT
    )
    models.runs[0] = a_run(steps=(ended,))
    stored = reader.add(an_event(session="run:1a2b3c4d", type="step.end", source="executor"))

    messages = view.changes(stored)

    assert [message.event for message in messages] == ["step"]
    assert messages[0].data["status"] == "ok"  # type: ignore[index, call-overload]


def test_ignores_events_of_other_runs_when_run_streamed(fakes: Any) -> None:
    view = RunStreamView(fakes.EventReadModels(runs=[a_run()]), "1a2b3c4d")
    view.prime()
    stored = fakes.EventReader().add(an_event(session="run:other"))

    assert view.changes(stored) == []


def test_scopes_to_executor_session_when_run_unknown(fakes: Any) -> None:
    view = RunStreamView(fakes.EventReadModels(), "ffffffff")
    view.prime()

    assert view.scope().session == "run:ffffffff"
    assert view.replay([]) == []


def test_sends_collector_when_source_sends_while_open(fakes: Any) -> None:
    counters = IngestionCounters(clock=lambda: AT)
    view = GlobalStreamView(fakes.EventReadModels(), counters, Scope())
    view.prime()
    counters.record_append(
        AppendResult(appended=1, duplicates=0), sources={EventSource.CLAUDE_CODE}
    )
    stored = fakes.EventReader().add(an_event())

    messages = view.changes(stored)

    assert [message.event for message in messages] == ["collector"]
    assert messages[0].data == {"sources": {"claude_code": "2026-10-11T12:00:00.000Z"}}
    assert [message.event for message in view.replay(stored)] == ["counts"]
    assert view.heartbeat(AT)["sources"] == {"claude_code": "2026-10-11T12:00:00.000Z"}
