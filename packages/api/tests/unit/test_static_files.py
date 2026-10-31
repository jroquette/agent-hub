from pathlib import Path
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


@pytest.mark.parametrize(
    "path",
    [
        "/projects/demo/skills",
        "/projects/demo/skills?q=plan&kind=skill&mode=user-only",
        "/projects/demo/skills/skill/hub-workflow/alpha",
        "/projects/demo/skills/hook/settings/settings-pretooluse-1",
        "/knowledge/skills",
    ],
)
def test_serves_index_when_skills_route_requested(client: Any, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == "<!doctype html><title>agent-hub</title>"
    assert response.headers["content-type"].startswith("text/html")


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


SCRIPT = "/assets/app-AbCd1234.js"
SCRIPT_BYTES = b"console.log('app-AbCd1234')"
# Known bytes, not real Brotli: the server sends a variant as it is and never decodes it.
SCRIPT_BR_BYTES = b"\x1b\x1a\x00\x00stand-in for the Brotli variant"
STYLE = "/assets/plain-AbCd1234.css"
STYLE_BYTES = b"body{color:#101010}"
ROBOTS_BYTES = b"User-agent: *\nDisallow:\n"
INDEX_BYTES = b"<!doctype html><title>agent-hub</title>"
# AC-10: a name that carries its content hash never changes content, so it is kept a year.
IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def compressed_dist(web_dist: Path) -> Path:
    """The built app stand-in plus a hashed script with its Brotli variant beside it, a hashed
    style with none, and a file outside ``assets/``."""
    assets = web_dist / "assets"
    (assets / "app-AbCd1234.js").write_bytes(SCRIPT_BYTES)
    (assets / "app-AbCd1234.js.br").write_bytes(SCRIPT_BR_BYTES)
    (assets / "plain-AbCd1234.css").write_bytes(STYLE_BYTES)
    (web_dist / "robots.txt").write_bytes(ROBOTS_BYTES)
    # The tests tell the variant from the file by its bytes, and their etags apart by its size.
    assert len(SCRIPT_BR_BYTES) != len(SCRIPT_BYTES)
    assert not (assets / "plain-AbCd1234.css.br").exists()
    return web_dist


def _fetch(
    client: Any,
    path: str,
    *,
    accept_encoding: str | None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
) -> tuple[Any, bytes]:
    """Sends exactly this ``Accept-Encoding`` (no such field for ``None``) and keeps the body as
    sent: the test client otherwise adds a field of its own and decodes the codings it knows."""
    request = client.build_request(method, path, headers=headers)
    request.headers.pop("accept-encoding", None)
    if accept_encoding is not None:
        request.headers["accept-encoding"] = accept_encoding
    response = client.send(request, stream=True)
    body = b"".join(response.iter_raw())
    response.close()
    return response, body


def _varies_on(response: Any) -> list[str]:
    """The field names the answer's ``Vary`` lists, lowercased."""
    return [name.strip().lower() for name in response.headers.get("vary", "").split(",")]


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize("accept_encoding", ["br", "br, gzip", "gzip, br;q=0.5", "*"])
def test_serves_brotli_variant_when_client_accepts_br(client: Any, accept_encoding: str) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding=accept_encoding)

    assert (response.status_code, response.headers.get("content-encoding")) == (200, "br")
    assert body == SCRIPT_BR_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
def test_keeps_asset_content_type_when_variant_served(client: Any) -> None:
    variant, _ = _fetch(client, SCRIPT, accept_encoding="br")
    identity, _ = _fetch(client, SCRIPT, accept_encoding="identity")

    answers = [variant, identity]
    assert [answer.headers.get("content-encoding") for answer in answers] == ["br", None]
    assert [answer.headers.get("content-type") for answer in answers] == [
        "text/javascript; charset=utf-8",
        "text/javascript; charset=utf-8",
    ]


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize("accept_encoding", [None, "identity"])
def test_serves_identity_when_client_sends_no_accept_encoding(
    client: Any, accept_encoding: str | None
) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding=accept_encoding)

    assert response.request.headers.get("accept-encoding") == accept_encoding
    assert (response.status_code, response.headers.get("content-encoding")) == (200, None)
    assert body == SCRIPT_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
def test_serves_identity_when_client_accepts_only_gzip(client: Any) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding="gzip")

    assert (response.status_code, response.headers.get("content-encoding")) == (200, None)
    assert body == SCRIPT_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize("accept_encoding", ["br;q=0, gzip", "*;q=0"])
def test_serves_identity_when_client_refuses_br_with_zero_quality(
    client: Any, accept_encoding: str
) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding=accept_encoding)

    assert (response.status_code, response.headers.get("content-encoding")) == (200, None)
    assert body == SCRIPT_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize(
    "accept_encoding",
    [
        pytest.param("br;q=abc", id="q-not-a-number"),
        pytest.param("br;q=1.5", id="q-above-one"),
        # br only after the first 1,024 characters and the first 32 tokens: past the bounds.
        pytest.param("," * 2_000 + "br", id="br-after-2000-commas"),
    ],
)
def test_serves_identity_when_accept_encoding_is_malformed(
    client: Any, accept_encoding: str
) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding=accept_encoding)

    assert (response.status_code, response.headers.get("content-encoding")) == (200, None)
    assert body == SCRIPT_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
def test_serves_identity_when_asset_has_no_variant(client: Any) -> None:
    response, body = _fetch(client, STYLE, accept_encoding="br, gzip")

    assert (response.status_code, response.headers.get("content-encoding")) == (200, None)
    assert body == STYLE_BYTES
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
def test_answers_identity_range_when_range_requested(client: Any) -> None:
    response, body = _fetch(client, SCRIPT, accept_encoding="br", headers={"Range": "bytes=0-6"})

    assert (response.status_code, body) == (206, SCRIPT_BYTES[:7])
    assert response.headers.get("content-range") == f"bytes 0-6/{len(SCRIPT_BYTES)}"
    assert response.headers.get("content-encoding") is None
    assert "accept-encoding" in _varies_on(response)


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize(("accept_encoding", "encoding"), [("br", "br"), ("identity", None)])
def test_answers_not_modified_when_etag_of_same_variant_sent(
    client: Any, accept_encoding: str, encoding: str | None
) -> None:
    first, _ = _fetch(client, SCRIPT, accept_encoding=accept_encoding)
    etag = first.headers.get("etag")
    assert (first.status_code, first.headers.get("content-encoding")) == (200, encoding)
    assert etag is not None

    again, body = _fetch(
        client, SCRIPT, accept_encoding=accept_encoding, headers={"If-None-Match": etag}
    )

    assert (again.status_code, body) == (304, b"")
    # A 304 carries the Vary its 200 would (RFC 9110, 15.4.5), so a cache keeps both apart.
    assert "accept-encoding" in _varies_on(again)


@pytest.mark.usefixtures("compressed_dist")
def test_gives_each_variant_own_etag_when_both_served(client: Any) -> None:
    variant, _ = _fetch(client, SCRIPT, accept_encoding="br")
    identity, _ = _fetch(client, SCRIPT, accept_encoding="identity")

    answers = [variant, identity]
    assert [answer.headers.get("content-encoding") for answer in answers] == ["br", None]
    etags = {answer.headers.get("etag") for answer in answers}
    assert None not in etags
    assert len(etags) == 2


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    ("path", "accept_encoding", "encoding"),
    [
        pytest.param(SCRIPT, "br", "br", id="variant"),
        pytest.param(SCRIPT, "identity", None, id="identity"),
        pytest.param(STYLE, "br", None, id="no-variant"),
    ],
)
def test_marks_assets_immutable_when_fetched(
    client: Any, *, method: str, path: str, accept_encoding: str, encoding: str | None
) -> None:
    response, _ = _fetch(client, path, accept_encoding=accept_encoding, method=method)

    assert response.status_code == 200
    assert response.headers.get("cache-control") == IMMUTABLE
    assert response.headers.get("content-encoding") == encoding


@pytest.mark.usefixtures("compressed_dist")
def test_marks_nothing_immutable_when_file_is_outside_assets(client: Any) -> None:
    response, body = _fetch(client, "/robots.txt", accept_encoding="br, gzip")

    assert (response.status_code, body) == (200, ROBOTS_BYTES)
    assert "immutable" not in response.headers.get("cache-control", "")


@pytest.mark.usefixtures("compressed_dist")
@pytest.mark.parametrize("path", ["/", "/sessions", "/projects/p/brain/now.md"])
def test_keeps_index_no_cache_when_spa_route_requested(client: Any, path: str) -> None:
    response, body = _fetch(client, path, accept_encoding="br, gzip")

    assert (response.status_code, body) == (200, INDEX_BYTES)
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("content-encoding") is None
