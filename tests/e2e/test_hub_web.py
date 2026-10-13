"""``hub web`` as installed: what it serves and where it listens (AC-200.58), and how its
streams see events another process appends (AC-200.41)."""

import contextlib
import json
import queue
import re
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.core.testing.builders import an_event, events_to_jsonl

REQUEST_SECONDS = 10
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
