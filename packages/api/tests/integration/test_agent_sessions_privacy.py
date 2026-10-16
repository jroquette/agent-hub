"""Privacy of the sessions ``hub web`` drives (AC-165.4, AC-165.36; E3, E9, E10, L4, L5).

Credentials: with sentinel ``ANTHROPIC_API_KEY`` and ``CLAUDE_CODE_OAUTH_TOKEN`` in ``hub web``'s
environment, one turn on the composed app (SQLite, a registered hub, the in-memory driver)
leaks neither into a response, an SSE frame, a stored row or a log line; the children get
``AGENT_HUB_WEB_URL`` only (never the token or the cookie name), and no code opens a
``.credentials.json`` (an ``open`` audit hook watches). Redaction: the store and every replay
carry ``[redacted: <kind>]`` where the live frame, sent from memory while connected, carries
the original; no log line holds conversation text.
"""

import base64
import json
import logging
import os
import sqlite3
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_hub.api.composition import build_app
from agent_hub.api.json_logging import LOGGER, JsonFormatter
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.agent_sessions.driver import (
    PermissionRequest,
    TextBlock,
    TextDelta,
    ToolCall,
    ToolResult,
)
from agent_hub.core.testing.agent_session_rig import START
from agent_hub.core.testing.builders import a_png_bytes
from agent_hub.core.testing.read_model_builders import WORKDIR_ID
from agent_hub.core.testing.session_driver_fakes import Hold, InMemorySessionDriver

BASE = "/api/v1/agent-sessions"
CREATE = {"project": "demo", "workdir_id": WORKDIR_ID}
TOKEN = "p" * 43
# Synthetic, shaped like the secrets they stand for; never real values.
API_KEY = "sk-ant-api03-SYNTHETICwebSessionKEY0123456789"
OAUTH_TOKEN = "sk-ant-oat01-SYNTHETICwebSessionOAUTH0123456789"  # noqa: S105 -- synthetic
TEXT_SECRET = "ghp_SYNTHETICwebSessionTEXT0123456789"  # noqa: S105 -- synthetic
TOOL_SECRET = "lin_api_SYNTHETICwebSessionTOOL0123456789"  # noqa: S105 -- synthetic
MESSAGE = "MESSAGESENTINEL-q4r8-conversation-text"
CREDENTIALS_FILE = ".credentials.json"


class _Lines(logging.Handler):
    """Every record any logger emits, as the JSON line ``hub web`` writes plus its fields."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self._json = JsonFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{self._json.format(record)} {record.__dict__!r}")

    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def log_lines() -> Iterator[_Lines]:
    """Captures every log record, the API's own logger included (it may not propagate)."""
    handler = _Lines()
    root, saved = logging.getLogger(), (logging.getLogger().level, LOGGER.level)
    root.addHandler(handler)
    LOGGER.addHandler(handler)
    root.setLevel(logging.DEBUG)
    LOGGER.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        LOGGER.removeHandler(handler)
        root.setLevel(saved[0])
        LOGGER.setLevel(saved[1])


_OPENED: list[str] = []
_WATCHING = threading.Event()


def _audit(event: str, arguments: tuple[Any, ...]) -> None:
    if event == "open" and _WATCHING.is_set() and arguments:
        path = arguments[0]
        if isinstance(path, (str, bytes, os.PathLike)):
            _OPENED.append(os.fsdecode(path))


sys.addaudithook(_audit)  # An audit hook cannot be removed; it records only while watching.


@pytest.fixture
def opened_files() -> Iterator[list[str]]:
    """The paths opened while the test runs."""
    _OPENED.clear()
    _WATCHING.set()
    try:
        yield _OPENED
    finally:
        _WATCHING.clear()


@contextmanager
def _composed(
    settings: ApiSettings, *, projects_root: Path, web_dist: Path, driver: InMemorySessionDriver
) -> Iterator[TestClient]:
    app = build_app(settings, projects_root=projects_root, web_dist=web_dist, session_driver=driver)
    origin = f"http://127.0.0.1:{settings.port}"
    with TestClient(
        app, base_url=origin, headers={"Origin": origin}, raise_server_exceptions=False
    ) as client:
        client.cookies.set(cookie_name(settings.port), TOKEN)
        yield client


def _until(client: TestClient, session_id: str, status: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while True:
        body: dict[str, Any] = client.get(f"{BASE}/{session_id}").json()
        if body["status"] == status or time.monotonic() > deadline:
            assert body["status"] == status, body
            return body
        time.sleep(0.005)


def _stored_text(db_path: Path) -> str:
    """Every row of every table of the database, as text."""
    with sqlite3.connect(db_path) as connection:
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        rows = [
            repr(row)
            for table in tables
            for row in connection.execute(f'SELECT * FROM "{table}"')  # noqa: S608 -- names from sqlite_master
        ]
    return "\n".join(rows)


def test_leaks_no_sentinel_when_session_runs_one_turn_credentials(  # noqa: PLR0913 -- fixtures
    composed_settings: ApiSettings,
    *,
    monkeypatch: pytest.MonkeyPatch,
    log_lines: _Lines,
    opened_files: list[str],
    projects_root: Path,
    web_dist: Path,
    make_hub: Any,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", API_KEY)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", OAUTH_TOKEN)
    hub = make_hub()
    settings = replace(composed_settings, session_token=TOKEN, clock=lambda: START)
    driver = InMemorySessionDriver(
        replies={"Go.": (TextDelta(block=0, index=0, text="Wor"), TextBlock(block=0, text="Work."))}
    )
    answers: list[str] = []
    with _composed(
        settings, projects_root=projects_root, web_dist=web_dist, driver=driver
    ) as client:
        assert (
            client.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
            ).status_code
            == 201
        )
        workdirs = client.get(f"{BASE}/workdirs", params={"project": "demo"})
        created = client.post(
            BASE,
            json={
                "project": "demo",
                "workdir_id": workdirs.json()["items"][0]["workdir_id"],
                "prompt": "Go.",
            },
        )
        session_id = created.json()["id"]
        _until(client, session_id, "idle")
        closed = client.post(f"{BASE}/{session_id}/close", json={})
        for response in (
            workdirs,
            created,
            closed,
            client.get(f"{BASE}/capabilities"),
            client.get(f"{BASE}/resumable", params={"project": "demo", "workdir_id": "0" * 16}),
            client.get(BASE),
            client.get(f"{BASE}/{session_id}"),
            client.get(f"{BASE}/{session_id}/events"),
            client.get(f"{BASE}/{session_id}/stream"),
            client.get("/api/v1/sessions"),
        ):
            answers.append(f"{response.headers!r} {response.text}")

    start = next(call for call in driver.calls if call.method == "start")
    child_extra = start.args[0].environment_extra  # type: ignore[attr-defined]
    leaked = "\n".join([*answers, log_lines.text(), _stored_text(settings.db_path)])
    assert dict(child_extra) == {"AGENT_HUB_WEB_URL": f"http://127.0.0.1:{settings.port}"}
    assert all(
        TOKEN not in text and cookie_name(settings.port) not in text
        for text in (*child_extra, *child_extra.values())
    )
    assert "record.text" in answers[8]
    assert log_lines.lines, "no log line was captured, so the check proves nothing"
    assert API_KEY not in leaked
    assert OAUTH_TOKEN not in leaked
    assert TOKEN not in log_lines.text()
    assert any(path.endswith("hub.json") for path in opened_files), "the audit hook saw no open"
    assert not [path for path in opened_files if path.endswith(CREDENTIALS_FILE)]


# Redaction over the real use case (the rig): a live stream opened before the turn reads the
# original text; the store, the events page and a replay read the redacted copy.

TURN = (
    Hold(),
    TextBlock(block=0, text=f"Found {TEXT_SECRET} in the config."),
    ToolCall(tool_use_id="tool-1", name="Bash", input={"command": "cat .env"}),
    ToolResult(tool_use_id="tool-1", content=f"LINEAR={TOOL_SECRET}"),
)


def _frames(body: str) -> list[dict[str, str]]:
    frames = []
    for block in body.split("\n\n"):
        fields = dict(line.partition(": ")[::2] for line in block.split("\n") if line)
        if fields:
            frames.append(fields)
    return frames


def _until_subscribed(app: Any, session_id: str) -> None:
    """Waits until a stream is attached to the live session (so its frames come live)."""
    deadline = time.monotonic() + 5
    live = app.rig.control._live  # noqa: SLF001 -- no public count of a session's subscribers
    while not (session_id in live and live[session_id]._subscribers):  # noqa: SLF001
        assert time.monotonic() < deadline, "the stream never attached"
        time.sleep(0.005)


def test_redacts_store_and_keeps_live_raw_when_secrets_streamed_redaction_logs(
    open_agent_session_app: Any, log_lines: _Lines
) -> None:
    app = open_agent_session_app(replies={"Read the config.": TURN})
    created = app.client.post(BASE, json=CREATE | {"prompt": "Read the config."})
    session_id = created.json()["id"]
    app.until_status(session_id, "running")
    live: dict[str, str] = {}
    reader = threading.Thread(
        target=lambda: live.update(body=app.client.get(f"{BASE}/{session_id}/stream").text)
    )
    reader.start()
    _until_subscribed(app, session_id)
    app.run(app.driver.release, app.rig.handle())
    app.until_status(session_id, "idle")
    app.client.post(f"{BASE}/{session_id}/close", json={})
    reader.join(timeout=10)
    page = app.client.get(f"{BASE}/{session_id}/events").text
    replay = app.client.get(f"{BASE}/{session_id}/stream").text
    stored = json.dumps([record.model_dump(mode="json") for record in app.rig.records(session_id)])

    assert not reader.is_alive()
    live_records = {
        frame["event"]: frame["data"]
        for frame in _frames(live["body"])
        if frame.get("event", "").startswith("record.")
    }
    assert TEXT_SECRET in live_records["record.text"]
    assert TOOL_SECRET in live_records["record.tool.result"]
    for copy in (stored, page, replay):
        assert TEXT_SECRET not in copy
        assert TOOL_SECRET not in copy
        assert "[redacted: github token]" in copy
        assert "[redacted: linear key]" in copy
    assert TEXT_SECRET not in log_lines.text()
    assert TOOL_SECRET not in log_lines.text()


def test_logs_no_message_text_when_requests_served_redaction_logs(
    open_agent_session_app: Any, log_lines: _Lines
) -> None:
    ask = PermissionRequest(request_id="req-1", tool="Bash", input={"command": f"echo {MESSAGE}"})
    app = open_agent_session_app(
        replies={f"Start {MESSAGE}": (ask, TextBlock(block=0, text=f"Said {MESSAGE}."))}
    )
    created = app.client.post(BASE, json=CREATE | {"prompt": f"Start {MESSAGE}"})
    session_id = created.json()["id"]
    app.until_status(session_id, "waiting_permission")
    app.client.post(
        f"{BASE}/{session_id}/permissions/req-1",
        json={"decision": "deny", "message": f"No {MESSAGE}"},
    )
    app.until_status(session_id, "idle")
    sent = app.client.post(f"{BASE}/{session_id}/messages", json={"text": f"Then {MESSAGE}"})
    app.until_status(session_id, "idle")
    too_large = app.client.post(f"{BASE}/{session_id}/messages", json={"text": MESSAGE * 5_000})
    app.client.get(f"{BASE}/{session_id}/events")
    app.client.post(f"{BASE}/{session_id}/close", json={})
    app.client.get(f"{BASE}/{session_id}/stream")

    assert (created.status_code, sent.status_code, too_large.status_code) == (201, 202, 413)
    assert MESSAGE not in too_large.text
    assert any('"path":"/api/v1/agent-sessions' in line for line in log_lines.lines)
    assert MESSAGE not in log_lines.text()


# A screenshot (AGH-260): its base64 carries a sentinel run; the image goes to the driver only.

IMAGE_SENTINEL = "SCREENSHOTSENTINEL7f3aQQ"  # 24 base64 characters: 18 bytes, kept aligned


def _png_with_sentinel() -> bytes:
    png = a_png_bytes()
    padded = png + b"\x00" * (-len(png) % 3)
    return padded + base64.b64decode(IMAGE_SENTINEL)


def test_keeps_no_image_when_screenshot_sent(
    open_agent_session_app: Any, log_lines: _Lines
) -> None:
    png = _png_with_sentinel()
    data = base64.b64encode(png).decode()
    assert IMAGE_SENTINEL in data
    app = open_agent_session_app(
        replies={"What is on this screen?": (Hold(), TextBlock(block=0, text="A page."))}
    )
    created = app.client.post(
        BASE,
        json=CREATE
        | {
            "prompt": "What is on this screen?",
            "screenshot": {"media_type": "image/png", "data": data},
        },
    )
    session_id = created.json()["id"]
    app.until_status(session_id, "running")
    live: dict[str, str] = {}
    reader = threading.Thread(
        target=lambda: live.update(body=app.client.get(f"{BASE}/{session_id}/stream").text)
    )
    reader.start()
    _until_subscribed(app, session_id)
    app.run(app.driver.release, app.rig.handle())
    app.until_status(session_id, "idle")
    detail = app.client.get(f"{BASE}/{session_id}").text
    app.client.post(f"{BASE}/{session_id}/close", json={})
    reader.join(timeout=10)
    events = app.client.get(f"{BASE}/{session_id}/events")
    replay = app.client.get(f"{BASE}/{session_id}/stream", headers={"Last-Event-ID": "0"}).text
    stored = json.dumps([record.model_dump(mode="json") for record in app.rig.records(session_id)])

    assert created.status_code == 201, created.text
    assert not reader.is_alive()
    assert "record.text" in live["body"]
    assert "record.user.message" in replay
    for copy in (created.text, detail, events.text, live["body"], replay, stored, log_lines.text()):
        assert IMAGE_SENTINEL not in copy
        assert "data:image/png" not in copy
        assert "iVBORw0KGgo" not in copy
    first = events.json()["items"][0]
    assert first["kind"] == "user.message"
    assert first["body"]["attachments"] == [
        {"kind": "screenshot", "media_type": "image/png", "bytes": len(png)}
    ]
