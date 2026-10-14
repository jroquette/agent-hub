from typing import Any

from agent_hub.core.testing.read_model_builders import HUB_ID, a_hub_view


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
