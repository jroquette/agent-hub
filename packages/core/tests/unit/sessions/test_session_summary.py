from datetime import timedelta

from agent_hub.core.sessions.session_summary import summarize_session
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    a_session_events,
    as_stored,
    learning_events,
    shuffled,
    stored_event_id,
    with_transcript_copies,
)

NOW = SCENARIO_START + timedelta(hours=2)
TOOLS = (
    ("Read", {"path": "src/app.py"}),
    ("Edit", {"path": "src/app.py", "lines_added": 3, "lines_removed": 1}),
    ("Write", {"path": "src/new.py", "lines_added": 9, "new_file": True}),
    ("Bash", {"command": "make check-fast"}),
    ("Bash", {"command": "make check-fast"}),
)


def _rich_session() -> list:
    denial = an_event(
        type="tool.result",
        timestamp=SCENARIO_START + timedelta(minutes=5, seconds=5),
        payload={"tool": "Bash", "tool_use_id": "toolu_deny", "status": "denied"},
    )
    gate = an_event(
        type="gate.result",
        timestamp=SCENARIO_START + timedelta(minutes=6, seconds=5),
        payload={"gate_id": "g1", "kind": "stop_gate", "result": "failed", "command": "make check"},
    )
    return as_stored(
        [
            *with_transcript_copies(a_session_events(tools=TOOLS, failed_tools=frozenset({3}))),
            denial,
            gate,
            *learning_events(start=SCENARIO_START + timedelta(minutes=7)),
        ]
    )


def test_returns_three_to_five_lines_of_session_events_when_session_ended() -> None:
    events = _rich_session()

    summary = summarize_session("session-1", events, now=NOW)

    assert 3 <= len(summary.lines) <= 5
    ids = {stored.event_id for stored in events}
    assert all(line.event_id in ids for line in summary.lines)
    assert summary.stored is False
    assert summary.derived is True
    texts = [line.text for line in summary.lines]
    assert texts[0] == "Ended stopped (prompt_input_exit)"
    assert texts[1] == "5 tool calls in 1 turn"
    assert texts[2] == "Edited 2 files"
    assert "Gates: 0 passed, 1 failed" in texts
    assert "Guard denied 1 tool call" in texts


def test_returns_identical_summary_when_called_again_or_shuffled() -> None:
    events = _rich_session()
    first = summarize_session("session-1", events, now=NOW)

    assert summarize_session("session-1", events, now=NOW) == first
    for seed in range(20):
        assert summarize_session("session-1", shuffled(events, seed), now=NOW) == first


def test_keeps_three_lines_when_session_is_minimal() -> None:
    events = as_stored(a_session_events(tools=[("Read", {"path": "a.py"})]))

    summary = summarize_session("session-1", events, now=NOW)

    assert [line.text for line in summary.lines] == [
        "Ended stopped (prompt_input_exit)",
        "1 tool call in 1 turn",
        "No file edited",
    ]
    assert summary.lines[2].event_id == stored_event_id(1)
    assert summary.generated_at == events[-1].event.timestamp


def test_says_no_end_event_when_end_inferred() -> None:
    events = as_stored(a_session_events(ended=False))

    summary = summarize_session("session-1", events, now=NOW)

    assert summary.lines[0].text == "Ended without an end event (last activity 14:07 UTC)"
    assert summary.lines[0].event_id == events[-1].event_id


def test_returns_stored_summary_when_session_summary_event_exists() -> None:
    stored_summary = an_event(
        type="session.summary",
        timestamp=SCENARIO_START + timedelta(minutes=20),
        payload={"lines": ["Shipped the fold", "All gates green", "Two files edited"]},
    )
    events = as_stored([*a_session_events(), stored_summary])

    summary = summarize_session("session-1", events, now=NOW)

    assert summary.stored is True
    assert [line.text for line in summary.lines] == [
        "Shipped the fold",
        "All gates green",
        "Two files edited",
    ]
    assert {line.event_id for line in summary.lines} == {events[-1].event_id}
