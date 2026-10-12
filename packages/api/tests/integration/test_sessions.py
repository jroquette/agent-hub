"""``/sessions`` and ``/live-sessions`` on the composed app (AC-201.3): each item says what the
session is about (``label``, the issue read with the registered hub's tracker teams and branch
prefix) and who acted (``actors``); the OpenAPI document marks the old ``agent`` deprecated."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_hub.core.testing.session_scenarios import (
    a_session_events,
    a_subagent_events,
    an_agent_call,
)

NOW_MINUS = timedelta(minutes=12)


def _labelled_session(composed: Any, *, ended: bool) -> None:
    start = composed.settings.clock() - NOW_MINUS
    tools = (("Skill", {"skill": "create-plan"}), ("Bash", {"command": "make check"}))
    events = a_session_events(
        "session-1",
        start=start,
        tools=tools,
        ended=ended,
        git_branch="jdoe/dem-42-export-button",
        slash_commands=("/feature", "/fix"),
    )
    events += an_agent_call(
        "toolu_agent_1",
        description="Map the collector",
        at=start + timedelta(minutes=5),
        done_at=start + timedelta(minutes=9),
    )
    events += a_subagent_events("agent-7", start=start + timedelta(minutes=6))
    composed.store.append(events)


LABEL = {
    "issue": "DEM-42",
    "workflow": "/feature",
    "workflows": ["/feature", "/fix", "/create-plan"],
    "repo": "demo-api",
    "branch": "jdoe/dem-42-export-button",
}


def _subset(item: dict[str, Any], keys: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in keys}


def test_returns_label_and_actors_when_sessions_listed(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post("/api/v1/hubs", json={"path": str(make_hub())})
    _labelled_session(composed, ended=False)

    sessions = composed.client.get("/api/v1/sessions")
    live = composed.client.get("/api/v1/live-sessions")
    one = composed.client.get("/api/v1/sessions/session-1")

    (listed,) = sessions.json()["items"]
    (tile,) = live.json()["items"]
    for item in (listed, tile, one.json()):
        assert _subset(item["label"], LABEL) == LABEL
        assert item["label"]["derived"] is True
        main, subagent = item["actors"]
        assert (main["kind"], main["type"], main["agent_id"]) == ("main", None, None)
        assert (subagent["kind"], subagent["type"], subagent["agent_id"]) == (
            "subagent",
            "Explore",
            "agent-7",
        )
        assert subagent["description"] == "Map the collector"


def test_leaves_label_issue_empty_when_hub_not_registered(composed: Any) -> None:
    _labelled_session(composed, ended=True)

    (listed,) = composed.client.get("/api/v1/sessions").json()["items"]

    assert listed["label"]["issue"] is None
    assert listed["label"]["workflow"] == "/feature"
    assert listed["label"]["branch"] == "jdoe/dem-42-export-button"


def test_reads_issue_from_worktree_when_label_has_no_branch(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post("/api/v1/hubs", json={"path": str(make_hub())})
    worktree = "/work/demo-api/.claude/worktrees/dem-77-retry"
    composed.store.append(a_session_events("session-2", cwd=worktree))

    (listed,) = composed.client.get("/api/v1/sessions").json()["items"]

    assert (listed["label"]["issue"], listed["label"]["worktree"]) == ("DEM-77", "dem-77-retry")
    assert listed["label"]["branch"] is None


def test_marks_agent_deprecated_when_label_served(composed: Any) -> None:
    schemas = composed.client.get("/api/v1/openapi.json").json()["components"]["schemas"]

    for name in ("Session", "LiveTile"):
        properties = schemas[name]["properties"]
        assert properties["agent"].get("deprecated") is True, name
        assert {"label", "actors", "problems"} <= set(properties), name
