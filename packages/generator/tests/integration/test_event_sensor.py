"""The rendered hook sensor ``event_sensor.py`` (AGH-200 D6, E2; AC-200.5, AC-200.6).

Each hook input runs through the sensor as Claude Code runs it: the file on ``hook_python`` (this
interpreter and a real 3.9) with the input on stdin, in an environment built from scratch. The
sensor posts one v1 envelope to the event server (``event_server``), or nothing; it never prints
and always exits 0, within about the 0.5 s bound of its send.
"""

import json
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.ingestion.hook_envelope import HookEnvelope
from agent_hub.core.testing import builders
from agent_hub.core.testing.builders import a_hub_document

HOOKS = "plugin/hub-workflow/hooks"
SENSOR = f"{HOOKS}/event_sensor.py"
URL_VARIABLE = "AGENT_HUB_WEB_URL"
HOOKS_PATH = "/api/v1/events/hooks"
# A run of the sensor, startup included, ends within this: its send is bounded by 0.5 s.
RUN_BOUND = 1.0
OMIT_LIMIT = 65_536
SESSION = "5e55a0b1-0000-4000-8000-000000000001"

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]


def hook_input(event: str, cwd: Path) -> dict[str, Any]:
    """A synthetic input of each of the eleven registered hook events (E2)."""
    common = {
        "session_id": SESSION,
        "transcript_path": f"/home/u/.claude/projects/x/{SESSION}.jsonl",
        "cwd": str(cwd),
        "hook_event_name": event,
        "permission_mode": "default",
    }
    tool = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "toolu_01"}
    agent = {"agent_id": "a1", "agent_type": "Explore"}
    extra: dict[str, dict[str, Any]] = {
        "SessionStart": {"source": "startup", "model": "claude-x"},
        "UserPromptSubmit": {"prompt": "hello"},
        "PreToolUse": tool,
        "PostToolUse": tool | {"tool_response": {"stdout": "a\n"}, "duration_ms": 12},
        "PostToolUseFailure": tool | {"error": "exit 1\nmore", "is_interrupt": False},
        "Notification": {"message": "needs you", "notification_type": "permission_prompt"},
        "Stop": {"stop_hook_active": False},
        "SubagentStart": agent,
        "SubagentStop": agent | {"agent_transcript_path": "/x/agent-a1.jsonl"},
        "PreCompact": {"trigger": "manual"},
        "SessionEnd": {"reason": "other"},
    }
    return common | extra[event]


def reduced(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """What the sensor sends of ``hook_input(event, ...)``: the prompt and output reduced (S1)."""
    sent = dict(data)
    if event == "UserPromptSubmit":
        prompt = sent.pop("prompt")
        sent["prompt_chars"] = len(prompt)
    if event == "PostToolUse":
        response = sent.pop("tool_response")
        sent["tool_response_bytes"] = len(json.dumps(response, separators=(",", ":")).encode())
    return sent


EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "SessionEnd",
)

# A child's sitecustomize (``PYTHONPATH``) that logs every socket connect and name lookup to
# ``$SOCKET_PROBE_LOG``: proof that a refused URL opens no socket (AC-200.6).
SOCKET_PROBE = """\
import json, os, socket

_log = os.environ["SOCKET_PROBE_LOG"]


def _record(kind, detail):
    with open(_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps([kind, repr(detail)]) + "\\n")


_connect, _connect_ex, _lookup = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def connect(self, address):
    _record("connect", address)
    return _connect(self, address)


def connect_ex(self, address):
    _record("connect", address)
    return _connect_ex(self, address)


def getaddrinfo(*args, **kwargs):
    _record("getaddrinfo", args[:2])
    return _lookup(*args, **kwargs)


socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
socket.getaddrinfo = getaddrinfo
"""


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub with its ``hub.json``, and ``demo-api`` with one worktree beside it."""
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    for folder in ("src", ".claude/worktrees/agh-1-x/src"):
        (hub.parent / "demo-api" / folder).mkdir(parents=True)
    return hub


def run_sensor(
    run_hook_file: RunHook,
    python: str,
    hub: Path,
    *,
    stdin: bytes,
    env: Mapping[str, str],
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    """(the sensor's run, its wall time in seconds)."""
    started = time.monotonic()
    completed = run_hook_file(python, hub / SENSOR, stdin=stdin, cwd=cwd or hub, env=env)
    return completed, time.monotonic() - started


def assert_silent(completed: subprocess.CompletedProcess[bytes]) -> None:
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, b"", b"")


@pytest.mark.serial
@pytest.mark.parametrize("event", EVENTS)
def test_posts_envelope_when_server_up(
    event: str,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    data = hook_input(event, hub)

    completed, elapsed = run_sensor(
        run_hook_file, hook_python, hub, stdin=json.dumps(data).encode(), env=sensor_env
    )

    assert_silent(completed)
    assert elapsed < RUN_BOUND
    [received] = event_server.received
    assert (received.method, received.path) == ("POST", HOOKS_PATH)
    assert received.headers["Content-Type"] == "application/json"
    envelope = HookEnvelope.model_validate_json(received.body)
    assert envelope.v == 1
    assert (envelope.project, envelope.repo) == ("demo", None)
    assert (envelope.run, envelope.step, envelope.attempt, envelope.decision) == (None,) * 4
    assert envelope.hook == reduced(event, data)


@pytest.mark.parametrize(
    ("folder", "repo"),
    [
        ("demo-api", "demo-api"),
        ("demo-api/src", "demo-api"),
        ("demo-api/.claude/worktrees/agh-1-x/src", "demo-api"),
        ("demo-hub", None),
        ("elsewhere", None),
    ],
)
def test_posts_repo_of_cwd_when_cwd_in_repo_or_worktree(
    folder: str,
    repo: str | None,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    cwd = hub.parent / folder
    cwd.mkdir(parents=True, exist_ok=True)
    stdin = json.dumps(hook_input("PreToolUse", cwd)).encode()

    completed, _ = run_sensor(run_hook_file, hook_python, hub, stdin=stdin, env=sensor_env, cwd=cwd)

    assert_silent(completed)
    [body] = event_server.bodies()
    assert body["repo"] == repo


@pytest.mark.serial
@pytest.mark.parametrize("event", EVENTS)
def test_exits_silently_when_server_down(
    event: str,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
) -> None:
    stdin = json.dumps(hook_input(event, hub)).encode()

    completed, elapsed = run_sensor(
        run_hook_file, hook_python, hub, stdin=stdin, env=server_down_env
    )

    assert_silent(completed)
    assert elapsed < RUN_BOUND


@pytest.mark.serial
def test_exits_within_bound_when_server_down_slow(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    event_server.delay = 3.0
    stdin = json.dumps(hook_input("PostToolUse", hub)).encode()

    completed, elapsed = run_sensor(run_hook_file, hook_python, hub, stdin=stdin, env=sensor_env)

    assert_silent(completed)
    assert elapsed < RUN_BOUND


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:7420",
        "https://127.0.0.1:7420",
        "http://127.0.0.1.example.com:7420",
        "http://user@127.0.0.1:7420",
        "http://127.0.0.1:7420/elsewhere",
        "http://127.0.0.2:7420",
        "http://127.0.0.1:99999",
        "ftp://localhost:7420",
    ],
)
def test_opens_no_socket_when_url_not_loopback(
    url: str, *, hub: Path, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    probe, log = tmp_path / "probe", tmp_path / "sockets.log"
    probe.mkdir()
    (probe / "sitecustomize.py").write_text(SOCKET_PROBE, encoding="utf-8")
    env = {URL_VARIABLE: url, "PYTHONPATH": str(probe), "SOCKET_PROBE_LOG": str(log)}
    stdin = json.dumps(hook_input("PreToolUse", hub)).encode()

    completed, _ = run_sensor(run_hook_file, hook_python, hub, stdin=stdin, env=env)

    assert_silent(completed)
    assert not log.exists(), log.read_text(encoding="utf-8")


def test_connects_to_loopback_when_url_is_loopback(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    tmp_path: Path,
) -> None:
    # The probe's counterpart: the same probe logs the connect of an allowed URL.
    probe, log = tmp_path / "probe", tmp_path / "sockets.log"
    probe.mkdir()
    (probe / "sitecustomize.py").write_text(SOCKET_PROBE, encoding="utf-8")
    url = event_server.url.replace("127.0.0.1", "localhost") + "/"
    env = {URL_VARIABLE: url, "PYTHONPATH": str(probe), "SOCKET_PROBE_LOG": str(log)}
    stdin = json.dumps(hook_input("PreToolUse", hub)).encode()

    completed, _ = run_sensor(run_hook_file, hook_python, hub, stdin=stdin, env=env)

    assert_silent(completed)
    assert "connect" in log.read_text(encoding="utf-8")
    assert len(event_server.bodies()) == 1


def test_omits_strings_when_oversize(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    data = hook_input("PostToolUseFailure", hub)
    data["error"] = "é" * OMIT_LIMIT
    data["extra"] = {"lines": ["x" * (OMIT_LIMIT + 1), "ok"]}
    data["tool_input"] = {"command": "y" * OMIT_LIMIT}

    completed, _ = run_sensor(
        run_hook_file, hook_python, hub, stdin=json.dumps(data).encode(), env=sensor_env
    )

    assert_silent(completed)
    [body] = event_server.bodies()
    assert body["hook"]["error"] == {"_omitted_bytes": 2 * OMIT_LIMIT}
    assert body["hook"]["extra"] == {"lines": [{"_omitted_bytes": OMIT_LIMIT + 1}, "ok"]}
    assert body["hook"]["tool_input"] == {"command": "y" * OMIT_LIMIT}
    HookEnvelope.model_validate(body)


@pytest.mark.parametrize("size", ["envelope_over_1_mib", "stdin_over_16_mib"])
def test_sends_nothing_when_oversize(
    size: str,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    data = hook_input("PostToolUse", hub)
    if size == "envelope_over_1_mib":  # each string is kept, together they pass 1 MiB
        data["tool_input"] = {"parts": ["z" * 60_000] * 20}
    else:
        data["tool_response"] = {"stdout": "z" * (16 * 1024 * 1024)}

    completed, _ = run_sensor(
        run_hook_file, hook_python, hub, stdin=json.dumps(data).encode(), env=sensor_env
    )

    assert_silent(completed)
    assert event_server.received == []


@pytest.mark.parametrize("stdin", [b"", b"[]", b'"x"', b"\xff", b"{", b"[" * 100_000])
def test_sends_nothing_when_input_not_object(
    stdin: bytes,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    completed, _ = run_sensor(run_hook_file, hook_python, hub, stdin=stdin, env=sensor_env)

    assert_silent(completed)
    assert event_server.received == []


def test_sends_nothing_when_no_hub_found(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
    tmp_path: Path,
) -> None:
    # The plugin cache: no hub holds the file, and none is above the session's cwd.
    cache = tmp_path / "cache" / "hooks"
    cache.mkdir(parents=True)
    for source in (hub / HOOKS).glob("*.py"):
        (cache / source.name).write_bytes(source.read_bytes())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stdin = json.dumps(hook_input("PreToolUse", elsewhere)).encode()

    completed = run_hook_file(
        hook_python, cache / "event_sensor.py", stdin=stdin, cwd=elsewhere, env=sensor_env
    )

    assert_silent(completed)
    assert event_server.received == []


@pytest.mark.parametrize(
    ("variables", "fields"),
    [
        (
            {"AGENT_HUB_RUN_ID": "0a1b2c3d", "AGENT_HUB_STEP": "plan", "AGENT_HUB_ATTEMPT": "2"},
            {"run": "0a1b2c3d", "step": "plan", "attempt": 2},
        ),
        (
            {
                "AGENT_HUB_RUN_ID": "0a1b2c3d4e5f",
                "AGENT_HUB_STEP": "s" * 40,
                "AGENT_HUB_ATTEMPT": "99",
            },
            {"run": "0a1b2c3d4e5f", "step": "s" * 40, "attempt": 99},
        ),
        (
            {"AGENT_HUB_RUN_ID": "0A1B2C3D", "AGENT_HUB_STEP": "s" * 41, "AGENT_HUB_ATTEMPT": "0"},
            {"run": None, "step": None, "attempt": None},
        ),
        (
            {"AGENT_HUB_RUN_ID": "0a1b2c3", "AGENT_HUB_STEP": "", "AGENT_HUB_ATTEMPT": "100"},
            {"run": None, "step": None, "attempt": None},
        ),
        (
            {"AGENT_HUB_RUN_ID": "0a1b2c3d4e5f6", "AGENT_HUB_ATTEMPT": "+3"},
            {"run": None, "step": None, "attempt": None},
        ),
        ({"AGENT_HUB_ATTEMPT": "x"}, {"run": None, "step": None, "attempt": None}),
    ],
)
def test_posts_run_fields_when_env_set(
    variables: dict[str, str],
    fields: dict[str, Any],
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    stdin = json.dumps(hook_input("SessionStart", hub)).encode()

    completed, _ = run_sensor(
        run_hook_file, hook_python, hub, stdin=stdin, env=sensor_env | variables
    )

    assert_silent(completed)
    [body] = event_server.bodies()
    assert {key: body[key] for key in fields} == fields
    HookEnvelope.model_validate(body)


# S1: the body of a prompt, a written file, an edit or a tool's output never leaves the machine.
BODY = "SENTINEL-body-never-sent"


def _sent_hook(
    data: dict[str, Any],
    *,
    hub: Path,
    python: str,
    run_hook_file: RunHook,
    event_server: Any,
    env: dict[str, str],
) -> dict[str, Any]:
    completed, _ = run_sensor(run_hook_file, python, hub, stdin=json.dumps(data).encode(), env=env)
    assert_silent(completed)
    [body] = event_server.bodies()
    HookEnvelope.model_validate(body)
    assert BODY not in json.dumps(body)
    hook: dict[str, Any] = body["hook"]
    return hook


@pytest.mark.parametrize(
    ("prompt", "command"),
    [(f"/feature add the export {BODY}", "/feature"), (f"plain words {BODY}", None)],
)
def test_sends_prompt_length_and_command_when_prompt_submitted(
    prompt: str,
    command: str | None,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    data = hook_input("UserPromptSubmit", hub) | {"prompt": "  " + prompt}

    hook = _sent_hook(
        data,
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        event_server=event_server,
        env=sensor_env,
    )

    assert "prompt" not in hook
    assert hook["prompt_chars"] == len(prompt) + 2
    assert hook.get("prompt_slash_command") == command


@pytest.mark.parametrize(
    ("tool_input", "sent"),
    [
        (
            {"file_path": "/w/demo-api/a.py", "content": f"one\n{BODY}\nthree\n"},
            {"file_path": "/w/demo-api/a.py", "content_lines": 3},
        ),
        (
            {"file_path": "/w/demo-api/big.txt", "content": f"{BODY}\n" * 4_000},
            {"file_path": "/w/demo-api/big.txt", "content_lines": 4_000},
        ),
        (
            {
                "file_path": "/w/demo-hub/brain/_inbox/note.md",
                "content": f"intro {BODY}\n## Run tests with -x  ##\n{BODY}",
            },
            {
                "file_path": "/w/demo-hub/brain/_inbox/note.md",
                "content_lines": 3,
                "content_heading": "Run tests with -x",
            },
        ),
        (
            {"file_path": "/w/a.py", "old_string": BODY, "new_string": f"{BODY}\n{BODY}"},
            {"file_path": "/w/a.py", "old_string_lines": 1, "new_string_lines": 2},
        ),
        (
            {
                "file_path": "/w/a.py",
                "edits": [{"old_string": f"{BODY}\n", "new_string": "", "replace_all": True}],
            },
            {
                "file_path": "/w/a.py",
                "edits": [{"old_string_lines": 1, "new_string_lines": 0, "replace_all": True}],
            },
        ),
    ],
    ids=["write", "write-over-64-kib", "inbox-heading", "edit", "multi-edit"],
)
def test_sends_line_counts_when_tool_input_carries_file_content(
    tool_input: dict[str, Any],
    sent: dict[str, Any],
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    tool = (
        "MultiEdit" if "edits" in tool_input else "Edit" if "old_string" in tool_input else "Write"
    )
    data = hook_input("PreToolUse", hub) | {"tool_name": tool, "tool_input": tool_input}

    hook = _sent_hook(
        data,
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        event_server=event_server,
        env=sensor_env,
    )

    assert hook["tool_input"] == sent


def test_sends_output_size_when_tool_responds(
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    response = {"stdout": f"é {BODY}" * 10_000, "stderr": "", "interrupted": False}
    data = hook_input("PostToolUse", hub) | {
        "tool_name": "Write",
        "tool_input": {"file_path": "/w/a.py", "content": BODY},
        "tool_response": response,
    }

    hook = _sent_hook(
        data,
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        event_server=event_server,
        env=sensor_env,
    )

    assert "tool_response" not in hook
    assert hook["tool_response_bytes"] == len(json.dumps(response, separators=(",", ":")).encode())
    assert hook["tool_input"] == {"file_path": "/w/a.py", "content_lines": 1}


# AGH-277 D-reason (AC-277.19): a blocked-word deny is recorded with ``rule: blocked_word``; the
# decision holds no command, and no part of the envelope holds a scanned variable's value.
def test_records_blocked_word_rule_when_guard_denies(
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
) -> None:
    (hub / "hub.json").write_text(json.dumps(builders.an_environments_document()), encoding="utf-8")
    by_command = hook_input("PreToolUse", hub) | {
        "tool_input": {"command": "curl https://prod.example.com/x"}
    }
    by_variable = hook_input("PreToolUse", hub) | {"tool_input": {"command": "git status"}}
    value = "demo-prod-value-7"

    runs = [
        run_hook_file(
            hook_python,
            hub / HOOKS / "guard.py",
            stdin=json.dumps(event).encode(),
            cwd=hub,
            env=sensor_env | extra,
        )
        for event, extra in ((by_command, {}), (by_variable, {"AWS_PROFILE": value}))
    ]

    assert [(run.returncode, run.stderr) for run in runs] == [(0, b""), (0, b"")]
    assert [json.loads(run.stdout)["hookSpecificOutput"]["permissionDecision"] for run in runs] == [
        "deny",
        "deny",
    ]
    bodies = event_server.bodies()
    assert [body["decision"] for body in bodies] == [
        {"by": "guard", "kind": "deny", "rule": "blocked_word"}
    ] * 2
    assert value not in json.dumps(bodies)
    for body in bodies:
        HookEnvelope.model_validate(body)
