"""``GET /agent-sessions/{id}/stream`` over a recording ``AgentSessionCommands`` (RT; S4, E8):
the frames in emit order with their ids, where the subscription starts (``Last-Event-ID``
wins over ``?after=``), the reset for a position that cannot be read, the 404 before any byte,
heartbeats, and the snapshot a reloaded page answers from; then, over the real use case
(``open_agent_session_app``), replay order, ``Last-Event-ID`` and a reload mid-permission."""

import json
from typing import Any

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus, PermissionDecision
from agent_hub.core.agent_sessions.driver import (
    PermissionRequest,
    TextBlock,
    TextDelta,
    ToolCall,
    ToolResult,
)
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError
from agent_hub.core.agent_sessions.records import (
    DeltaFrame,
    ResetFrame,
    StatusFrame,
    StreamPosition,
)
from agent_hub.core.testing.read_model_builders import (
    AGENT_SESSION_ID,
    WORKDIR_ID,
    a_log_record,
    an_agent_session,
    an_open_permission,
)

ONE = f"/api/v1/agent-sessions/{AGENT_SESSION_ID}"
STREAM = f"{ONE}/stream"


def _frames(body: str) -> list[dict[str, str]]:
    """Each SSE message of ``body`` as its fields (``event``, ``id``, ``data``, ``retry``)."""
    frames = []
    for block in body.split("\n\n"):
        if not block:
            continue
        fields = {}
        for line in block.split("\n"):
            name, _, value = line.partition(": ")
            fields[name] = value
        frames.append(fields)
    return frames


def _subscribed(app: Any) -> list[tuple[object, ...]]:
    return [arguments for method, arguments in app.control.calls if method == "subscribe"]


def test_sends_frames_in_emit_order_with_ids_when_order_read(recorded_app: Any) -> None:
    recorded_app.control.stream = [
        a_log_record("user.message", seq=1),
        DeltaFrame(after_seq=1, block=0, index=0, text="Hel"),
        DeltaFrame(after_seq=1, block=0, index=1, text="lo\nthere"),
        a_log_record("text", seq=2),
        a_log_record("tool.call", seq=3),
        a_log_record("result", seq=4),
        StatusFrame(status=AgentSessionStatus.IDLE),
    ]

    response = recorded_app.client.get(STREAM)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    frames = _frames(response.text)
    assert frames[0] == {"retry": "3000"}
    sent = [(item["event"], item.get("id")) for item in frames[1:]]
    assert sent == [
        ("record.user.message", "1"),
        ("delta", "1.0"),
        ("delta", "1.1"),
        ("record.text", "2"),
        ("record.tool.call", "3"),
        ("record.result", "4"),
        ("status", None),
    ]
    assert '"text":"lo\\nthere"' in frames[3]["data"]


def test_subscribes_from_last_event_id_when_replay_header_and_after_given(
    recorded_app: Any,
) -> None:
    response = recorded_app.client.get(
        STREAM, params={"after": "1"}, headers={"Last-Event-ID": "4.2"}
    )

    assert response.status_code == 200, response.text
    assert _subscribed(recorded_app) == [(AGENT_SESSION_ID, StreamPosition(seq=4, delta=2))]


def test_subscribes_from_after_when_replay_header_missing(recorded_app: Any) -> None:
    recorded_app.client.get(STREAM, params={"after": "3"})

    assert _subscribed(recorded_app) == [(AGENT_SESSION_ID, StreamPosition(seq=3))]


def test_subscribes_from_log_start_when_replay_position_missing(recorded_app: Any) -> None:
    recorded_app.client.get(STREAM)

    assert _subscribed(recorded_app) == [(AGENT_SESSION_ID, StreamPosition(seq=0))]


@pytest.mark.parametrize("last_event_id", ["abc", "1.2.3", "-1", "9" * 40])
def test_sends_reset_then_live_frames_when_replay_id_malformed(
    recorded_app: Any, last_event_id: str
) -> None:
    recorded_app.control.stream = [a_log_record("text", seq=9)]

    response = recorded_app.client.get(STREAM, headers={"Last-Event-ID": last_event_id})

    assert response.status_code == 200, response.text
    frames = _frames(response.text)
    assert [item.get("event") for item in frames] == [None, "reset", "record.text"]
    assert frames[1]["data"] == '{"reason":"unknown_position"}'
    assert "id" not in frames[1]
    assert _subscribed(recorded_app) == [(AGENT_SESSION_ID, None)]


def test_passes_reset_through_when_replay_position_unknown_to_session(
    recorded_app: Any,
) -> None:
    recorded_app.control.stream = [ResetFrame(reason="replay_unavailable")]

    response = recorded_app.client.get(STREAM, headers={"Last-Event-ID": "999"})

    assert [item.get("event") for item in _frames(response.text)] == [None, "reset"]


def test_answers_404_problem_before_any_byte_when_session_unknown(
    recorded_app: Any,
) -> None:
    recorded_app.control.failures["subscribe"] = AgentSessionNotFoundError(AGENT_SESSION_ID)

    response = recorded_app.client.get(STREAM)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-not-found"
    assert "retry" not in response.text


def test_sends_heartbeat_with_last_id_when_replay_stream_quiet(
    recorded_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent_hub.api.routes.agent_session_stream.HEARTBEAT_SECONDS", 0.02)
    recorded_app.control.stream = [
        a_log_record("text", seq=8),
        a_log_record("result", seq=9),
    ]
    recorded_app.control.pause = 0.3

    response = recorded_app.client.get(STREAM, headers={"Last-Event-ID": "7"})

    frames = _frames(response.text)[1:]
    events = [(item["event"], item.get("id")) for item in frames]
    first_record = events.index(("record.text", "8"))
    assert ("heartbeat", "7") in events[:first_record]
    assert ("heartbeat", "8") in events[first_record:]
    assert events[-1] == ("record.result", "9")
    beat = next(item for item in frames if item["event"] == "heartbeat")
    assert beat["data"] == '{"at":"2026-10-11T12:00:00.000Z"}'


def test_closes_subscription_when_stream_ends(recorded_app: Any) -> None:
    recorded_app.control.stream = [a_log_record("text", seq=1)]

    recorded_app.client.get(STREAM)

    assert recorded_app.control.closed


def test_shows_open_request_then_accepts_answer_when_reload_pending(
    recorded_app: Any,
) -> None:
    recorded_app.control.session = an_agent_session(
        status=AgentSessionStatus.WAITING_PERMISSION, open_permission=an_open_permission()
    )

    snapshot = recorded_app.client.get(ONE)
    request_id = snapshot.json()["open_permission"]["request_id"]
    stream = recorded_app.client.get(STREAM)
    answered = recorded_app.client.post(
        f"{ONE}/permissions/{request_id}", json={"decision": "allow"}
    )

    assert (snapshot.status_code, stream.status_code, answered.status_code) == (200, 200, 200)
    assert recorded_app.control.methods() == ["snapshot", "subscribe", "answer"]
    assert recorded_app.control.calls[2][1] == (
        AGENT_SESSION_ID,
        "req-1",
        PermissionDecision(decision="allow"),
    )


# The stream over the real AgentSessionControl (CP): an ended session's stream replays its
# persisted log and ends, so these tests read it whole.

EDIT = ToolCall(
    tool_use_id="tool-1",
    name="Edit",
    input={"file_path": "src/app.py", "old_string": "a = 1\n", "new_string": "a = 2\n"},
)
TURN = (
    TextDelta(block=0, index=0, text="Look"),
    TextBlock(block=0, text="Looking."),
    EDIT,
    ToolResult(tool_use_id="tool-1", content="edited"),
    TextBlock(block=1, text="Done."),
)
BASE = "/api/v1/agent-sessions"
CREATE = {"project": "demo", "workdir_id": WORKDIR_ID}


def _ended(app: Any, prompt: str) -> str:
    response = app.client.post(BASE, json=CREATE | {"prompt": prompt})
    assert response.status_code == 201, response.text
    session_id = str(response.json()["id"])
    app.until_status(session_id, "idle")
    assert app.client.post(f"{BASE}/{session_id}/close", json={}).status_code == 200
    return session_id


def _records(body: str) -> list[dict[str, str]]:
    return [frame for frame in _frames(body) if frame.get("event", "").startswith("record.")]


def test_replays_records_in_seq_order_with_diff_when_order_read(
    open_agent_session_app: Any,
) -> None:
    app = open_agent_session_app(replies={"Fix it.": TURN})
    session_id = _ended(app, "Fix it.")

    response = app.client.get(f"{BASE}/{session_id}/stream")

    assert response.status_code == 200
    records = _records(response.text)
    assert [frame["id"] for frame in records] == [str(n) for n in range(1, len(records) + 1)]
    kinds = [frame["event"].removeprefix("record.") for frame in records]
    assert kinds[:6] == ["user.message", "init", "text", "tool.call", "tool.result", "text"]
    call = json.loads(records[3]["data"])
    assert "+a = 2" in call["body"]["diff"]


def test_replays_after_last_event_id_when_replay_requested(open_agent_session_app: Any) -> None:
    app = open_agent_session_app(replies={"Fix it.": TURN})
    session_id = _ended(app, "Fix it.")

    response = app.client.get(f"{BASE}/{session_id}/stream", headers={"Last-Event-ID": "3"})

    records = _records(response.text)
    assert records[0]["id"] == "4"
    assert all(int(frame["id"]) > 3 for frame in records)


def test_answers_from_snapshot_and_logs_answer_when_reload_pending(
    open_agent_session_app: Any,
) -> None:
    ask = PermissionRequest(request_id="req-1", tool="Bash", input={"command": "make test"})
    app = open_agent_session_app(replies={"Ask first.": (ask, TextBlock(block=0, text="ok"))})
    response = app.client.post(BASE, json=CREATE | {"prompt": "Ask first."})
    session_id = response.json()["id"]
    app.until_status(session_id, "waiting_permission")

    # A reloaded page: the snapshot names the open request, the answer goes through.
    snapshot = app.get(session_id)
    request_id = snapshot["open_permission"]["request_id"]
    answered = app.client.post(
        f"{BASE}/{session_id}/permissions/{request_id}", json={"decision": "allow"}
    )
    app.until_status(session_id, "idle")
    app.client.post(f"{BASE}/{session_id}/close", json={})
    replay = app.client.get(f"{BASE}/{session_id}/stream")

    assert answered.status_code == 200, answered.text
    kinds = [frame["event"] for frame in _records(replay.text)]
    assert kinds.index("record.permission.request") < kinds.index("record.permission.decision")
