from datetime import timedelta

from agent_hub.core.events.event import EventSource
from agent_hub.core.readmodels.fact_keys import (
    canonical_events,
    canonical_part,
    fact_key,
    resolve_facts,
    usage_key,
)
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_run_events,
    a_session_events,
    as_stored,
    shuffled,
    usage_events,
    with_transcript_copies,
)


def test_keys_tool_events_by_tool_use_id_when_payload_has_one() -> None:
    call = an_event(type="tool.call", payload={"tool": "Bash", "tool_use_id": "toolu_1"})
    result = an_event(type="tool.result", payload={"tool": "Bash", "tool_use_id": "toolu_1"})

    assert fact_key(call) == "tool.call:toolu_1"
    assert fact_key(result) == "tool.result:toolu_1"


def test_keys_step_by_run_step_and_attempt_when_executor_step() -> None:
    event = an_event(
        type="step.end",
        source="executor",
        session="run:1a2b3c4d",
        step="verify",
        payload={"run": "1a2b3c4d", "attempt": 2},
    )

    assert fact_key(event) == "step.end:1a2b3c4d:verify:2"


def test_keys_run_end_by_run_when_two_run_ends_exist() -> None:
    first = an_event(type="run.end", source="executor", payload={"run": "r1"})

    assert fact_key(first) == "run.end:r1"


def test_has_no_key_when_event_has_no_shared_identity() -> None:
    assert fact_key(an_event(type="message", payload={"role": "user"})) is None


def test_keys_usage_by_message_id_when_payload_has_one() -> None:
    usage = usage_events()[0]

    assert usage_key(usage) == f"usage:{usage.payload['message_id']}"
    assert usage_key(an_event(type="message", payload={"role": "assistant"})) is None


def test_prefers_hook_copy_when_transcript_copy_of_tool_call_exists() -> None:
    stored = as_stored(with_transcript_copies(a_session_events()))

    resolution = resolve_facts(stored)

    winner_sources = {
        stored_event.event.source
        for stored_event in resolution.winners
        if stored_event.event.type in {"tool.call", "tool.result"}
    }
    assert winner_sources == {EventSource.CLAUDE_CODE}
    losers = [item for item in stored if item.event_id in resolution.conflicts]
    assert {item.event.source for item in losers} == {EventSource.TRANSCRIPT}
    assert len(losers) == 6
    merged = [resolution.merged_sources.get(item.event_id) for item in resolution.winners]
    assert (EventSource.CLAUDE_CODE, EventSource.TRANSCRIPT) in merged


def test_prefers_executor_copy_when_hook_reports_same_step() -> None:
    executor = an_event(
        type="step.start", source="executor", step="verify", payload={"run": "r1", "attempt": 1}
    )
    hook = an_event(
        type="step.start",
        source="claude_code",
        step="verify",
        timestamp=executor.timestamp - timedelta(seconds=5),
        payload={"run": "r1", "attempt": 1},
    )

    resolution = resolve_facts(as_stored([hook, executor]))

    assert [item.event for item in resolution.winners] == [executor]


def test_keeps_first_run_end_when_second_arrives_later() -> None:
    events = a_run_events(fails=True)
    late = events[-1].model_copy(
        update={
            "source_id": "late-run-end",
            "timestamp": events[-1].timestamp + timedelta(minutes=5),
            "payload": dict(events[-1].payload) | {"status": "done"},
        }
    )

    resolution = resolve_facts(as_stored([late, *events]))

    run_ends = [item.event for item in resolution.winners if item.event.type == "run.end"]
    assert run_ends == [events[-1]]


def test_resolves_same_winners_when_events_shuffled_with_duplicates() -> None:
    stored = as_stored(with_transcript_copies(a_session_events()))
    expected = resolve_facts(stored)

    for seed in range(10):
        noisy = shuffled([*stored, *stored[:3]], seed)

        assert resolve_facts(noisy) == expected


def test_orders_by_timestamp_then_identity_when_events_canonicalized() -> None:
    later = an_event(timestamp=SCENARIO_START + timedelta(minutes=1), source_id="b")
    earlier = an_event(timestamp=SCENARIO_START, source_id="z")
    same_time = an_event(timestamp=SCENARIO_START, source_id="a")
    stored = as_stored([later, earlier, same_time, earlier])

    ordered = canonical_events(stored)

    assert [item.event.source_id for item in ordered] == ["a", "z", "b"]


def test_keys_learning_proposal_by_proposal_when_hook_and_transcript_report_it() -> None:
    transcript_copy = an_event(
        type="learning.proposed", source="transcript", payload={"proposal": "toolu_9"}
    )
    hook_copy = an_event(
        type="learning.proposed", source="claude_code", payload={"proposal": "toolu_9"}
    )

    assert fact_key(transcript_copy) == fact_key(hook_copy) == "learning.proposed:toolu_9"
    assert fact_key(an_event(type="learning.proposed", payload={})) is None


def test_returns_input_unchanged_when_events_already_canonical() -> None:
    ordered = canonical_events(shuffled(as_stored(a_session_events()), seed=3))

    again = canonical_events(ordered)

    assert again is ordered
    assert canonical_events(list(ordered)) == ordered


def test_keeps_part_canonical_when_part_of_canonical_events_marked() -> None:
    ordered = canonical_events(as_stored(a_session_events()))

    part = canonical_part(ordered[::2])

    assert canonical_events(part) is part
    assert part == ordered[::2]
