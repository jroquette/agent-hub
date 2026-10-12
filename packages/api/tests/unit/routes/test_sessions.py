from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from agent_hub.core.events.event import EventType
from agent_hub.core.readmodels.filters import PageRequest, SessionFilter
from agent_hub.core.sessions.session import (
    SessionCost,
    SessionFileChange,
    SessionSummary,
    SummaryLine,
    TimelineEvent,
)
from agent_hub.core.testing.read_model_builders import EVENT_ID, a_session, a_session_problems

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def _timeline_event(event_type: EventType) -> TimelineEvent:
    return TimelineEvent(
        event_id=EVENT_ID,
        seq=1,
        project="demo",
        session="session-1",
        type=event_type,
        timestamp=AT,
        received_at=None,
        latency_ms=None,
        source="claude_code",
        source_id="session-1:PreToolUse:toolu_1",
        repo=None,
        agent="main",
        workflow=None,
        step=None,
        payload={"tool": "Bash"},
    )


def test_maps_filters_and_page_when_sessions_listed(wired: Any) -> None:
    wired.events.sessions.append(a_session())

    response = wired.client.get(
        "/api/v1/sessions",
        params={
            "project": "demo",
            "status": "live",
            "cost_min": "0.5",
            "from": "2026-10-09T00:00:00Z",
            "guard_denial": "true",
            "sort": "cost",
            "limit": "20",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["total_estimate"], body["next_cursor"]) == (1, None)
    assert body["items"][0]["id"] == "session-1"
    assert body["items"][0]["cost_usd"] == "0.0412"
    assert wired.events.calls == [
        (
            "list_sessions",
            SessionFilter(
                project="demo",
                status="live",
                cost_min=Decimal("0.5"),
                started_from=datetime(2026, 10, 9, tzinfo=UTC),
                guard_denial=True,
                sort="cost",
                limit=20,
            ),
        )
    ]


def test_maps_session_when_session_requested(wired: Any) -> None:
    wired.events.sessions.append(a_session())

    response = wired.client.get("/api/v1/sessions/session-1")

    assert response.status_code == 200
    assert response.json() == a_session().model_dump(mode="json")


def test_maps_types_and_page_when_session_events_listed(wired: Any) -> None:
    wired.events.timeline["session-1"] = [
        _timeline_event(EventType.TOOL_CALL),
        _timeline_event(EventType.MESSAGE),
    ]

    response = wired.client.get(
        "/api/v1/sessions/session-1/events",
        params=[("types", "tool.call"), ("types", "tool.result"), ("cursor", "abc")],
    )

    assert response.status_code == 200
    assert [item["type"] for item in response.json()["items"]] == ["tool.call"]
    assert wired.events.calls == [
        (
            "session_events",
            (
                "session-1",
                frozenset({EventType.TOOL_CALL, EventType.TOOL_RESULT}),
                PageRequest(cursor="abc", limit=200),
            ),
        )
    ]


def test_maps_summary_files_and_cost_when_session_parts_requested(wired: Any) -> None:
    wired.events.summaries["session-1"] = SessionSummary(
        session_id="session-1",
        lines=(SummaryLine(text="Edited 2 files", event_id=EVENT_ID),),
        generated_at=AT,
    )
    wired.events.files["session-1"] = [
        SessionFileChange(
            repo="demo-api", path="src/a.py", ops=("edited",), added=3, removed=1, event_ids=()
        )
    ]
    wired.events.costs["session-1"] = SessionCost(
        session_id="session-1",
        model="claude-opus-4-1",
        series=(),
        total_usd=Decimal("1.5"),
        prices_as_of=date(2026, 10, 11),
    )

    summary = wired.client.get("/api/v1/sessions/session-1/summary").json()
    files = wired.client.get("/api/v1/sessions/session-1/files").json()
    cost = wired.client.get("/api/v1/sessions/session-1/cost").json()

    assert summary["lines"] == [{"text": "Edited 2 files", "event_id": EVENT_ID}]
    assert files["items"][0]["path"] == "src/a.py"
    assert (cost["total_usd"], cost["prices_as_of"]) == ("1.5000", "2026-10-11")


def test_answers_not_found_when_session_unknown(wired: Any) -> None:
    for suffix in ("", "/summary", "/events", "/files", "/cost"):
        response = wired.client.get(f"/api/v1/sessions/nope{suffix}")

        assert response.status_code == 404, suffix
        assert response.json()["detail"] == "No session with id 'nope'."


def test_maps_problems_when_session_problems_requested(wired: Any) -> None:
    wired.events.problems["session-1"] = a_session_problems()

    response = wired.client.get("/api/v1/sessions/session-1/problems")

    assert response.status_code == 200
    assert response.json() == a_session_problems().model_dump(mode="json")
    assert wired.events.calls == [("session_problems", "session-1")]


def test_answers_not_found_when_problems_of_unknown_session_requested(wired: Any) -> None:
    response = wired.client.get("/api/v1/sessions/nope/problems")

    assert response.status_code == 404
    assert response.json()["detail"] == "No session with id 'nope'."
