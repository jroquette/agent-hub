from datetime import timedelta
from typing import Any

from agent_hub.api.sse import (
    RETRY,
    SseMessage,
    heartbeat_data,
    read_window,
    reset_message,
    resume_seq,
)
from agent_hub.core.events.event_query import EventQuery
from agent_hub.core.testing.builders import an_event


def test_writes_event_id_and_one_data_line_when_message_encoded() -> None:
    message = SseMessage("event", {"text": "a\nb"}, id="01929a4e-0000-7000-8000-000000000001")

    assert message.encode() == (
        b'event: event\nid: 01929a4e-0000-7000-8000-000000000001\ndata: {"text":"a\\nb"}\n\n'
    )


def test_leaves_out_id_when_message_has_none() -> None:
    assert SseMessage("reset", {"reason": "x"}).encode() == (
        b'event: reset\ndata: {"reason":"x"}\n\n'
    )
    assert reset_message().event == "reset"
    assert RETRY == b"retry: 3000\n\n"


def test_reads_scoped_window_when_window_read(fakes: Any) -> None:
    reader = fakes.EventReader()
    reader.add(*(an_event(session="a" if n % 2 else "b") for n in range(10)))

    window = read_window(reader, EventQuery(session="a"), after=2, upto=8)

    assert [stored.seq for stored in window.events] == [4, 6, 8]
    assert not window.overflow


def test_reports_overflow_when_window_holds_more_than_cap(fakes: Any) -> None:
    reader = fakes.EventReader()
    reader.add(*(an_event() for _ in range(10_001)))

    window = read_window(reader, EventQuery(), after=0, upto=10_001)

    assert window.overflow
    assert len(window.events) == 10_000


def test_resumes_after_seq_when_id_known_and_recent(fakes: Any) -> None:
    reader, clock = fakes.EventReader(), fakes.Clock()
    stored = reader.add(an_event(), an_event())

    assert resume_seq(reader, stored[1].event_id, now=clock.now()) == 2
    late = clock.now() + timedelta(hours=25)
    assert resume_seq(reader, stored[1].event_id, now=late) is None
    assert resume_seq(reader, "01929a4e-0000-7000-8000-0000000000ff", now=clock.now()) is None
    assert resume_seq(reader, "../etc", now=clock.now()) is None


def test_states_time_when_heartbeat_built(fakes: Any) -> None:
    assert heartbeat_data(fakes.Clock().now()) == {"at": "2026-10-11T12:00:00.000Z"}
