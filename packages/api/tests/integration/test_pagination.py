"""Snapshot pagination of ``/sessions`` on the composed app (AC-200.32), and 404 problems for
unknown ids through the real read models (AC-200.33)."""

from datetime import timedelta
from typing import Any

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.testing.session_scenarios import SCENARIO_START, a_session_events

SESSIONS = 120
PAGE = 50


def _sessions(first: int, count: int, *, offset_minutes: int = 0) -> list[Event]:
    events: list[Event] = []
    for number in range(first, first + count):
        start = SCENARIO_START + timedelta(minutes=offset_minutes + number)
        events += a_session_events(f"session-{number:03d}", start=start, tools=())
    return events


def _page(composed: Any, cursor: str | None, **params: Any) -> dict[str, Any]:
    query = {"limit": PAGE, **params} | ({} if cursor is None else {"cursor": cursor})
    response = composed.client.get("/api/v1/sessions", params=query)
    assert response.status_code == 200, response.text
    document: dict[str, Any] = response.json()
    return document


@pytest.mark.parametrize("sort", ["-started_at", "started_at", "-last_activity_at"])
def test_lists_each_session_once_when_events_appended_between_pages(
    composed: Any, sort: str
) -> None:
    composed.store.append(_sessions(0, SESSIONS))
    seen: list[str] = []
    cursor: str | None = None
    appended = SESSIONS
    while True:
        page = _page(composed, cursor, sort=sort)
        seen += [item["id"] for item in page["items"]]
        # Between pages: new sessions, and new events in a session already listed.
        composed.store.append(_sessions(appended, 3, offset_minutes=600))
        later = SCENARIO_START + timedelta(days=1, minutes=appended)
        composed.store.append(a_session_events("session-000", start=later, tools=()))
        appended += 3
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == SESSIONS
    assert set(seen) == {f"session-{number:03d}" for number in range(SESSIONS)}


@pytest.mark.parametrize(
    ("params", "parameter"),
    [
        ({"cursor": "not-a-cursor"}, "cursor"),
        ({"cursor": "eyJod20iOiAxfQ"}, "cursor"),
        ({"cost_min": "abc"}, "cost_min"),
        ({"limit": "0"}, "limit"),
    ],
)
def test_answers_bad_request_problem_naming_parameter_when_bad(
    composed: Any, params: dict[str, str], parameter: str
) -> None:
    composed.store.append(_sessions(0, 3))

    response = composed.client.get("/api/v1/sessions", params=params)

    assert response.status_code == 400, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"][0]["parameter"] == parameter


@pytest.mark.parametrize(
    ("path", "entity", "entity_id"),
    [
        ("/api/v1/sessions/nope-session", "session", "nope-session"),
        ("/api/v1/sessions/nope-session/cost", "session", "nope-session"),
        ("/api/v1/workflow-runs/0badc0ffee00", "run", "0badc0ffee00"),
        ("/api/v1/approvals/toolu_nope", "approval", "toolu_nope"),
        ("/api/v1/learnings/learning-nope", "learning", "learning-nope"),
        ("/api/v1/projects/nope-project", "project", "nope-project"),
        ("/api/v1/features/demo/nope-feature", "feature", "demo/nope-feature"),
    ],
)
def test_answers_not_found_problem_naming_id_when_entity_unknown_to_composed_app(
    composed: Any, *, path: str, entity: str, entity_id: str
) -> None:
    composed.store.append(_sessions(0, 2))

    response = composed.client.get(path)

    assert response.status_code == 404, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == f"{entity.capitalize()} not found"
    assert f"'{entity_id}'" in response.json()["detail"]
