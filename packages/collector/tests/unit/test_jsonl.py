import io
import json

import pytest

from agent_hub.collector import jsonl
from agent_hub.collector.errors import InputUnreadableError
from agent_hub.collector.jsonl import (
    MAX_REASON_LENGTH,
    LineError,
    ParsedEvent,
    parse_events,
    read_stream,
)
from agent_hub.core.testing.builders import an_event, events_to_jsonl


def test_returns_events_in_order_when_all_lines_valid() -> None:
    events = [an_event(), an_event(), an_event()]

    batch = parse_events(events_to_jsonl(events))

    assert batch.errors == ()
    assert batch.events == (
        ParsedEvent(line_number=1, event=events[0]),
        ParsedEvent(line_number=2, event=events[1]),
        ParsedEvent(line_number=3, event=events[2]),
    )


def test_reports_every_bad_line_when_json_and_schema_errors_mixed() -> None:
    valid = [an_event(), an_event(), an_event()]
    without_project = an_event().model_dump(mode="json")
    del without_project["project"]
    lines = [
        valid[0].model_dump_json(),
        valid[1].model_dump_json(),
        '{"project": "demo",',
        valid[2].model_dump_json(),
        json.dumps(without_project),
    ]

    batch = parse_events("\n".join(lines) + "\n")

    assert [error.line_number for error in batch.errors] == [3, 5]
    assert "JSON" in batch.errors[0].reason
    assert "project" in batch.errors[1].reason
    assert batch.events == (
        ParsedEvent(line_number=1, event=valid[0]),
        ParsedEvent(line_number=2, event=valid[1]),
        ParsedEvent(line_number=4, event=valid[2]),
    )


def test_skips_blank_lines_when_counting_line_numbers() -> None:
    first, second = an_event(), an_event()
    text = f"\n{first.model_dump_json()}\n   \n\t\n{second.model_dump_json()}\n"

    batch = parse_events(text)

    assert batch.errors == ()
    assert batch.events == (
        ParsedEvent(line_number=2, event=first),
        ParsedEvent(line_number=5, event=second),
    )


def test_returns_nothing_when_text_empty() -> None:
    batch = parse_events("")

    assert batch.events == ()
    assert batch.errors == ()


def test_reports_error_when_line_is_json_array() -> None:
    batch = parse_events(f"[{an_event().model_dump_json()}]\n")

    assert batch.events == ()
    assert batch.errors == (LineError(line_number=1, reason="expected a JSON object"),)


def test_reports_error_when_line_uses_nan_constant() -> None:
    fields = an_event().model_dump(mode="json")
    line = json.dumps(fields | {"payload": {"score": float("nan")}})

    batch = parse_events(line)

    assert batch.events == ()
    assert [error.line_number for error in batch.errors] == [1]
    assert "NaN" in batch.errors[0].reason


def test_keeps_line_whole_when_string_holds_unicode_line_separator() -> None:
    # JSON strings may hold U+2028 and U+0085 unescaped; only "\n" ends a JSON Lines record.
    event = an_event(payload={"text": "a b\x85c"})

    batch = parse_events(events_to_jsonl([event]))

    assert batch.errors == ()
    assert batch.events == (ParsedEvent(line_number=1, event=event),)


def test_accepts_line_when_it_ends_with_carriage_return() -> None:
    event = an_event()

    batch = parse_events(f"{event.model_dump_json()}\r\n")

    assert batch.errors == ()
    assert batch.events == (ParsedEvent(line_number=1, event=event),)


def test_decodes_utf8_when_stream_read() -> None:
    text = events_to_jsonl([an_event(payload={"text": "café"})])

    assert read_stream(io.BytesIO(text.encode()), name="stdin") == text


def test_raises_unreadable_when_stream_not_utf8() -> None:
    with pytest.raises(InputUnreadableError) as caught:
        read_stream(io.BytesIO(b"caf\xe9\n"), name="stdin")

    assert "stdin" in str(caught.value)
    assert "UTF-8" in str(caught.value)


def test_raises_unreadable_when_stream_read_fails() -> None:
    stream = io.BytesIO()
    stream.close()

    with pytest.raises(InputUnreadableError) as caught:
        read_stream(stream, name="stdin")

    assert "stdin" in str(caught.value)


def _line_with_payload(payload_json: str) -> str:
    fields = an_event().model_dump(mode="json")
    del fields["payload"]
    return json.dumps(fields)[:-1] + f', "payload": {payload_json}}}'


def test_reports_error_when_line_nested_too_deeply() -> None:
    depth = 200_000
    line = _line_with_payload('{"a": ' + "[" * depth + "]" * depth + "}")

    batch = parse_events(line)

    assert batch.events == ()
    assert batch.errors == (LineError(line_number=1, reason="invalid JSON: nested too deeply"),)


def test_reports_error_when_validation_recurses_too_deeply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecursingEvent:
        @classmethod
        def model_validate(cls, value: object) -> object:
            raise RecursionError

    monkeypatch.setattr(jsonl, "Event", RecursingEvent)

    batch = parse_events(an_event().model_dump_json())

    assert batch.errors == (LineError(line_number=1, reason="invalid JSON: nested too deeply"),)


def test_reports_error_when_key_repeated_at_top_level() -> None:
    event = an_event()
    line = event.model_dump_json()[:-1] + ', "source_id": "evt-other"}'

    batch = parse_events(line)

    assert batch.events == ()
    assert batch.errors == (
        LineError(line_number=1, reason='invalid JSON: duplicate key "source_id"'),
    )


def test_reports_error_when_key_repeated_inside_payload() -> None:
    line = _line_with_payload('{"state": "open", "state": "closed"}')

    batch = parse_events(line)

    assert batch.events == ()
    assert batch.errors == (LineError(line_number=1, reason='invalid JSON: duplicate key "state"'),)


def _has_control_character(text: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in text)


def test_escapes_key_when_unknown_key_has_control_characters() -> None:
    fields = an_event().model_dump(mode="json") | {"se\ncret=hunter2\x1b[2J": 1}

    batch = parse_events(json.dumps(fields))

    [error] = batch.errors
    assert not _has_control_character(error.reason)
    assert json.dumps("se\ncret=hunter2\x1b[2J") in error.reason


def test_keeps_field_name_plain_when_required_field_missing() -> None:
    fields = an_event().model_dump(mode="json")
    del fields["project"]

    batch = parse_events(json.dumps(fields))

    assert batch.errors == (LineError(line_number=1, reason="project: Field required"),)


def test_bounds_reason_when_location_deeply_nested() -> None:
    depth = 900
    line = _line_with_payload('{"a": ' + "[" * depth + "]" * depth + "}")

    batch = parse_events(line)

    [error] = batch.errors
    assert len(error.reason) <= MAX_REASON_LENGTH
    assert error.reason.startswith("payload.a.list.0.list…: ")


def test_bounds_reason_when_many_fields_unknown() -> None:
    fields = an_event().model_dump(mode="json") | {f"extra{n}": n for n in range(200)}

    batch = parse_events(json.dumps(fields))

    [error] = batch.errors
    assert len(error.reason) <= MAX_REASON_LENGTH
    assert error.reason.endswith("…")
