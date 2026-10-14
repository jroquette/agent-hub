"""``/sessions`` and ``/live-sessions`` on the composed app (AC-201.3): each item says what the
session is about (``label``, the issue read with the registered hub's tracker teams and branch
prefix) and who acted (``actors``); the OpenAPI document marks the old ``agent`` deprecated."""

import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.driver import PermissionRequest, TextBlock
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
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
    composed.client.post(
        "/api/v1/hubs", json={"path": str(make_hub())}, headers={"Origin": "http://127.0.0.1:7420"}
    )
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
    composed.client.post(
        "/api/v1/hubs", json={"path": str(make_hub())}, headers={"Origin": "http://127.0.0.1:7420"}
    )
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


# AC-165.25: a session hub web drives, whose Claude session id the hook sensor also posts.

TOKEN = "l" * 43
SENT_AT = "2026-10-11T11:59:00.000Z"  # a minute before the composed app's clock
ASK = PermissionRequest(request_id="req-1", tool="Bash", input={"command": "make test"})


def _waiting_agent_session(app: Any, hub: Path) -> dict[str, Any]:
    """An agent session parked on a permission request, started in the hub's workdir."""
    client, base = app.client, "/api/v1/agent-sessions"
    assert (
        client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
        ).status_code
        == 201
    )
    (workdir, *_) = client.get(f"{base}/workdirs", params={"project": "demo"}).json()["items"]
    created = client.post(
        base, json={"project": "demo", "workdir_id": workdir["workdir_id"], "prompt": "Test it."}
    )
    assert created.status_code == 201, created.text
    deadline = time.monotonic() + 5
    while True:
        body: dict[str, Any] = client.get(f"{base}/{created.json()['id']}").json()
        if body["status"] == "waiting_permission" or time.monotonic() > deadline:
            assert body["status"] == "waiting_permission", body
            return body
        time.sleep(0.005)


def test_links_agent_session_when_hook_posts_same_id_agent_session_link(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    driver = InMemorySessionDriver(replies={"Test it.": (ASK, TextBlock(block=0, text="ok"))})
    app = open_composed(replace(composed_settings, session_token=TOKEN), session_driver=driver)
    app.client.headers["Origin"] = f"http://127.0.0.1:{composed_settings.port}"
    app.client.cookies.set(cookie_name(composed_settings.port), TOKEN)
    agent_session = _waiting_agent_session(app, make_hub())
    claude_id = agent_session["claude_session_id"]
    hook = a_hook_input("SessionStart", session_id=claude_id)
    posted = app.client.post(
        "/api/v1/events/hooks", json=an_envelope(hook, sent_at=SENT_AT).model_dump(mode="json")
    )

    session = app.client.get(f"/api/v1/sessions/{claude_id}")
    tiles = {tile["id"]: tile for tile in app.client.get("/api/v1/live-sessions").json()["items"]}

    assert posted.status_code == 202, posted.text
    assert session.status_code == 200, session.text
    assert session.json()["agent_session_id"] == agent_session["id"]
    tile = tiles[claude_id]
    assert (tile["group"], tile["status"]) == ("waiting", "waiting")
    assert tile["waiting_reason"] == "Permission prompt"
    assert tile["agent_session_id"] == agent_session["id"]
