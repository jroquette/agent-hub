"""The agent connected end to end: a real ``claude -p`` session in a hub made from this working
tree, seen through ``hub web`` (marker ``live("claude")``, run by ``make test-live``).

``hub init`` makes a temp hub (it carries the event sensor), ``hub web`` serves a temp database,
and ``claude -p`` runs a tiny prompt in the hub (one Bash command, one file read, at most three
turns) with ``AGENT_HUB_WEB_URL`` pointing at the server. Claude Code's config folder is a temp
one too (``CLAUDE_CONFIG_DIR``), so the session's transcript is written there and the server
tails it there (``AGENT_HUB_CLAUDE_PROJECTS``); the whole temp folder, transcript and database
included, is deleted afterwards. The API must then show the session with its tool calls, the
file it read, an estimated cost and a prompt kept as a size, never as text.

AGH-165 (AC-165.5): an agent session started through ``hub web``'s own API (``hub web`` drives the
user's ``claude`` with ``CLAUDE_CONFIG_DIR`` set to the temp folder) asks for ``git push origin
main``: the hub's guard hook denies it before any permission prompt reaches the browser, and the
hook-observed session appears in ``GET /sessions``, linked to its agent session.

Skips when ``claude`` is missing or not logged in for a fresh config folder (an API key or
``CLAUDE_CODE_OAUTH_TOKEN`` in the environment, or ``claude auth login`` reaching it). It costs
a few cents; the model is ``AGENT_HUB_LIVE_MODEL``, else Claude Haiku 4.5.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e.conftest import WEB_STOP_SECONDS, free_loopback_port

pytestmark = pytest.mark.live("claude")

PROJECT = "live"
DEFAULT_MODEL = "claude-haiku-4-5"
CLAUDE_SECONDS = 300
COMMAND_SECONDS = 60
REQUEST_SECONDS = 10
# The transcript tail runs on the Stop and SessionEnd hooks; the API sees it right after.
SETTLE_SECONDS = 30
# The parent session's variables a nested claude must not inherit: it would join that session.
INHERITED_SESSION_VARIABLES = frozenset(
    {"CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT"}
)


@dataclass(frozen=True)
class LiveHub:
    """The temp hub, the server watching it and the environment claude runs with."""

    path: Path
    url: str
    token: str
    claude: str
    claude_env: Mapping[str, str]


def _claude_env(config: Path) -> dict[str, str]:
    kept = {
        name: value
        for name, value in os.environ.items()
        if name not in INHERITED_SESSION_VARIABLES and not name.startswith("AGENT_HUB_")
    }
    return kept | {"CLAUDE_CONFIG_DIR": str(config)}


def _logged_in(claude: str, env: Mapping[str, str]) -> bool:
    result = subprocess.run(
        [claude, "auth", "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=COMMAND_SECONDS,
        check=False,
    )
    try:
        return result.returncode == 0 and json.loads(result.stdout).get("loggedIn") is True
    except ValueError:
        return False


def _hub_command(*arguments: str, env: Mapping[str, str], cwd: Path) -> None:
    hub = Path(sys.executable).with_name("hub")
    result = subprocess.run(
        [str(hub), *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=COMMAND_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@contextmanager
def _hub_web(root: Path, *, config: Path) -> Iterator[tuple[str, str]]:
    """``hub web`` of this working tree on a free port, a temp database and registry; it drives
    ``claude`` with the temp config folder. Yields its URL and this start's session token."""
    port = free_loopback_port()
    env = _claude_env(config) | {
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "AGENT_HUB_CLAUDE_PROJECTS": str(config / "projects"),
    }
    hub = Path(sys.executable).with_name("hub")
    command = [str(hub), "web", "--port", str(port), "--db", str(root / "live.db")]
    with (root / "web.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=log, text=True
        )
        try:
            assert process.stdout is not None
            line = process.stdout.readline()
            # The URL carries this start's session token (AGH-165, P6).
            prefix = f"agent-hub at http://127.0.0.1:{port}/?token="
            assert line.startswith(prefix), (root / "web.log").read_text()
            yield f"http://127.0.0.1:{port}", line.strip().removeprefix(prefix)
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=WEB_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.fixture
def live_hub() -> Iterator[LiveHub]:
    claude = shutil.which("claude")
    if claude is None:
        pytest.skip("claude is not on PATH")
    with tempfile.TemporaryDirectory(prefix="agent-hub-live-") as folder:
        root = Path(folder)
        config = root / "claude-config"
        claude_env = _claude_env(config)
        if not _logged_in(claude, claude_env):
            pytest.skip("claude is not logged in for a fresh CLAUDE_CONFIG_DIR")
        hub = root / f"{PROJECT}-hub"
        init_env = {
            name: value for name, value in claude_env.items() if name != "CLAUDE_CONFIG_DIR"
        }
        _hub_command(
            "init",
            PROJECT,
            "--repos",
            "acme/live-api",
            "--tracker",
            "linear:LIV",
            "--branch-prefix",
            "live/",
            "--hub-repo",
            "acme/live-hub",
            "--author-name",
            "Live Test",
            "--author-email",
            "live@example.com",
            "--dir",
            str(hub),
            env=init_env,
            cwd=root,
        )
        with _hub_web(root, config=config) as (url, token):
            yield LiveHub(
                path=hub,
                url=url,
                token=token,
                claude=claude,
                claude_env=claude_env | {"AGENT_HUB_WEB_URL": url},
            )
    assert not root.exists()


def _run_claude(live: LiveHub, prompt: str) -> str:
    """Runs the prompt in the hub; returns the session id claude reports."""
    model = os.environ.get("AGENT_HUB_LIVE_MODEL") or DEFAULT_MODEL
    command = [
        live.claude,
        "-p",
        prompt,
        "--max-turns",
        "3",
        "--model",
        model,
        "--allowedTools",
        "Bash(ls)",
        "Read",
        "--output-format",
        "json",
    ]
    result = subprocess.run(
        command,
        cwd=live.path,
        env=live.claude_env,
        capture_output=True,
        text=True,
        timeout=CLAUDE_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    session_id: str = json.loads(result.stdout)["session_id"]
    return session_id


def _settled(client: httpx.Client, session_id: str) -> dict[str, Any]:
    """The session's views once its tool calls, the read file and a cost are in."""
    deadline = time.monotonic() + SETTLE_SECONDS
    while True:
        views = {
            "session": client.get(f"/api/v1/sessions/{session_id}"),
            "events": client.get(f"/api/v1/sessions/{session_id}/events"),
            "files": client.get(f"/api/v1/sessions/{session_id}/files"),
            "cost": client.get(f"/api/v1/sessions/{session_id}/cost"),
        }
        ready = all(response.status_code == 200 for response in views.values()) and (
            views["cost"].json()["total_usd"] is not None and views["files"].json()["items"]
        )
        if ready or time.monotonic() > deadline:
            return {name: response for name, response in views.items()}
        time.sleep(1)


def test_shows_real_session_with_tools_files_and_cost_when_claude_runs_in_hub(
    live_hub: LiveHub,
) -> None:
    marker = f"marker-{uuid.uuid4().hex}"
    with httpx.Client(base_url=live_hub.url, timeout=REQUEST_SECONDS) as client:
        registered = client.post(
            "/api/v1/hubs", json={"path": str(live_hub.path)}, headers={"Origin": live_hub.url}
        )
        assert registered.status_code == 201, registered.text
        prompt = (
            f"This is test {marker}. Use the Bash tool to run exactly `ls`, then use the Read "
            "tool to read hub.json, then reply with the single word: done."
        )

        session_id = _run_claude(live_hub, prompt)
        views = _settled(client, session_id)

    for name, response in views.items():
        assert response.status_code == 200, f"{name}: {response.text}"
    session = views["session"].json()
    events = views["events"].json()["items"]
    files = views["files"].json()["items"]
    cost = views["cost"].json()
    assert session["project"] == PROJECT
    # Hook events from the hub's sensor and the transcript the server tailed both arrived.
    assert {"claude_code", "transcript"} <= {event["source"] for event in events}
    calls = {event["payload"].get("tool") for event in events if event["type"] == "tool.call"}
    assert {"Bash", "Read"} <= calls
    # The hub is no repo checkout, so the path it read stays absolute (repo files are relative).
    read = [change["path"] for change in files if "read" in change["ops"]]
    assert read == [str(live_hub.path / "hub.json")]
    assert cost["total_usd"] is not None
    prompts = [
        event["payload"]
        for event in events
        if event["type"] == "message" and event["payload"].get("role") == "user"
    ]
    assert prompts
    assert all(prompt.get("chars", 0) > 0 for prompt in prompts)
    every_view = "".join(response.text for response in views.values())
    assert marker not in every_view
    assert "reply with the single word" not in every_view


PUSH_PROMPT = (
    "Use the Bash tool to run exactly `git push origin main` in this folder, then reply with the "
    "single word: done."
)
AGENT_SESSIONS = "/api/v1/agent-sessions"


def _until_idle(client: httpx.Client, agent_session_id: str) -> dict[str, Any]:
    """The agent session once its turn ended, failing if it ever waits on the browser."""
    deadline = time.monotonic() + CLAUDE_SECONDS
    while True:
        body: dict[str, Any] = client.get(f"{AGENT_SESSIONS}/{agent_session_id}").json()
        prompted = body["open_permission"]
        assert prompted is None or "git push" not in json.dumps(prompted), prompted
        if body["status"] in {"idle", "ended", "failed"} or time.monotonic() > deadline:
            return body
        time.sleep(1)


def _with_denial(client: httpx.Client, session_id: str) -> httpx.Response:
    """The hook-observed session once its guard denial is in (the sensor posts it at once)."""
    deadline = time.monotonic() + SETTLE_SECONDS
    while True:
        response = client.get(f"/api/v1/sessions/{session_id}")
        denied = response.status_code == 200 and response.json()["guard_denials"] >= 1
        if denied or time.monotonic() > deadline:
            return response
        time.sleep(1)


def test_denies_guarded_push_when_web_session_runs(live_hub: LiveHub) -> None:
    model = os.environ.get("AGENT_HUB_LIVE_MODEL") or DEFAULT_MODEL
    with httpx.Client(
        base_url=live_hub.url, timeout=REQUEST_SECONDS, headers={"Origin": live_hub.url}
    ) as client:
        assert client.get(f"/?token={live_hub.token}").status_code == 303
        assert client.post("/api/v1/hubs", json={"path": str(live_hub.path)}).status_code == 201
        workdirs = client.get(f"{AGENT_SESSIONS}/workdirs", params={"project": PROJECT}).json()
        created = client.post(
            AGENT_SESSIONS,
            json={
                "project": PROJECT,
                "workdir_id": workdirs["items"][0]["workdir_id"],
                "model": model,
                "prompt": PUSH_PROMPT,
            },
        )
        assert created.status_code == 201, created.text
        agent_session = _until_idle(client, created.json()["id"])
        records = client.get(f"{AGENT_SESSIONS}/{agent_session['id']}/events").json()["items"]
        claude_session = agent_session["claude_session_id"]
        session = _with_denial(client, claude_session)
        client.post(f"{AGENT_SESSIONS}/{agent_session['id']}/close", json={})

    assert agent_session["status"] == "idle", agent_session
    kinds = [record["kind"] for record in records]
    assert "permission.request" not in kinds
    calls = [r for r in records if r["kind"] == "tool.call" and "git push" in json.dumps(r)]
    assert calls, kinds
    assert session.status_code == 200, session.text
    assert session.json()["agent_session_id"] == agent_session["id"]
    assert session.json()["guard_denials"] >= 1
