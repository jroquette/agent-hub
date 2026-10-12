from typing import Any

import pytest

from agent_hub.api.static_files import WEB_DIST


@pytest.mark.parametrize("path", ["/", "/sessions/abc", "/projects/demo/features/x", "/welcome"])
def test_serves_index_when_spa_route_requested(client: Any, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == "<!doctype html><title>agent-hub</title>"
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(
    "path", ["/projects/demo/brain/index.md", "/projects/demo/brain/features/export/spec.md"]
)
def test_serves_index_when_brain_note_route_names_a_markdown_file(client: Any, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == "<!doctype html><title>agent-hub</title>"


def test_serves_asset_when_file_exists(client: Any) -> None:
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('app')"


@pytest.mark.parametrize(
    "path", ["/assets/missing.js", "/favicon.ico", "/assets/../../etc/passwd.txt"]
)
def test_answers_not_found_when_file_with_extension_missing(client: Any, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    "path", ["/api/v1/nope", "/api/v1", "/api/v2/sessions", "/api/v1/sessions/a/b/c"]
)
def test_answers_problem_when_api_404_path_unknown(client: Any, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["instance"] == path


def test_answers_method_not_allowed_when_spa_route_posted(client: Any) -> None:
    response = client.post("/sessions/abc")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD"


def test_ships_built_app_when_package_installed() -> None:
    assert (WEB_DIST / "index.html").is_file()
