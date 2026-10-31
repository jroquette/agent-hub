"""The committed build (``web_dist``) as ``hub web`` serves it: each script and style has a
Brotli variant under the ticket's size, and each asset's name carries its content hash."""

import hashlib
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.app import create_app
from agent_hub.api.settings import ApiSettings
from agent_hub.api.static_files import WEB_DIST

ASSETS = WEB_DIST / "assets"
# AC-8: the ticket's 600 KB on the wire, in decimal bytes.
WIRE_LIMIT_BYTES = 600_000
# Q11: the build writes a variant for each script and style of 1 KB or more.
SMALLEST_COMPRESSED_BYTES = 1_024
# Vite names an asset ``<name>-<8-character content hash>.<extension>``.
CONTENT_HASHED_NAME = re.compile(r"-[A-Za-z0-9_-]{8}\.[a-z0-9]+$")


@pytest.fixture
def built_client(api_settings: ApiSettings) -> Iterator[TestClient]:
    """A client of the app serving the committed ``web_dist``."""
    app = create_app(api_settings, web_dist=WEB_DIST)
    base_url = f"http://127.0.0.1:{api_settings.port}"
    with TestClient(app, base_url=base_url, raise_server_exceptions=False) as client:
        yield client


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_accepting_br(client: TestClient, path: str) -> tuple[int, str | None, bool, bytes]:
    """GETs ``path`` as a browser does (``br, gzip``) and keeps the body as sent, never decoded:
    its status, ``Content-Encoding``, whether ``Vary`` names ``Accept-Encoding``, and body."""
    with client.stream("GET", path, headers={"Accept-Encoding": "br, gzip"}) as response:
        body = b"".join(response.iter_raw())
    varies = "accept-encoding" in response.headers.get("vary", "").lower()
    return response.status_code, response.headers.get("content-encoding"), varies, body


def test_serves_every_built_script_and_style_compressed_when_br_accepted(
    built_client: TestClient,
) -> None:
    built = sorted(
        path
        for path in ASSETS.iterdir()
        if path.suffix in {".js", ".css"} and path.stat().st_size >= SMALLEST_COMPRESSED_BYTES
    )
    variants = {path.name: path.with_name(f"{path.name}.br") for path in built}
    assert any(name.startswith("index-") and name.endswith(".js") for name in variants)
    assert [name for name, variant in variants.items() if not variant.is_file()] == []

    answers = {name: _get_accepting_br(built_client, f"/assets/{name}") for name in variants}

    assert {
        name: (status, encoding, varies, _sha256(body))
        for name, (status, encoding, varies, body) in answers.items()
    } == {
        name: (200, "br", True, _sha256(variant.read_bytes())) for name, variant in variants.items()
    }
    assert [name for name, (*_, body) in answers.items() if len(body) >= WIRE_LIMIT_BYTES] == []


def test_names_every_asset_with_content_hash_when_built() -> None:
    names = sorted(
        path.relative_to(ASSETS).as_posix()
        for path in ASSETS.rglob("*")
        if path.is_file() and path.suffix != ".br"
    )
    assert any(name.startswith("index-") and name.endswith(".js") for name in names)

    assert [name for name in names if not CONTENT_HASHED_NAME.search(name)] == []
