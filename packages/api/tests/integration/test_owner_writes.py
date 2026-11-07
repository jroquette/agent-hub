"""The owner's writes on the composed app (AGH-699, audit C-2).

The Hub config writes, the hub actions, the learning decisions, the Linear key, a feature's
nickname and the owner sign-off are made only from the owner's own page, which holds the launch
cookie. This server's exact ``Origin`` is not enough: any local process can send it. So without
the cookie each one answers 401 before its route runs and nothing changes on disk, and in the
container, where no token is minted, each one is off (404 ``owner-writes-off``), as
``docs/API.md`` (Local security) says.
"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.doctor_fix import DoctorFixResult
from agent_hub.api.linear_connection import KEY_FILE_NAME
from agent_hub.api.platform_sync import PlatformSyncResult
from agent_hub.api.routes import hubs as hub_routes
from agent_hub.api.settings import ApiSettings

TOKEN = "synthetic-owner-launch-token-0123456789abcdefghij"  # noqa: S105 -- synthetic
OWN = {"Origin": "http://127.0.0.1:7420"}
# Synthetic keys in Linear's shape, never real ones.
SAVED_KEY = "lin_api_" + "s" * 40
FORGED_KEY = "lin_api_" + "m" * 40
FORGED_MARK = "forged-write.txt"

OWNER_WRITES = [
    pytest.param(
        "PUT",
        "/api/v1/projects/demo/config/local",
        {"author_name": "Mallory", "author_email": "mallory@example.com"},
        id="config-local",
    ),
    pytest.param(
        "POST",
        "/api/v1/projects/demo/config/environments",
        {"op": "add_environment", "scope": "team", "name": "qa", "access": "read"},
        id="config-environments",
    ),
    pytest.param(
        "POST",
        "/api/v1/projects/demo/config/repos",
        {
            "op": "add_repo",
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check": "make check",
            "check_fast": "make check-fast",
        },
        id="config-repos",
    ),
    pytest.param("POST", "/api/v1/hubs/{hub_id}/platform-sync", {}, id="platform-sync"),
    pytest.param("POST", "/api/v1/hubs/{hub_id}/doctor-fix", {}, id="doctor-fix"),
    pytest.param(
        "POST", "/api/v1/learnings/learning-1/accept", {"target": "learnings/"}, id="accept"
    ),
    pytest.param("POST", "/api/v1/learnings/learning-1/reject", {"reason": "No"}, id="reject"),
    pytest.param(
        "POST",
        "/api/v1/learnings/decisions",
        {"decisions": [{"learning_id": "learning-1", "action": "reject", "reason": "No"}]},
        id="learning-decisions",
    ),
    pytest.param("PUT", "/api/v1/tracker/linear", {"api_key": FORGED_KEY}, id="linear-connect"),
    pytest.param("DELETE", "/api/v1/tracker/linear", None, id="linear-disconnect"),
    pytest.param(
        "PUT",
        "/api/v1/feature-names",
        {"project": "demo", "slug": "demo-feature", "name": "Mallory"},
        id="feature-name",
    ),
    pytest.param(
        "POST",
        "/api/v1/features/demo/demo-feature/owner-signoff",
        {"acs": ["AC-1"], "decision": "done"},
        id="owner-signoff",
    ),
]


def _accepting_linear(
    url: str, headers: Any, body: bytes, *, timeout_s: float
) -> tuple[int, bytes]:
    """A Linear that accepts any key, so a forged connect would save its key."""
    viewer = b'{"viewer": {"name": "Mallory", "email": "mallory@example.com"}'
    return 200, b'{"data": ' + viewer + b', "organization": {"name": "Demo", "urlKey": "demo"}}}'


def _marking_action(hub_id: str, hub_path: str, **_: object) -> Any:
    """A hub action's stand-in that writes into the hub, as ``hub sync`` or the fix would."""
    (Path(hub_path) / FORGED_MARK).write_text("written\n", encoding="utf-8")
    return DoctorFixResult(
        hub_id=hub_id,
        ok=True,
        exit_code=0,
        output=(),
        changed_files=(FORGED_MARK,),
        errors_left=0,
        warnings_left=0,
    )


def _marking_sync(hub_id: str, hub_path: str, **_: object) -> PlatformSyncResult:
    (Path(hub_path) / FORGED_MARK).write_text("written\n", encoding="utf-8")
    return PlatformSyncResult(
        hub_id=hub_id,
        previous_version=None,
        version="0.0.0",
        ok=True,
        exit_code=0,
        output=(),
        changed_files=(FORGED_MARK,),
    )


def _files(*roots: Path) -> dict[Path, bytes]:
    """Every file under ``roots`` with its bytes."""
    return {path: path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}


def _owner_world(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, str, list[Path]]:
    """The composed app with a registered hub and a saved Linear key; its hub actions write
    into the hub. Returns the app, the hub's id and the folders a forged write would change."""
    monkeypatch.setattr(hub_routes, "sync_platform", _marking_sync)
    monkeypatch.setattr(hub_routes, "fix_hub", _marking_action)
    app = open_composed(settings, linear_post=_accepting_linear)
    hub = make_hub()
    registered = app.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
    assert registered.status_code == 201, registered.text
    config = settings.registry_path.parent
    (config / KEY_FILE_NAME).write_text(SAVED_KEY + "\n", encoding="utf-8")
    return app, registered.json()["id"], [hub, config]


@pytest.mark.parametrize(("method", "path", "body"), OWNER_WRITES)
def test_answers_unauthorized_and_changes_nothing_when_owner_write_has_no_cookie(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    settings = replace(composed_settings, session_token=TOKEN)
    app, hub_id, folders = _owner_world(open_composed, settings, make_hub, monkeypatch=monkeypatch)
    before = _files(*folders)

    response = app.client.request(method, path.format(hub_id=hub_id), json=body, headers=OWN)

    assert response.status_code == 401, response.text
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"
    assert _files(*folders) == before


@pytest.mark.parametrize(("method", "path", "body"), OWNER_WRITES)
def test_answers_off_and_changes_nothing_when_owner_write_in_container(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    settings = replace(composed_settings, session_token=None, sessions_off=True)
    app, hub_id, folders = _owner_world(open_composed, settings, make_hub, monkeypatch=monkeypatch)
    before = _files(*folders)

    response = app.client.request(method, path.format(hub_id=hub_id), json=body, headers=OWN)

    assert response.status_code == 404, response.text
    problem = response.json()
    assert (problem["type"], problem["title"]) == (
        "urn:agent-hub:problem:owner-writes-off",
        "Owner writes are off",
    )
    assert _files(*folders) == before
