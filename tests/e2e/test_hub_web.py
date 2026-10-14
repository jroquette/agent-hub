"""``hub web`` as installed: what it serves and where it listens (AC-200.58), and how its
streams see events another process appends (AC-200.41).

AGH-165: the installed server (with the ``sessions`` extra) drives the stub ``claude`` found on
``PATH`` (E14): on SIGTERM or Ctrl-C it leaves no child it started and stores its sessions as
ended by the server (AC-165.23), and it never upgrades a connection to a WebSocket (AC-165.54)."""

import contextlib
import json
import queue
import re
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.claude_sessions.process_tree import alive
from agent_hub.claude_sessions.testing.scenarios import Scenario, held_turn
from agent_hub.core.testing.builders import an_event, events_to_jsonl
from tests.e2e.conftest import InstalledHub, RunningWeb, StubClaude

REQUEST_SECONDS = 10


@pytest.fixture
def web_extra_env(stub_claude: StubClaude) -> Mapping[str, str]:
    """``hub web`` finds the stub ``claude`` first on ``PATH``."""
    return stub_claude.env


# AC-200.41: the tile arrives within 2 s of the append.
STREAM_SECONDS = 2.0


def _non_loopback_addresses() -> set[str]:
    """This machine's IPv4 addresses other than loopback (none on an isolated box)."""
    found: set[str] = set()
    with contextlib.suppress(OSError):
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    # The address the default route would use; a UDP connect sends nothing.
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe,
        contextlib.suppress(OSError),
    ):
        probe.connect(("192.0.2.1", 9))
        found.add(probe.getsockname()[0])
    return {address for address in found if not address.startswith("127.")}


def test_serves_api_app_and_problems_only_on_loopback_when_started(hub_web: Any) -> None:
    # Each start prints its own session token in the URL (AGH-165, P6).
    assert re.fullmatch(
        rf"agent-hub at {re.escape(hub_web.url)}/\?token=[\w-]{{43,}}\n", hub_web.first_line
    )
    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS) as client:
        status = client.get("/api/v1/collector/status")
        root = client.get("/")
        deep = client.get("/sessions/abc")
        unknown = client.get("/api/v1/nope")

    assert status.status_code == 200
    assert status.json()["db_path"] == str(hub_web.db_path)
    assert root.status_code == deep.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in root.text.lower()
    assert deep.text == root.text
    assert unknown.status_code == 404
    assert unknown.headers["content-type"] == "application/problem+json"
    for address in _non_loopback_addresses():
        with pytest.raises(OSError), socket.create_connection((address, hub_web.port), timeout=2):
            pass


type Messages = queue.Queue[tuple[str, Any]]


def _read_stream(url: str, messages: Messages, stop: threading.Event) -> None:
    """Puts each ``(event, data)`` of the stream on ``messages`` until ``stop`` is set.

    The server ends open streams when it stops; that cut is the stream's end, not an error.
    """
    with contextlib.suppress(httpx.TransportError):
        _read_messages(url, messages, stop)


def _read_messages(url: str, messages: Messages, stop: threading.Event) -> None:
    name = "message"
    with (
        httpx.Client(timeout=httpx.Timeout(REQUEST_SECONDS, read=None)) as client,
        client.stream("GET", url) as response,
    ):
        messages.put(("open", response.status_code))
        for line in response.iter_lines():
            if stop.is_set():
                return
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                messages.put((name, json.loads(line.removeprefix("data:").strip())))
                name = "message"


@contextmanager
def _listening(url: str) -> Iterator[Messages]:
    messages: Messages = queue.Queue()
    stop = threading.Event()
    reader = threading.Thread(target=_read_stream, args=(url, messages, stop), daemon=True)
    reader.start()
    assert messages.get(timeout=REQUEST_SECONDS) == ("open", 200)
    try:
        yield messages
    finally:
        stop.set()


def _first(messages: Messages, wanted: Callable[[str, Any], bool], *, until: float) -> Any:
    while (left := until - time.monotonic()) > 0:
        try:
            name, data = messages.get(timeout=left)
        except queue.Empty:
            break
        if wanted(name, data):
            return data
    return None


def test_streams_tile_and_counts_when_another_process_collects_live_session(
    hub_web: Any,
    *,
    installed_hub: Any,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    events = tmp_path / "live.jsonl"
    started = an_event(
        session="live-1",
        type="session.start",
        timestamp=datetime.now(UTC),
        payload={"trigger": "startup", "cwd": "/work/demo-api"},
    )
    events.write_text(events_to_jsonl([started]), encoding="utf-8")
    collect = [str(installed_hub.executable), "collect", str(events), "--db", str(hub_web.db_path)]

    with (
        _listening(f"{hub_web.url}/api/v1/live-sessions/stream") as tiles,
        _listening(f"{hub_web.url}/api/v1/events/stream") as stream,
    ):
        result = run(collect, env=hub_web.env, cwd=tmp_path)
        appended_at = time.monotonic()
        assert result.returncode == 0, result.stderr
        tile = _first(
            tiles,
            lambda name, data: name == "tile.upsert" and data.get("id") == "live-1",
            until=appended_at + STREAM_SECONDS,
        )
        counts = _first(
            stream,
            lambda name, data: name == "counts" and data.get("live_sessions") == 1,
            until=appended_at + STREAM_SECONDS,
        )

    assert tile is not None, "no tile.upsert for live-1 within 2 s"
    assert counts is not None, "no counts with one live session within 2 s"


# AGH-165: sessions driven by the installed server, on the stub claude.

AGENT_SESSIONS = "/api/v1/agent-sessions"
SHUTDOWN_SECONDS = 5.0
HELD_PROMPT = "Work on it."
HUB_FLAGS = (
    "--repos",
    "acme/demo-api",
    "--hub-repo",
    "acme/demo-hub",
    "--tracker",
    "linear:DEM",
    "--branch-prefix",
    "jdoe/",
    "--author-name",
    "Jane Doe",
    "--author-email",
    "jane@example.com",
)


@contextmanager
def _signed_in(web: RunningWeb) -> Iterator[httpx.Client]:
    """A client that traded the printed token for the cookie, writing from the server's Origin."""
    with httpx.Client(
        base_url=web.url, timeout=REQUEST_SECONDS, headers={"Origin": web.url}
    ) as client:
        exchanged = client.get(f"/?token={web.token}")
        assert exchanged.status_code == 303, exchanged.text
        assert client.cookies.get(f"agent_hub_{web.port}") == web.token
        yield client


def _hub_workdir(client: httpx.Client, installed_hub: InstalledHub, root: Path) -> str:
    """A synthetic hub for ``demo``, registered; its workdir id."""
    hub = root / "demo-hub"
    command = [str(installed_hub.executable), "init", "demo", *HUB_FLAGS, "--dir", str(hub)]
    made = subprocess.run(
        command, cwd=root, env=installed_hub.env, capture_output=True, text=True, check=False
    )
    assert made.returncode == 0, made.stderr
    assert client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201
    listed = client.get(f"{AGENT_SESSIONS}/workdirs", params={"project": "demo"})
    assert listed.status_code == 200, listed.text
    workdir_id: str = listed.json()["items"][0]["workdir_id"]
    return workdir_id


def _running(client: httpx.Client, workdir_id: str) -> str:
    created = client.post(
        AGENT_SESSIONS, json={"project": "demo", "workdir_id": workdir_id, "prompt": HELD_PROMPT}
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["id"]
    deadline = time.monotonic() + REQUEST_SECONDS
    while client.get(f"{AGENT_SESSIONS}/{session_id}").json()["status"] != "running":
        assert time.monotonic() < deadline, "the session never started its turn"
        time.sleep(0.05)
    return session_id


def _stored_endings(db_path: Path) -> list[tuple[str, str | None]]:
    with contextlib.closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute("SELECT status, end_reason FROM agent_sessions").fetchall()
    return [(str(status), reason) for status, reason in rows]


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT], ids=["sigterm", "ctrl_c"])
def test_leaves_no_child_when_sigterm_or_ctrl_c_with_two_sessions_agent_session_shutdown(
    hub_web: RunningWeb,
    *,
    stub_claude: StubClaude,
    installed_hub: InstalledHub,
    tmp_path: Path,
    stop: signal.Signals,
) -> None:
    # Each stub holds its turn, runs a tool in its own session and outlives a closed stdin.
    stub_claude.play(
        Scenario(replies={HELD_PROMPT: held_turn()}, grandchild=True, linger_on_eof=True)
    )
    with _signed_in(hub_web) as client:
        workdir_id = _hub_workdir(client, installed_hub, tmp_path)
        sessions = [_running(client, workdir_id) for _ in range(2)]
    spawns = [record for record in stub_claude.records() if record.event == "spawn"]
    children = [record.pid for record in spawns]
    tools = [record.grandchild_pid for record in spawns if record.grandchild_pid is not None]

    hub_web.process.send_signal(stop)
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    while any(alive(pid) for pid in (*children, *tools)) and time.monotonic() < deadline:
        time.sleep(0.05)
    left = [pid for pid in (*children, *tools) if alive(pid)]
    hub_web.process.wait(timeout=SHUTDOWN_SECONDS)

    assert (len(sessions), len(children), len(tools)) == (2, 2, 2)
    assert left == [], f"still running {SHUTDOWN_SECONDS} s after the signal: {left}"
    assert _stored_endings(hub_web.db_path) == [("ended", "server_stopped")] * 2


UPGRADE = (
    "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: {origin}\r\n"
    "Cookie: agent_hub_{port}={token}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
)


def _upgrade_status(web: RunningWeb, path: str) -> str:
    """The status line the server answers a WebSocket upgrade with ("" when it just closes)."""
    request = UPGRADE.format(path=path, port=web.port, origin=web.url, token=web.token)
    with socket.create_connection(("127.0.0.1", web.port), timeout=REQUEST_SECONDS) as sock:
        sock.sendall(request.encode("ascii"))
        answer = b""
        with contextlib.suppress(TimeoutError, ConnectionResetError):
            while b"\r\n" not in answer and (chunk := sock.recv(4096)):
                answer += chunk
    return answer.split(b"\r\n", 1)[0].decode("latin-1")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/v1/events/stream",
        f"{AGENT_SESSIONS}/0192f3a0-0000-7000-8000-000000000001/stream",
    ],
)
def test_refuses_websocket_upgrade_when_any_path_requested(hub_web: RunningWeb, path: str) -> None:
    status = _upgrade_status(hub_web, path)

    assert not status.startswith("HTTP/1.1 101"), status
