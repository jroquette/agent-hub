import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from agent_hub.api.app import create_app
from agent_hub.api.server import LoopbackServer, PortInUseError, bind_loopback
from agent_hub.api.settings import ApiSettings


def test_binds_loopback_only_when_port_free() -> None:
    sock = bind_loopback(0)
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        sock.close()


def test_raises_port_in_use_naming_port_when_port_taken() -> None:
    first = bind_loopback(0)
    port = first.getsockname()[1]
    try:
        with pytest.raises(PortInUseError) as raised:
            bind_loopback(port)
    finally:
        first.close()

    assert raised.value.port == port
    assert str(raised.value) == f"port {port} is in use"


def _get(url: str, host: str | None = None) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Host": host} if host else {})  # noqa: S310 -- a loopback URL built here
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 -- same
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_serves_api_until_stopped_when_run(api_settings: ApiSettings, web_dist: Any) -> None:
    sock = bind_loopback(0)
    port = sock.getsockname()[1]
    settings = ApiSettings(
        db_path=api_settings.db_path,
        registry_path=api_settings.registry_path,
        port=port,
        running_version="0.8.0",
    )
    server = LoopbackServer(create_app(settings, web_dist=web_dist), sock)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)

        status, body = _get(f"http://127.0.0.1:{port}/api/v1/nope")
        foreign, _ = _get(f"http://127.0.0.1:{port}/api/v1/nope", host="attacker.example")
    finally:
        server.stop()
        thread.join(timeout=10)

    assert (status, body["status"]) == (404, 404)
    assert foreign == 403
    assert not thread.is_alive()
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
