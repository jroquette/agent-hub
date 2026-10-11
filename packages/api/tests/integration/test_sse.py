import json
from datetime import timedelta
from typing import Any

from agent_hub.core.projects.project_views import LiveTile, StreamCounts
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.read_model_builders import a_run, a_session

SESSION_STREAM = "/api/v1/sessions/session-1/events/stream"


def _messages(body: str) -> list[dict[str, Any]]:
    """Each message as its fields; ``data`` parsed from JSON."""
    messages = []
    for block in body.split("\n\n"):
        if not block:
            continue
        fields: dict[str, Any] = {}
        for line in block.split("\n"):
            name, _, value = line.partition(": ")
            fields[name] = json.loads(value) if name == "data" else value
        messages.append(fields)
    return messages


def _close_after(wired: Any, seconds: float) -> None:
    def close(elapsed: float) -> None:
        if elapsed >= seconds:
            wired.feed.close()

    wired.clock.on_sleep = close


def _stream(wired: Any, path: str, last_event_id: str | None = None) -> list[dict[str, Any]]:
    headers = {} if last_event_id is None else {"Last-Event-ID": last_event_id}
    response = wired.client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    return _messages(response.text)


def test_replays_after_last_id_then_heartbeats_when_resume_requested(wired: Any) -> None:
    wired.events.sessions.append(a_session())
    stored = wired.reader.add(*(an_event(session="session-1") for _ in range(5)))
    wired.reader.add(an_event(session="session-2"))
    _close_after(wired, 16)

    messages = _stream(wired, SESSION_STREAM, last_event_id=stored[2].event_id)

    assert messages[0] == {"retry": "3000"}
    replayed = [message for message in messages if message.get("event") == "event"]
    assert [message["id"] for message in replayed] == [stored[3].event_id, stored[4].event_id]
    assert [message["data"]["seq"] for message in replayed] == [4, 5]
    assert replayed[0]["data"]["source_id"] == stored[3].event.source_id
    heartbeat = messages[-1]
    assert heartbeat["event"] == "heartbeat"
    assert heartbeat["id"] == stored[4].event_id
    assert heartbeat["data"] == {"at": "2026-10-11T12:00:15.000Z"}


def test_sends_reset_when_more_than_ten_thousand_events_follow_last_id(wired: Any) -> None:
    stored = wired.reader.add(*(an_event(session="session-1") for _ in range(10_002)))
    _close_after(wired, 1)

    messages = _stream(wired, SESSION_STREAM, last_event_id=stored[0].event_id)

    assert [message.get("event") for message in messages] == [None, "reset"]


def test_replays_all_when_exactly_ten_thousand_events_follow_last_id(wired: Any) -> None:
    stored = wired.reader.add(*(an_event(session="session-1") for _ in range(10_001)))
    _close_after(wired, 1)

    messages = _stream(wired, SESSION_STREAM, last_event_id=stored[0].event_id)

    assert len([message for message in messages if message.get("event") == "event"]) == 10_000


def test_sends_reset_when_last_id_unknown(wired: Any, fakes: Any) -> None:
    wired.reader.add(an_event(session="session-1"))
    _close_after(wired, 1)

    unknown = _stream(wired, SESSION_STREAM, last_event_id=fakes.event_id(99))
    malformed = _stream(wired, SESSION_STREAM, last_event_id="not-an-id")

    assert [message.get("event") for message in unknown] == [None, "reset"]
    assert [message.get("event") for message in malformed] == [None, "reset"]


def test_sends_reset_when_last_id_older_than_a_day(wired: Any) -> None:
    stored = wired.reader.add(an_event(session="session-1"))
    wired.clock.start += timedelta(hours=24, seconds=1)
    _close_after(wired, 1)

    messages = _stream(wired, SESSION_STREAM, last_event_id=stored[0].event_id)

    assert [message.get("event") for message in messages] == [None, "reset"]


def test_sends_heartbeat_without_id_when_nothing_happened(wired: Any) -> None:
    _close_after(wired, 31)

    messages = _stream(wired, SESSION_STREAM)

    assert messages == [
        {"retry": "3000"},
        {"event": "heartbeat", "data": {"at": "2026-10-11T12:00:15.000Z"}},
        {"event": "heartbeat", "data": {"at": "2026-10-11T12:00:30.000Z"}},
    ]


def test_sends_new_events_patch_and_end_when_session_ends_while_open(wired: Any) -> None:
    wired.events.sessions.append(a_session())

    def append_then_close(elapsed: float) -> None:
        if elapsed == 1.0:
            wired.reader.add(an_event(session="session-1", type="session.end"))
            wired.events.sessions[0] = a_session(status="ended", turns=4)
        if elapsed >= 3:
            wired.feed.close()

    wired.clock.on_sleep = append_then_close

    messages = _stream(wired, SESSION_STREAM)

    names = [message.get("event") for message in messages]
    assert names == [None, "event", "session", "end"]
    event_id = wired.reader.stored[0].event_id
    assert all(message["id"] == event_id for message in messages[1:])
    assert messages[2]["data"] == {"status": "ended", "turns": 4}
    assert messages[3]["data"] == {"session_id": "session-1"}


def _tile(**overrides: object) -> LiveTile:
    at = "2026-10-11T11:59:00Z"
    fields: dict[str, object] = {
        "id": "session-1",
        "project": "demo",
        "repo": None,
        "agent": "main",
        "status": "live",
        "group": "live",
        "last_action": None,
        "last_tool": None,
        "last_activity_at": at,
        "started_at": at,
        "turns": 1,
        "tokens_total": 0,
        "files_touched": 0,
        "errors": 0,
        "guard_denials": 0,
        "cost_usd": None,
    }
    return LiveTile.model_validate(fields | overrides)


def test_sends_tile_upsert_and_remove_when_live_sessions_change(wired: Any) -> None:
    wired.events.tiles.append(_tile(id="session-old"))

    def change(elapsed: float) -> None:
        if elapsed == 1.0:
            wired.reader.add(an_event(session="session-1"))
            wired.events.tiles[:] = [_tile()]
        if elapsed >= 3:
            wired.feed.close()

    wired.clock.on_sleep = change

    messages = _stream(wired, "/api/v1/live-sessions/stream?project=demo")

    assert [(message.get("event"), message.get("data", {}).get("id")) for message in messages] == [
        (None, None),
        ("tile.upsert", "session-1"),
        ("tile.remove", "session-old"),
    ]


def test_sends_counts_when_global_counts_change(wired: Any) -> None:
    def change(elapsed: float) -> None:
        if elapsed == 1.0:
            wired.reader.add(an_event())
            wired.events.counts = StreamCounts(
                approvals_open=1, live_sessions=1, failed_runs_7d=0, learnings_proposed=0
            )
        if elapsed >= 16:
            wired.feed.close()

    wired.clock.on_sleep = change

    messages = _stream(wired, "/api/v1/events/stream")

    counts = [message for message in messages if message.get("event") == "counts"]
    assert [message["data"]["approvals_open"] for message in counts] == [1]
    assert messages[-1]["event"] == "heartbeat"
    assert messages[-1]["data"] == {"at": "2026-10-11T12:00:15.000Z", "sources": {}}


def test_sends_run_patch_and_step_when_run_advances(wired: Any) -> None:
    wired.events.runs.append(a_run())

    def change(elapsed: float) -> None:
        if elapsed == 1.0:
            wired.reader.add(an_event(session="run:1a2b3c4d", type="step.end", source="executor"))
            wired.events.runs[0] = a_run(stage="VERIFYING")
        if elapsed >= 3:
            wired.feed.close()

    wired.clock.on_sleep = change

    messages = _stream(wired, "/api/v1/workflow-runs/1a2b3c4d/stream")

    assert [message.get("event") for message in messages] == [None, "run"]
    assert messages[1]["data"] == {"stage": "VERIFYING"}


def test_answers_not_implemented_when_streams_not_wired(client: Any) -> None:
    assert client.get(SESSION_STREAM).status_code == 501
