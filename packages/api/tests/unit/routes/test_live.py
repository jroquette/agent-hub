from datetime import UTC, datetime
from typing import Any

from agent_hub.core.projects.project_views import LiveTile
from agent_hub.core.readmodels.filters import Scope

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def a_tile(**overrides: object) -> LiveTile:
    fields: dict[str, object] = {
        "id": "session-1",
        "project": "demo",
        "repo": "demo-api",
        "agent": "main",
        "status": "live",
        "group": "live",
        "last_action": "Bash make check",
        "last_tool": "Bash",
        "last_activity_at": AT,
        "started_at": AT,
        "turns": 2,
        "tokens_total": 100,
        "files_touched": 1,
        "errors": 0,
        "guard_denials": 0,
        "cost_usd": None,
    }
    return LiveTile.model_validate(fields | overrides)


def test_maps_scope_when_live_sessions_listed(wired: Any) -> None:
    wired.events.tiles.extend([a_tile(), a_tile(id="session-2", project="other")])

    response = wired.client.get("/api/v1/live-sessions", params={"project": "demo"})

    assert [tile["id"] for tile in response.json()["items"]] == ["session-1"]
    assert wired.events.calls == [("list_live_sessions", Scope(project="demo"))]
