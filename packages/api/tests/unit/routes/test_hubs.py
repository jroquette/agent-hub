from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.doctor_fix import DoctorFixResult
from agent_hub.api.platform_sync import PlatformSyncResult
from agent_hub.api.routes import hubs as hub_routes
from agent_hub.core.testing.read_model_builders import HUB_ID, a_hub_view

# The path of ``a_hub_view()``, and this server's Origin, which the hub actions require.
HUB_PATH = "/home/demo/demo-hub"
OWN = {"Origin": "http://127.0.0.1:7420"}


def test_maps_hubs_when_hubs_listed(wired: Any) -> None:
    wired.hubs.hubs.append(a_hub_view())

    response = wired.client.get("/api/v1/hubs")

    assert response.json()["items"] == [a_hub_view().model_dump(mode="json")]


def test_maps_created_hub_when_hub_registered(wired: Any) -> None:
    wired.hubs.hubs.append(a_hub_view())

    response = wired.client.post(
        "/api/v1/hubs",
        json={"path": "/home/demo/other-hub"},
        headers={"Origin": "http://127.0.0.1:7420"},
    )

    assert response.status_code == 201
    assert response.json()["path"] == "/home/demo/other-hub"
    assert wired.hubs.calls == [("register_hub", "/home/demo/other-hub")]


def test_answers_no_content_when_hub_removed(wired: Any) -> None:
    wired.hubs.hubs.append(a_hub_view())

    response = wired.client.delete(
        f"/api/v1/hubs/{HUB_ID}", headers={"Origin": "http://127.0.0.1:7420"}
    )

    assert response.status_code == 204
    assert response.content == b""
    assert wired.hubs.hubs == []


def test_answers_not_found_when_removed_hub_unknown(wired: Any) -> None:
    response = wired.client.delete("/api/v1/hubs/nope", headers={"Origin": "http://127.0.0.1:7420"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No hub with id 'nope'."


def test_answers_unprocessable_when_hub_body_invalid(wired: Any) -> None:
    response = wired.client.post(
        "/api/v1/hubs", json={"path": "", "extra": 1}, headers={"Origin": "http://127.0.0.1:7420"}
    )

    assert response.status_code == 422
    pointers = {error["pointer"] for error in response.json()["errors"]}
    assert pointers == {"/path", "/extra"}
    assert wired.hubs.calls == []


# AC-PG-23.3: a hub.json that cannot be pinned is refused: the route answers the refusal as a
# failed sync (ok false, the reason as its output), and hub.json is left as it was.
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (None, "hub.json cannot be read"),
        ("not json\n", "hub.json is not valid JSON"),
        ('{"schema_version": 1}\n', "hub.json has no platform object"),
    ],
)
def test_answers_refusal_when_hub_json_cannot_be_pinned(
    wired: Any, tmp_path: Path, *, text: str | None, reason: str
) -> None:
    if text is not None:
        (tmp_path / "hub.json").write_text(text, encoding="utf-8")
    wired.hubs.hubs.append(a_hub_view(path=str(tmp_path), running_version="0.9.0"))

    response = wired.client.post(
        f"/api/v1/hubs/{HUB_ID}/platform-sync",
        json={},
        headers={"Origin": "http://127.0.0.1:7420"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["ok"], body["exit_code"], body["output"]) == (False, 1, [reason])
    assert (body["previous_version"], body["version"], body["changed_files"]) == (
        "0.8.0",
        "0.8.0",
        [],
    )
    if text is None:
        assert not (tmp_path / "hub.json").exists()
    else:
        assert (tmp_path / "hub.json").read_text(encoding="utf-8") == text


def _synced(hub_id: str) -> PlatformSyncResult:
    return PlatformSyncResult(
        hub_id=hub_id,
        previous_version="0.8.0",
        version="0.9.0",
        ok=True,
        exit_code=0,
        output=(),
        changed_files=("hub.json", "hub.lock"),
    )


def _sync_failed(hub_id: str) -> PlatformSyncResult:
    return PlatformSyncResult(
        hub_id=hub_id,
        previous_version="0.8.0",
        version="0.9.0",
        ok=False,
        exit_code=1,
        output=("hub sync failed",),
        changed_files=("hub.json",),
    )


def _fixed(hub_id: str) -> DoctorFixResult:
    return DoctorFixResult(
        hub_id=hub_id,
        ok=True,
        exit_code=0,
        output=(),
        changed_files=("AGENTS.md",),
        errors_left=0,
        warnings_left=0,
    )


# AGH-608 AC-26 (A7, review round 2, N5): a hub action marks its hub due at the next tick once it
# is done, whatever its outcome; an unknown hub marks nothing.
@pytest.mark.parametrize(
    ("action", "route", "result"),
    [
        pytest.param("sync_platform", "platform-sync", _synced, id="platform-sync"),
        pytest.param("fix_hub", "doctor-fix", _fixed, id="doctor-fix"),
        pytest.param("sync_platform", "platform-sync", _sync_failed, id="platform-sync-failed"),
    ],
)
def test_marks_written_hub_due_when_write_route_answers(
    wired: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    action: str,
    route: str,
    result: Callable[[str], object],
) -> None:
    wired.hubs.hubs.append(a_hub_view())

    def act(hub_id: str, hub_path: str, **_: object) -> object:
        wired.hubs.calls.append((action, hub_path))
        return result(hub_id)

    monkeypatch.setattr(hub_routes, action, act)
    unknown = wired.client.post(f"/api/v1/hubs/nope/{route}", json={}, headers=OWN)
    assert unknown.status_code == 404, unknown.text
    assert "reread_hubs" not in {name for name, _ in wired.hubs.calls}

    response = wired.client.post(f"/api/v1/hubs/{HUB_ID}/{route}", json={}, headers=OWN)

    assert response.status_code == 200, response.text
    calls = wired.hubs.calls
    assert (action, HUB_PATH) in calls
    assert calls[calls.index((action, HUB_PATH)) :] == [
        (action, HUB_PATH),
        ("reread_hubs", HUB_PATH),
    ]
