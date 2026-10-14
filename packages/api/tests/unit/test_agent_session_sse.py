import json
from datetime import UTC, datetime

import pytest

from agent_hub.api.agent_session_sse import (
    MAX_POSITION_CHARS,
    RETRY,
    UNKNOWN_POSITION,
    frame,
    heartbeat_frame,
    parse_last_event_id,
    resume_position,
)
from agent_hub.core.agent_sessions.records import (
    DeltaFrame,
    ResetFrame,
    StatusFrame,
    StreamPosition,
)
from agent_hub.core.testing.read_model_builders import a_log_record


def _lines(encoded: bytes) -> list[str]:
    text = encoded.decode()
    assert text.endswith("\n\n")
    return text[:-2].split("\n")


def _data(encoded: bytes) -> object:
    (data,) = [line for line in _lines(encoded) if line.startswith("data: ")]
    return json.loads(data.removeprefix("data: "))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", StreamPosition(seq=0)),
        ("12", StreamPosition(seq=12)),
        ("12.0", StreamPosition(seq=12, delta=0)),
        ("12.345", StreamPosition(seq=12, delta=345)),
        ("999999999999.999999", StreamPosition(seq=999_999_999_999, delta=999_999)),
    ],
)
def test_parses_seq_and_delta_when_last_event_id_dotted(
    value: str, expected: StreamPosition
) -> None:
    assert parse_last_event_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-1",
        "1.",
        ".1",
        "1.2.3",
        "1 ",
        " 1",
        "1e3",
        "0x10",
        "１２",
        "1234567890123",
        "1.1234567",
        "01929a4e-7a11-7c00-8a00-00000000a001",
        "9" * (MAX_POSITION_CHARS + 1),
    ],
)
def test_refuses_position_when_last_event_id_malformed(value: str) -> None:
    assert parse_last_event_id(value) is None


def test_prefers_header_when_last_event_id_and_after_given() -> None:
    assert resume_position("7.2", after="3") == StreamPosition(seq=7, delta=2)


def test_reads_after_when_last_event_id_missing() -> None:
    assert resume_position(None, after="3") == StreamPosition(seq=3)


def test_starts_from_zero_when_no_last_event_id_or_after() -> None:
    assert resume_position(None, after=None) == StreamPosition(seq=0)


def test_answers_reset_when_last_event_id_malformed() -> None:
    assert resume_position("nope", after=None) == ResetFrame(reason=UNKNOWN_POSITION)


def test_names_event_after_kind_and_ids_by_seq_when_record_framed() -> None:
    record = a_log_record("tool.call", seq=4)

    message = frame(record)

    assert (message.event, message.id) == ("record.tool.call", "4")
    assert message.data == record.model_dump(mode="json")


def test_ids_delta_by_seq_and_index_when_delta_framed() -> None:
    delta = DeltaFrame(after_seq=9, block=1, index=3, text="Hel")

    message = frame(delta)

    assert (message.event, message.id) == ("delta", "9.3")
    assert message.data == {"after_seq": 9, "block": 1, "index": 3, "text": "Hel"}


def test_sends_no_id_when_status_or_reset_framed() -> None:
    status = frame(StatusFrame(status="ended", end_reason="closed"))
    reset = frame(ResetFrame(reason=UNKNOWN_POSITION))

    assert (status.event, status.id, status.data) == (
        "status",
        None,
        {"status": "ended", "end_reason": "closed"},
    )
    assert (reset.event, reset.id, reset.data) == ("reset", None, {"reason": UNKNOWN_POSITION})


def test_round_trips_position_when_frame_id_parsed() -> None:
    record_id = frame(a_log_record("text", seq=21)).id
    delta_id = frame(DeltaFrame(after_seq=21, block=0, index=5, text="x")).id

    assert record_id is not None
    assert delta_id is not None
    assert parse_last_event_id(record_id) == StreamPosition(seq=21)
    assert parse_last_event_id(delta_id) == StreamPosition(seq=21, delta=5)


@pytest.mark.parametrize(
    "text", ["line one\nline two", "a\r\nb", "a\rb", "sep par end", "\n\nid: 99\n\n"]
)
def test_encodes_one_data_line_when_text_multiline(text: str) -> None:
    encoded = frame(DeltaFrame(after_seq=1, block=0, index=0, text=text)).encode()

    lines = _lines(encoded)
    assert lines == ["event: delta", "id: 1.0", lines[2]]
    assert lines[2].startswith("data: ")
    assert "\r" not in encoded.decode()
    data = _data(encoded)
    assert isinstance(data, dict)
    assert data["text"] == text


def test_encodes_record_body_on_one_line_when_body_multiline() -> None:
    record = a_log_record("text", seq=2, body={"block": 0, "text": "first\nsecond"})

    encoded = frame(record).encode()

    assert _lines(encoded)[:2] == ["event: record.text", "id: 2"]
    assert len(_lines(encoded)) == 3


def test_carries_last_id_when_heartbeat_framed() -> None:
    beat = heartbeat_frame(datetime(2026, 10, 13, 9, 0, tzinfo=UTC), last_id="4.2")

    assert (beat.event, beat.id, beat.data) == (
        "heartbeat",
        "4.2",
        {"at": "2026-10-13T09:00:00.000Z"},
    )


def test_reuses_shared_retry_when_stream_opens() -> None:
    assert RETRY == b"retry: 3000\n\n"
