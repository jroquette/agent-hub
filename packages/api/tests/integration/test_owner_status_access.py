"""The owner's status decision on a feature, on the app as ``hub web`` composes it (ADR 0065).

``POST /features/{project}/{slug}/status`` writes ``status.md`` into the feature's hub folder,
uncommitted, as the owner sign-off writes its eval. It is a strict owner write: this server's
``Origin``, a JSON body and the launch cookie, else nothing is written. The feature's read then
carries the decision (``owner_status``) and its date (``last_activity_on``); ``active`` reopens it.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings

TOKEN = "synthetic-status-token-0123456789abcdefghijkl"  # noqa: S105 -- synthetic
OWN = {"Origin": "http://127.0.0.1:7420"}
SLUG = "demo-feature"
STATUS = f"/api/v1/features/demo/{SLUG}/status"


def _signed(open_composed: Callable[..., Any], settings: ApiSettings) -> Any:
    """The composed app with a launch token, its client holding no cookie yet."""
    return open_composed(replace(settings, session_token=TOKEN))


def _feature(app: Any, make_hub: Callable[..., Path]) -> Path:
    """A registered hub with one feature; its folder."""
    hub = make_hub()
    folder = hub / "brain" / "features" / SLUG
    folder.mkdir(parents=True)
    acs = [{"id": "AC-7.1", "description": "Given x, when y, then z", "passes": True}]
    (folder / "features.json").write_text(json.dumps({"acs": acs}), encoding="utf-8")
    registered = app.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
    assert registered.status_code == 201, registered.text
    return folder


def _owner_status(app: Any) -> Any:
    detail = app.client.get(f"/api/v1/features/demo/{SLUG}")
    assert detail.status_code == 200, detail.text
    return detail.json()["owner_status"]


@pytest.mark.parametrize(
    "cookie",
    [None, "synthetic-wrong-token-0123456789abcdefghijkl"],
    ids=["no-cookie", "wrong-cookie"],
)
def test_refuses_and_writes_nothing_when_status_has_no_launch_cookie(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    cookie: str | None,
) -> None:
    app = _signed(open_composed, composed_settings)
    folder = _feature(app, make_hub)
    if cookie is not None:
        app.client.cookies.set(cookie_name(app.settings.port), cookie)

    response = app.client.post(STATUS, json={"status": "shipped"}, headers=OWN)

    assert response.status_code == 401, response.text
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"
    assert not (folder / "status.md").exists()
    assert _owner_status(app) is None


def test_refuses_and_writes_nothing_when_status_sent_bare(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    app = _signed(open_composed, composed_settings)
    folder = _feature(app, make_hub)

    response = app.client.post(STATUS)

    assert response.status_code == 403, response.text
    assert not (folder / "status.md").exists()


@pytest.mark.parametrize("status", ["shipped", "closed", "paused"])
def test_records_decision_when_owner_marks_feature_with_launch_cookie(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    status: str,
) -> None:
    app = _signed(open_composed, composed_settings)
    folder = _feature(app, make_hub)
    app.client.cookies.set(cookie_name(app.settings.port), TOKEN)

    response = app.client.post(STATUS, json={"status": status, "note": "Done here."}, headers=OWN)

    assert response.status_code == 204, response.text
    text = (folder / "status.md").read_text(encoding="utf-8")
    assert f"status: {status}\n" in text
    assert "provenance: owner\n" in text
    decided = _owner_status(app)
    assert (decided["status"], decided["note"]) == (status, "Done here.")


def test_clears_decision_when_owner_reopens_feature(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    app = _signed(open_composed, composed_settings)
    folder = _feature(app, make_hub)
    app.client.cookies.set(cookie_name(app.settings.port), TOKEN)
    paused = app.client.post(STATUS, json={"status": "paused"}, headers=OWN)
    assert paused.status_code == 204, paused.text

    response = app.client.post(STATUS, json={"status": "active"}, headers=OWN)

    assert response.status_code == 204, response.text
    assert "status: active\n" in (folder / "status.md").read_text(encoding="utf-8")
    assert _owner_status(app) is None


@pytest.mark.parametrize(
    "body",
    [
        {"status": "done"},
        {"status": "shipped", "extra": 1},
        {"status": "shipped", "note": "x" * 2001},
    ],
    ids=["unknown-status", "extra-field", "note-too-long"],
)
def test_answers_unprocessable_and_writes_nothing_when_status_body_invalid(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    body: dict[str, Any],
) -> None:
    app = _signed(open_composed, composed_settings)
    folder = _feature(app, make_hub)
    app.client.cookies.set(cookie_name(app.settings.port), TOKEN)

    response = app.client.post(STATUS, json=body, headers=OWN)

    assert response.status_code == 422, response.text
    assert not (folder / "status.md").exists()


def test_answers_not_found_when_status_feature_unknown(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    app = _signed(open_composed, composed_settings)
    _feature(app, make_hub)
    app.client.cookies.set(cookie_name(app.settings.port), TOKEN)

    response = app.client.post(
        "/api/v1/features/demo/nope/status", json={"status": "closed"}, headers=OWN
    )

    assert response.status_code == 404, response.text
