"""``/hubs`` on the composed app, over a real ``hubs.json`` and real hub folders (AC-200.34)."""

import json
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_hub.core.testing.builders import an_event

HUBS = "/api/v1/hubs"
# The registry writes require this server's Origin (A11).
OWN = {"Origin": "http://127.0.0.1:7420"}


def test_registers_hub_with_project_pin_lock_and_repos_when_path_is_a_hub(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()

    response = composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN)

    assert response.status_code == 201, response.text
    view = response.json()
    assert view["project"] == "demo"
    assert view["platform_pin"] == composed.settings.running_version
    assert view["lock_state"] is not None
    assert view["repos"] == ["demo-api"]
    assert view["valid"] is True
    assert view["path"] == str(hub.resolve())
    assert [item["id"] for item in composed.client.get(HUBS).json()["items"]] == [view["id"]]


def test_writes_registry_only_its_owner_can_read_when_hub_registered(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN)

    registry = composed.settings.registry_path
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(registry.parent.stat().st_mode) == 0o700


def test_refuses_unprocessable_no_hub_json_when_folder_has_none(
    composed: Any, tmp_path: Path
) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()

    response = composed.client.post(HUBS, json={"path": str(folder)}, headers=OWN)

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "No hub.json"
    assert composed.client.get(HUBS).json()["items"] == []


def test_refuses_unprocessable_with_pointers_when_hub_json_invalid(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    document = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
    document["repos"][0]["dir"] = 7
    document["tracker"] = "linear"
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    response = composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN)

    assert response.status_code == 422, response.text
    problem = response.json()
    assert problem["title"] == "Invalid hub.json"
    pointers = {error["pointer"] for error in problem["errors"]}
    assert {"/repos/0/dir", "/tracker"} <= pointers


def test_refuses_conflict_when_project_registered_by_another_hub(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN)
    twin = make_hub(folder="twin-hub")

    response = composed.client.post(HUBS, json={"path": str(twin)}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert len(composed.client.get(HUBS).json()["items"]) == 1


def test_removes_hub_and_keeps_its_events_when_deleted(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub_id = composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN).json()["id"]
    composed.store.append([an_event(project="demo")])

    response = composed.client.delete(f"{HUBS}/{hub_id}", headers=OWN)

    assert response.status_code == 204
    assert composed.client.get(HUBS).json()["items"] == []
    assert [row.project for row in composed.rows()] == ["demo"]
    assert composed.client.delete(f"{HUBS}/{hub_id}", headers=OWN).status_code == 404
