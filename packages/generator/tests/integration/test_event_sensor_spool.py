"""The hook sensor's spool: an envelope ``hub web`` did not take is kept for a later import.

The rendered ``event_sensor.py`` (and ``pre_tool_use.py``, which sends through it) runs on
``hook_python`` as Claude Code runs it, with ``HOME`` under the test's folder, never inside the
rendered hub's workspace. When nothing listens on the sensor's URL, or the server answers with a
server error, the envelope goes to ``$XDG_STATE_HOME/agent-hub/hook-spool.jsonl`` (else
``~/.local/state/agent-hub/``) as one JSON line; the spool keeps at most ``MAX_SPOOL_BYTES``, and a
trim drops the oldest lines and counts them in a first line ``{"dropped": n}``.
"""

import json
import os
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.testing.builders import a_hub_document

HOOKS = "plugin/hub-workflow/hooks"
SENSOR = f"{HOOKS}/event_sensor.py"
PRE_TOOL_USE = f"{HOOKS}/pre_tool_use.py"
URL_VARIABLE = "AGENT_HUB_WEB_URL"
SPOOL = Path(".local", "state", "agent-hub", "hook-spool.jsonl")
SESSION = "5e55a0b1-0000-4000-8000-000000000002"
# A run of the sensor, startup included, ends within this: its send is bounded by 0.5 s.
RUN_BOUND = 1.0

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub with its ``hub.json``, ``demo-api`` beside it."""
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    (hub.parent / "demo-api").mkdir()
    return hub


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The child's ``HOME``, beside the workspace that holds the hub and its repos."""
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


def a_tool_input(hub: Path, *, command: str = "ls") -> bytes:
    hook = {
        "session_id": SESSION,
        "cwd": str(hub),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "toolu_spool_1",
        "tool_response": {"stdout": "a\n"},
    }
    return json.dumps(hook).encode()


def run(
    run_hook_file: RunHook, python: str, hook: Path, *, stdin: bytes, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    completed = run_hook_file(python, hook, stdin=stdin, cwd=hook.parents[3], env=env)
    assert (completed.returncode, completed.stderr) == (0, b"")
    return completed


def spooled(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines()


def sensor_constant(run_python: Callable[..., Any], python: str, *, hub: Path, name: str) -> int:
    """The rendered sensor's module constant ``name``, as ``python`` imports it."""
    value = run_python(
        python,
        f"import json, event_sensor\nprint(json.dumps(event_sensor.{name}))",
        path=hub / HOOKS,
    )
    assert isinstance(value, int)
    return value


def test_spools_one_private_envelope_line_outside_hub_when_nothing_listens(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
) -> None:
    completed = run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"HOME": str(home)},
    )

    assert completed.stdout == b""
    spool = home / SPOOL
    [line] = spooled(spool)
    envelope = HookEnvelope.model_validate_json(line)
    assert (envelope.project, envelope.hook["tool_use_id"]) == ("demo", "toolu_spool_1")
    assert "tool_response" not in envelope.hook
    assert envelope.hook["tool_response_bytes"] == len(b'{"stdout":"a\\n"}')
    assert stat.S_IMODE(spool.stat().st_mode) == 0o600
    assert stat.S_IMODE(spool.parent.stat().st_mode) == 0o700
    assert hub.parent not in spool.parents
    assert sorted(hub.parent.rglob("hook-spool*")) == []


def test_appends_after_earlier_lines_when_spool_not_empty(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
) -> None:
    env = server_down_env | {"HOME": str(home)}

    for command in ("first", "second"):
        run(
            run_hook_file,
            hook_python,
            hub / SENSOR,
            stdin=a_tool_input(hub, command=command),
            env=env,
        )

    commands = [json.loads(line)["hook"]["tool_input"]["command"] for line in spooled(home / SPOOL)]
    assert commands == ["first", "second"]


def test_spools_nothing_when_server_answers(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=sensor_env | {"HOME": str(home)},
    )

    assert len(event_server.bodies()) == 1
    assert not (home / ".local").exists()


def test_spools_under_xdg_state_home_when_set(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"

    run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"HOME": str(home), "XDG_STATE_HOME": str(state)},
    )

    assert len(spooled(state / "agent-hub" / "hook-spool.jsonl")) == 1
    assert not (home / ".local").exists()


@pytest.mark.parametrize("variables", [{}, {"HOME": "relative/home"}])
def test_spools_nothing_when_no_absolute_home_or_state_folder(
    variables: dict[str, str],
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
) -> None:
    completed = run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | variables,
    )

    assert completed.stdout == b""
    assert sorted(hub.parents[1].rglob("hook-spool*")) == []


def test_drops_oldest_lines_and_counts_them_when_spool_over_cap(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    run_python: Callable[..., Any],
    server_down_env: dict[str, str],
) -> None:
    cap = sensor_constant(run_python, hook_python, hub=hub, name="MAX_SPOOL_BYTES")
    spool = home / SPOOL
    spool.parent.mkdir(parents=True, mode=0o700)
    filler = [
        json.dumps({"filler": index, "pad": "x" * 1000}).encode() for index in range(cap // 1000)
    ]
    spool.write_bytes(b"\n".join([b'{"dropped": 5}', *filler]) + b"\n")
    spool.chmod(0o600)
    assert spool.stat().st_size >= cap - 1000

    run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"HOME": str(home)},
    )

    first, *kept, last = spooled(spool)
    kept_indices = [json.loads(line)["filler"] for line in kept]
    dropped = len(filler) - len(kept_indices)
    assert dropped > 0
    assert json.loads(first) == {"dropped": 5 + dropped}
    assert kept_indices == list(range(dropped, len(filler)))
    assert HookEnvelope.model_validate_json(last).hook["tool_use_id"] == "toolu_spool_1"
    assert spool.stat().st_size <= cap
    assert stat.S_IMODE(spool.stat().st_mode) == 0o600
    assert sorted(path.name for path in spool.parent.iterdir()) == [
        "hook-spool.jsonl",
        "hook-spool.lock",
    ]


def test_writes_nothing_through_link_when_spool_is_link(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"")
    spool = home / SPOOL
    spool.parent.mkdir(parents=True, mode=0o700)
    os.symlink(target, spool)

    completed = run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"HOME": str(home)},
    )

    assert completed.stdout == b""
    assert target.read_bytes() == b""
    assert spool.is_symlink()


def test_writes_nothing_through_link_when_spool_folder_is_link(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
    tmp_path: Path,
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / SPOOL).parent.parent.mkdir(parents=True)
    os.symlink(elsewhere, (home / SPOOL).parent)

    completed = run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"HOME": str(home)},
    )

    assert completed.stdout == b""
    assert list(elsewhere.iterdir()) == []


def test_exits_silently_when_state_folder_cannot_be_made(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "state"
    blocker.write_bytes(b"a file, not a folder")

    completed = run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=server_down_env | {"XDG_STATE_HOME": str(blocker)},
    )

    assert completed.stdout == b""
    assert blocker.read_bytes() == b"a file, not a folder"


def test_spools_decision_then_event_when_guard_denies_and_nothing_listens(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
) -> None:
    push = {
        "session_id": SESSION,
        "cwd": str(hub),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "tool_use_id": "toolu_spool_2",
    }

    completed = run(
        run_hook_file,
        hook_python,
        hub / PRE_TOOL_USE,
        stdin=json.dumps(push).encode(),
        env=server_down_env | {"HOME": str(home)},
    )

    verdict = json.loads(completed.stdout)["hookSpecificOutput"]
    assert verdict["permissionDecision"] == "deny"
    decision, event = (HookEnvelope.model_validate_json(line) for line in spooled(home / SPOOL))
    assert decision.decision is not None
    assert (decision.decision.by, decision.decision.kind) == ("guard", "deny")
    assert event.decision is None
    assert event.hook["tool_use_id"] == "toolu_spool_2"


class _FailingServer(BaseHTTPRequestHandler):
    """Answers every POST with 503, as ``hub web`` does when its store cannot be written."""

    def do_POST(self) -> None:  # noqa: N802 - http.server's method name
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - base signature
        return


@pytest.fixture
def failing_url() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FailingServer)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_spools_envelope_when_server_answers_server_error(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    failing_url: str,
) -> None:
    run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env={URL_VARIABLE: failing_url, "HOME": str(home)},
    )

    assert len(spooled(home / SPOOL)) == 1


@pytest.mark.serial
def test_spools_within_bound_when_server_answers_late(
    *,
    hub: Path,
    home: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    event_server.delay = 3.0
    started = time.monotonic()

    run(
        run_hook_file,
        hook_python,
        hub / SENSOR,
        stdin=a_tool_input(hub),
        env=sensor_env | {"HOME": str(home)},
    )

    assert time.monotonic() - started < RUN_BOUND
    assert len(spooled(home / SPOOL)) == 1
