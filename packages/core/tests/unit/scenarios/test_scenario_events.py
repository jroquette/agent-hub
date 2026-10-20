"""A scenario run's events, metadata only (AC-350.26, ADR 0019)."""

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.payload_keys import kept_payload
from agent_hub.core.scenarios.scenario_events import ScenarioEvents
from agent_hub.core.testing.workflow_fakes import START
from agent_hub.core.workflows.ports import ContextCapture, ExpectPoll

SECRET_OUTPUT = {"status": "ON_HOLD", "order_id": "o-secret-7"}


def test_keeps_only_payload_keys_when_scenario_events_built_for_polls() -> None:
    events = ScenarioEvents(project="demo", run_id="1a2b3c4d", workflow="scenario:walk")

    events.expect_polled(
        ExpectPoll("wait", 1, 1, held=False, at=START, output={"status": "PENDING"})
    )
    events.expect_polled(ExpectPoll("wait", 1, 2, held=True, at=START, output=SECRET_OUTPUT))
    events.context_captured(ContextCapture("wait", 1, "order_id", START, "o-secret-7"))

    polls, held, capture = events.events
    assert [event.type for event in events.events] == [
        EventType.EXPECT_POLL,
        EventType.EXPECT_POLL,
        EventType.CONTEXT_CAPTURE,
    ]
    assert polls.payload == {"run": "1a2b3c4d", "attempt": 1, "poll": 1, "held": False}
    assert held.payload == {"run": "1a2b3c4d", "attempt": 1, "poll": 2, "held": True}
    assert capture.payload == {"run": "1a2b3c4d", "attempt": 1, "name": "order_id"}
    for event in events.events:
        assert kept_payload(event.type, event.payload) == event.payload
        assert (event.source, event.session, event.step) == (
            EventSource.EXECUTOR,
            "run:1a2b3c4d",
            "wait",
        )
        assert event.workflow == "scenario:walk"
        assert "secret" not in event.model_dump_json()
    assert len({event.source_id for event in events.events}) == 3
