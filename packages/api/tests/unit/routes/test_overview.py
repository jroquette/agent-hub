from datetime import UTC, datetime
from typing import Any

from agent_hub.core.projects.project_views import ActivityItem, NeedsYouItem, SearchHit
from agent_hub.core.readmodels.filters import PageRequest, Scope

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def test_maps_scope_when_needs_you_listed(wired: Any) -> None:
    item = NeedsYouItem(
        kind="approval",
        verb="Approve",
        context="guard ask",
        project="demo",
        since=AT,
        href="/approvals/1",
    )
    wired.events.needs.append(item)

    response = wired.client.get("/api/v1/needs-you", params={"project": "demo"})

    assert response.json()["items"] == [item.model_dump(mode="json")]
    assert wired.events.calls == [("needs_you", Scope(project="demo"))]


def test_maps_page_when_activity_listed(wired: Any) -> None:
    wired.events.activity_items.append(
        ActivityItem(kind="failed", text="Run failed", project="demo", at=AT, href=None)
    )

    response = wired.client.get("/api/v1/activity", params={"cursor": "c1", "limit": "3"})

    assert response.json()["items"][0]["at"] == "2026-10-09T14:00:00.000Z"
    assert wired.events.calls == [("activity", PageRequest(cursor="c1", limit=3))]


def test_maps_query_when_search_requested(wired: Any) -> None:
    wired.events.hits.append(
        SearchHit(kind="command", label="make check", detail=None, project="demo", href="/x")
    )

    response = wired.client.get("/api/v1/search", params={"q": "make", "project": "demo"})

    assert response.json()["items"][0]["label"] == "make check"
    assert wired.events.calls == [("search_events", ("make", PageRequest(project="demo")))]
