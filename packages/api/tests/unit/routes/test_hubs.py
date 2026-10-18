from pathlib import Path
from typing import Any

import pytest

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
