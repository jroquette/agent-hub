import json
from typing import Any

import pytest

from agent_hub.collector import hook_spool
from agent_hub.collector.hook_spool import parse_spool
from agent_hub.core.ingestion.hook_envelope import MAX_BODY_BYTES, MAX_JSON_DEPTH
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope


def _line(hook_event_name: str = "PreToolUse", **overrides: Any) -> bytes:
    envelope = an_envelope(a_hook_input(hook_event_name), **overrides)
    return envelope.model_dump_json().encode()


def test_parses_envelopes_with_their_line_numbers_when_lines_valid() -> None:
    data = b"\n".join([_line("PreToolUse"), b"", _line("Stop")]) + b"\n"

    lines = parse_spool(data)

    assert [
        (item.line_number, item.envelope.hook["hook_event_name"]) for item in lines.envelopes
    ] == [
        (1, "PreToolUse"),
        (3, "Stop"),
    ]
    assert (lines.errors, lines.dropped) == ((), 0)


def test_sums_dropped_counts_when_count_lines_present() -> None:
    data = b"\n".join([b'{"dropped": 4}', _line(), b'{"dropped": 3}']) + b"\n"

    lines = parse_spool(data)

    assert lines.dropped == 7
    assert [item.line_number for item in lines.envelopes] == [2]
    assert lines.errors == ()


def test_reports_each_bad_line_with_its_reason_when_lines_not_envelopes() -> None:
    no_project = json.loads(_line())
    del no_project["project"]
    data = b"\n".join(
        [
            _line(),
            b"{not json",
            b"[1, 2]",
            json.dumps(no_project).encode(),
            b'{"dropped": -1}',
            b"\xff\xfe",
        ]
    )

    lines = parse_spool(data)

    assert [item.line_number for item in lines.envelopes] == [1]
    reasons = {error.line_number: error.reason for error in lines.errors}
    assert sorted(reasons) == [2, 3, 4, 5, 6]
    assert reasons[2] == "invalid JSON: Expecting property name enclosed in double quotes"
    assert reasons[3] == "expected a JSON object"
    assert reasons[4] == "project: Field required"
    assert "dropped: Extra inputs are not permitted" in reasons[5]
    assert reasons[6] == "not valid UTF-8 (byte 0)"


# The parser's overflow is simulated, not built: Python 3.14 reads 200,000 levels.
@pytest.mark.parametrize("target", ["agent_hub.collector.jsonl.json.loads", "envelope"])
def test_reports_nested_too_deeply_when_parse_or_validation_overflows(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    def overflow(*_args: object, **_kwargs: object) -> object:
        raise RecursionError

    line = _line()
    if target == "envelope":
        monkeypatch.setattr(hook_spool.HookEnvelope, "model_validate", overflow)
    else:
        monkeypatch.setattr(target, overflow)

    lines = parse_spool(line)

    assert [(error.line_number, error.reason) for error in lines.errors] == [
        (1, "invalid JSON: nested too deeply")
    ]


def test_reports_bad_line_when_envelope_nests_deeper_than_hook_route_allows() -> None:
    nested: Any = "leaf"
    for _ in range(100):
        nested = [nested]
    deep = an_envelope(a_hook_input("PreToolUse", tool_input={"nested": nested}))
    data = b"\n".join([deep.model_dump_json().encode(), _line()])

    lines = parse_spool(data)

    assert [item.line_number for item in lines.envelopes] == [2]
    assert [(error.line_number, error.reason) for error in lines.errors] == [
        (1, f"nested deeper than {MAX_JSON_DEPTH} levels")
    ]


def test_refuses_line_when_longer_than_body_limit() -> None:
    envelope = json.loads(_line())
    envelope["hook"]["tool_input"]["command"] = "x" * MAX_BODY_BYTES

    lines = parse_spool(json.dumps(envelope).encode())

    assert lines.envelopes == ()
    assert [(error.line_number, error.reason) for error in lines.errors] == [
        (1, f"longer than {MAX_BODY_BYTES} bytes")
    ]


def test_returns_nothing_when_spool_empty() -> None:
    lines = parse_spool(b"")

    assert (lines.envelopes, lines.errors, lines.dropped) == ((), (), 0)


def test_bounds_taken_file_at_64_mib_when_no_bound_given() -> None:
    assert hook_spool.MAX_TAKEN_BYTES == 67_108_864
