"""The one PreToolUse hook, ``pre_tool_use.py`` (AGH-621): the guard's verdict, then the sensor's
posts, in one process.

Each event runs through the rendered hook as Claude Code runs it: the file on ``hook_python`` with
the event on stdin, in an environment built from scratch, in a rendered demo hub whose
``hub.json`` sets blocked words. It must print what Claude Code got on PreToolUse before the
merge, in the same hub: ``guard.py``'s output for a call the old matcher sent to the guard (each
case also states that output's decision, so a broken hub cannot pass), nothing for another call.
Its posts must be the ones ``guard.py`` then ``event_sensor.py`` make for the same event.
"""

import json
import os
import select
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import IO, Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing import builders

HOOKS = "plugin/hub-workflow/hooks"
HOOK = f"{HOOKS}/pre_tool_use.py"
GUARD = f"{HOOKS}/guard.py"
SENSOR = f"{HOOKS}/event_sensor.py"
EXTENSION = "plugin/demo/hooks/project_guard.py"
SESSION = "5e55a0b1-0000-4000-8000-000000000001"
URL_VARIABLE = "AGENT_HUB_WEB_URL"
# The sensor's one deadline for both envelopes, in seconds, and what the hook may take beyond it
# to exit on a loaded machine.
SEND_DEADLINE = 0.5
EXIT_MARGIN = 0.3
# How long the hook may take to start and reach the listener, and how long the test waits for a
# verdict already printed to show on the pipe (well under the send deadline).
START_WAIT = 10.0
VERDICT_WAIT = 0.2
ATTRIBUTION = "git commit -m 'feat: x\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>'"

type Completed = subprocess.CompletedProcess[bytes]
type RunHook = Callable[..., Completed]
type RunDriver = Callable[..., Completed]
type Stdin = Callable[[Path], bytes]


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """``ws/demo-hub`` with the builder's blocked words in its ``hub.json``, beside ``demo-api``."""
    hub = rendered_hub(demo_config).resolve()
    document = builders.an_environments_document()
    assert document["guard"]["blocked_words"]
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    (hub.parent / "demo-api" / "src").mkdir(parents=True)
    return hub


def home_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": str(home)}


def tool_call(hub: Path, tool: str, **tool_input: Any) -> bytes:
    """A PreToolUse event of ``tool`` in a session whose cwd is ``hub``."""
    event = {
        "session_id": SESSION,
        "transcript_path": f"/home/u/.claude/projects/x/{SESSION}.jsonl",
        "cwd": str(hub),
        "hook_event_name": "PreToolUse",
        "permission_mode": "default",
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_01",
    }
    return json.dumps(event).encode()


def bash(command: str) -> Stdin:
    return lambda hub: tool_call(hub, "Bash", command=command)


def raw(stdin: bytes) -> Stdin:
    return lambda hub: stdin


def read_file(rel: str) -> Stdin:
    """A Read of ``rel``, from the folder holding the hub."""
    return lambda hub: tool_call(hub, "Read", file_path=str(hub.parent / rel))


def edit_file(rel: str) -> Stdin:
    """An Edit of ``rel``, from the folder holding the hub."""
    return lambda hub: tool_call(
        hub, "Edit", file_path=str(hub.parent / rel), old_string="a", new_string="b"
    )


def decision_of(output: bytes) -> str | None:
    """The decision a hook's output holds; ``None`` when it printed nothing."""
    if not output.strip():
        return None
    decision: str = json.loads(output)["hookSpecificOutput"]["permissionDecision"]
    return decision


def partial_install_ask(cause: str) -> bytes:
    """What guard.py prints when it cannot load its own modules, naming the exception's type."""
    output = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": f"[hub guard] could not check this call ({cause}); confirm",
    }
    return json.dumps({"hookSpecificOutput": output}).encode() + b"\n"


def unchanged(hub: Path) -> None:
    """The rendered hub as it is."""


def without(name: str) -> Callable[[Path], None]:
    """Remove the hook file ``name``, as a partial install leaves the hooks folder."""

    def remove(hub: Path) -> None:
        (hub / HOOKS / name).unlink()

    return remove


def broken_extension(hub: Path) -> None:
    """A project guard that raises on every call."""
    source = 'def check(event, cfg):\n    raise RuntimeError("broken")\n'
    (hub / EXTENSION).write_text(source, encoding="utf-8")


def guard_syntax_error(hub: Path) -> None:
    (hub / GUARD).write_text("def check(:\n", encoding="utf-8")


@dataclass(frozen=True)
class Case:
    """A PreToolUse stdin, built for the hub, and a change made to the hub before it runs.

    ``decision``: what guard.py prints on it in that hub (``None``: nothing). ``routed=False``:
    the old anchored matcher never started guard.py for this tool, so Claude Code got nothing.
    ``broken_guard``: guard.py itself is gone or broken (the exception the hook must name), so
    there is no guard.py to run.
    """

    stdin: Stdin
    decision: str | None
    setup: Callable[[Path], None] = unchanged
    routed: bool = True
    broken_guard: str | None = None


# AC-4.11's odd stdins (test_hooks_fail_open.py's FIXED_STDINS) and what guard.py decides on each
# while blocked words are set: an event that is not a JSON object asks, whatever its tool (A10).
ODD_STDINS: dict[str, tuple[bytes, str | None]] = {
    "empty": (b"", None),
    "list": (b"[]", "ask"),
    "string": (b'"x"', "ask"),
    "invalid_utf8": (b"\xff", "ask"),
    "object": (b"{}", None),
}
VERDICT_CASES: dict[str, Case] = {
    "bash-ls": Case(bash("ls"), None),
    "read": Case(read_file("demo-hub/README.md"), None),
    "edit": Case(edit_file("demo-hub/README.md"), None),
    "todowrite": Case(
        lambda hub: tool_call(hub, "TodoWrite", todos=[{"content": "x", "status": "pending"}]),
        None,
        routed=False,
    ),
    "force-push": Case(bash("git push --force origin jdoe/dem-1-x"), "deny"),
    "env-read": Case(read_file("demo-api/.env"), "deny"),
    "hub-json-edit": Case(edit_file("demo-hub/hub.json"), "ask"),
    "ai-attribution": Case(bash(ATTRIBUTION), "deny"),
    "terraform": Case(bash("terraform apply"), "deny"),
    "mcp-tool": Case(
        lambda hub: tool_call(hub, "mcp__db__query", host="db.prod.example.com"), "deny"
    ),
    "brain-write": Case(
        lambda hub: tool_call(
            hub, "Write", file_path=str(hub / "brain/decisions/x.md"), content="x"
        ),
        "ask",
    ),
    **{
        f"stdin-{name}": Case(raw(stdin), decision)
        for name, (stdin, decision) in ODD_STDINS.items()
    },
    "broken-project-guard": Case(bash("ls"), "ask", setup=broken_extension),
    "partial-install": Case(bash("ls"), "ask", setup=without("hubhooks.py")),
    "guard-removed": Case(
        bash("ls"), "ask", setup=without("guard.py"), broken_guard="ModuleNotFoundError"
    ),
    "guard-syntax-error": Case(
        bash("ls"), "ask", setup=guard_syntax_error, broken_guard="SyntaxError"
    ),
}


def expected_output(
    case: Case, *, hub: Path, run: Callable[[Path], subprocess.CompletedProcess[bytes]]
) -> tuple[int, bytes]:
    """The exit code and stdout the hook must give for ``case``: guard.py's for a call the old
    matcher sent to it (checked against the case's decision first), nothing for another call; and
    with guard.py gone or broken, the guard's partial-install ask (where ``python3 guard.py`` used
    to exit 2 or 1)."""
    if not case.routed:
        return 0, b""
    if case.broken_guard is not None:
        return 0, partial_install_ask(case.broken_guard)
    reference = run(hub / GUARD)
    assert decision_of(reference.stdout) == case.decision, reference.stdout
    return reference.returncode, reference.stdout


# AC-20, with A10: every case's exit code and stdout.
@pytest.mark.parametrize("case", VERDICT_CASES.values(), ids=VERDICT_CASES.keys())
def test_prints_guard_verdict_when_event_runs(
    case: Case, hub: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    case.setup(hub)
    stdin = case.stdin(hub)
    run = partial(run_hook_file, hook_python, stdin=stdin, cwd=hub, env=home_env(tmp_path))
    expected = expected_output(case, hub=hub, run=run)

    completed = run(hub / HOOK)

    assert (completed.returncode, completed.stdout) == expected


# A step of the guard that fails once the guard has loaded. argv: none. Makes one step raise
# RuntimeError ($BREAK: hubhooks' load_config, or the guard's rule_of; each call is logged to
# $CALLS first), then runs $HOOK_FILE: guard.py as its __main__ block runs it, the hook as __main__.
GUARD_STEP_RAISES = """
import os, runpy, sys
hook = os.environ["HOOK_FILE"]
sys.path.insert(0, os.path.dirname(hook))
import hubhooks


def raising(*args):
    with open(os.environ["CALLS"], "a", encoding="utf-8") as fh:
        fh.write(repr(args) + "\\n")
    raise RuntimeError("broken step")


if os.environ["BREAK"] == "load_config":
    hubhooks.load_config = raising
import guard
if os.environ["BREAK"] == "rule_of":
    guard.rule_of = raising
sys.argv = [hook]
if os.path.basename(hook) == "guard.py":
    guard.run_hook(guard.main, guard.ask_on_error)
runpy.run_path(hook, run_name="__main__")
"""


@pytest.fixture
def run_driver(hub: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path) -> RunDriver:
    """Run a driver (its source) with an event on stdin, for the hook file ``script`` of ``hub``
    ($HOOK_FILE) and with more variables."""

    def run(source: str, script: str, stdin: bytes, **env: str) -> Completed:
        driver = tmp_path / "support" / "driver.py"
        driver.parent.mkdir(exist_ok=True)
        driver.write_text(source, encoding="utf-8")
        variables = home_env(tmp_path) | {"HOOK_FILE": str(hub / script)} | env
        return run_hook_file(hook_python, driver, stdin=stdin, cwd=hub, env=variables)

    return run


# AC-20: the guard loads, then fails while it checks the call; the hook asks naming the error
# (the crash ask has the partial-install ask's bytes), as guard.py's run_hook does.
def test_asks_with_crash_cause_when_guard_raises_while_checking(
    hub: Path, run_driver: RunDriver, tmp_path: Path
) -> None:
    calls = tmp_path / "calls.txt"

    completed = run_driver(
        GUARD_STEP_RAISES, HOOK, bash("ls")(hub), BREAK="load_config", CALLS=str(calls)
    )

    crash_ask = partial_install_ask("RuntimeError")
    assert calls.is_file()
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, crash_ask, b"")


# What a hook may inherit from the process that starts it. argv: none. Replaces this process with
# $HOOK_FILE on this interpreter, after one change ($INHERITS) that survives exec: no stdin (fd 0
# closed), no stderr (fd 2 closed), SIGCHLD ignored, one more open fd, or none.
EXEC_HOOK = """
import os, signal, sys
inherits = os.environ["INHERITS"]
if inherits == "no-stdin":
    os.close(0)
elif inherits == "no-stderr":
    os.close(2)
elif inherits == "sigchld-ignored":
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
elif inherits == "open-fd":
    os.set_inheritable(os.open(os.devnull, os.O_RDONLY), True)
os.execv(sys.executable, [sys.executable, os.environ["HOOK_FILE"]])
"""


# AC-20, AC-38: with no stdin at all (sys.stdin is None), the hook asks naming the error, as
# guard.py does, and never exits with a traceback, which would let the call through unchecked.
def test_asks_with_crash_cause_when_stdin_closed(run_driver: RunDriver) -> None:
    reference = run_driver(EXEC_HOOK, GUARD, b"", INHERITS="no-stdin")
    assert (reference.returncode, reference.stdout) == (0, partial_install_ask("AttributeError"))

    completed = run_driver(EXEC_HOOK, HOOK, b"", INHERITS="no-stdin")

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, reference.stdout, b"")


# AC-23, AC-24: with no stderr at all (sys.stderr is None), the hook still forks the project
# guard: the seeded stub keeps the base verdict, so a call no rule stops goes through with no
# output, as it did when the guard started a new python3 for it.
@pytest.mark.parametrize("script", [GUARD, HOOK], ids=["guard", "pre_tool_use"])
def test_passes_call_when_stderr_closed(script: str, hub: Path, run_driver: RunDriver) -> None:
    assert (hub / EXTENSION).is_file()

    completed = run_driver(EXEC_HOOK, script, bash("ls")(hub), INHERITS="no-stderr")

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, b"", b"")


# AC-20, AC-21: the rule id only labels the decision sent after the verdict; when finding it
# fails, the verdict is printed as it is, and nothing follows it.
@pytest.mark.parametrize("script", [GUARD, HOOK], ids=["guard", "pre_tool_use"])
def test_prints_one_verdict_when_rule_id_raises(
    script: str, hub: Path, *, run_driver: RunDriver, tmp_path: Path
) -> None:
    stdin, calls = bash("git push --force origin jdoe/dem-1-x")(hub), tmp_path / "calls.txt"
    verdict = run_driver(EXEC_HOOK, GUARD, stdin, INHERITS="nothing").stdout
    assert decision_of(verdict) == "deny"

    completed = run_driver(GUARD_STEP_RAISES, script, stdin, BREAK="rule_of", CALLS=str(calls))

    assert len(calls.read_text(encoding="utf-8").splitlines()) == 1
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, verdict, b"")


# AC-23, AC-24: with SIGCHLD ignored, the kernel would reap the forked runner before the hook
# reads its status; the project guard's verdict still comes through.
def test_gives_project_guard_verdict_when_sigchld_ignored(hub: Path, run_driver: RunDriver) -> None:
    source = 'def check(event, cfg):\n    return ("ask", "project says ask")\n'
    (hub / EXTENSION).write_text(source, encoding="utf-8")
    stdin = bash("ls")(hub)
    verdict = run_driver(EXEC_HOOK, GUARD, stdin, INHERITS="nothing").stdout
    reason = json.loads(verdict)["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason == "[hub guard] project guard: project says ask"

    completed = run_driver(EXEC_HOOK, HOOK, stdin, INHERITS="sigchld-ignored")

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, verdict, b"")


# AC-24 (A6): the forked project guard holds fds 0 to 2 only, as a new python3 did under Popen's
# close_fds: none of the hook's own files and pipe, nor an fd the hook inherited.
FD_RECORDER = """\
import json, os


def check(event, cfg):
    held = []
    for fd in range(3, 256):
        try:
            os.fstat(fd)
        except OSError:
            continue
        held.append(fd)
    with open({record!r}, "w", encoding="utf-8") as fh:
        json.dump(held, fh)
    return None
"""


def test_closes_hook_fds_when_project_guard_forked(
    hub: Path, run_driver: RunDriver, tmp_path: Path
) -> None:
    record = tmp_path / "fds.json"
    (hub / EXTENSION).write_text(FD_RECORDER.format(record=str(record)), encoding="utf-8")

    completed = run_driver(EXEC_HOOK, HOOK, bash("ls")(hub), INHERITS="open-fd")

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, b"", b"")
    assert json.loads(record.read_text(encoding="utf-8")) == []


# AC-21: (the call, how many POSTs guard.py and event_sensor.py make for it together).
ENVELOPE_CALLS: dict[str, tuple[Stdin, int]] = {
    "allowed": (bash("ls"), 1),
    "denied": (bash("git push origin main"), 2),
    "asked": (edit_file("demo-hub/hub.json"), 2),
}


def sent(received: Any) -> tuple[str, str | None, Any]:
    """A POST as two are compared: its path, its Content-Type and its body without sent_at."""
    headers = {name.lower(): value for name, value in received.headers.items()}
    body = json.loads(received.body)
    body.pop("sent_at")
    return received.path, headers.get("content-type"), body


@pytest.mark.parametrize(("call", "posts"), ENVELOPE_CALLS.values(), ids=ENVELOPE_CALLS.keys())
def test_sends_same_envelopes_as_guard_and_sensor_when_server_records(
    call: Stdin,
    posts: int,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    event_server: Any,
    sensor_env: dict[str, str],
    tmp_path: Path,
) -> None:
    env = sensor_env | home_env(tmp_path)
    run = partial(run_hook_file, hook_python, stdin=call(hub), cwd=hub, env=env)
    assert [run(hub / script).returncode for script in (GUARD, SENSOR)] == [0, 0]
    expected = [sent(received) for received in event_server.received]
    assert len(expected) == posts
    event_server.received.clear()

    completed = run(hub / HOOK)

    assert (completed.returncode, completed.stderr) == (0, b"")
    assert [sent(received) for received in event_server.received] == expected


@dataclass
class Listener:
    """A loopback listener that accepts connections and never answers; ``accepted_at`` holds the
    time of each accept, ``accepted`` is set at the first."""

    url: str
    accepted: threading.Event = field(default_factory=threading.Event)
    accepted_at: list[float] = field(default_factory=list)


@pytest.fixture
def hanging_server() -> Iterator[Listener]:
    """A loopback listener in a thread: it accepts each connection, never reads or answers, and
    holds it open until the test ends."""
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.05)
    listener = Listener(url=f"http://127.0.0.1:{server.getsockname()[1]}")
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            listener.accepted_at.append(time.monotonic())
            held.append(connection)
            listener.accepted.set()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield listener
    finally:
        stop.set()
        thread.join(timeout=5)
        for connection in held:
            connection.close()
        server.close()


def first_line(stream: IO[bytes], *, wait: float) -> bytes:
    """What the pipe behind ``stream`` holds, up to and with its first newline, waiting at most
    ``wait`` seconds for it; nothing has been read from ``stream`` before."""
    fd = stream.fileno()
    deadline = time.monotonic() + wait
    data = b""
    while b"\n" not in data:
        ready, _, _ = select.select([fd], [], [], max(deadline - time.monotonic(), 0))
        chunk = os.read(fd, 65_536) if ready else b""
        if not chunk:
            break
        data += chunk
    return data


def closed_now(stream: IO[bytes]) -> bool:
    """Whether the pipe behind ``stream`` is at its end now, without waiting: no writer holds it
    any more and nothing is left on it."""
    fd = stream.fileno()
    ready, _, _ = select.select([fd], [], [], 0)
    return bool(ready) and os.read(fd, 65_536) == b""


# AC-22: the verdict is on stdout before the sensor sends, and one deadline bounds both envelopes
# (a denied call sends two) when hub web accepts and never answers. The verdict is whole by then:
# the hook closes its stdout before it connects, so even an allowed call's empty output is final.
@pytest.mark.serial
@pytest.mark.parametrize(
    ("command", "decision"),
    [("ls", None), ("git push origin main", "deny")],
    ids=["allowed", "denied"],
)
def test_prints_verdict_before_send_when_server_hangs(
    command: str,
    decision: str | None,
    hub: Path,
    *,
    hanging_server: Listener,
    hook_python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
) -> None:
    stdin = bash(command)(hub)
    verdict = run_hook_file(
        hook_python, hub / GUARD, stdin=stdin, cwd=hub, env=home_env(tmp_path)
    ).stdout
    assert decision_of(verdict) == decision
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        URL_VARIABLE: hanging_server.url,
        **home_env(tmp_path),
    }

    with subprocess.Popen(  # noqa: S603 - an interpreter from hook_python, a rendered file
        [hook_python, str(hub / HOOK)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=hub,
        env=env,
    ) as process:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(stdin)
        process.stdin.close()
        connected = hanging_server.accepted.wait(START_WAIT)
        printed = first_line(process.stdout, wait=VERDICT_WAIT) if connected else b""
        closed = closed_now(process.stdout) if connected else False
        returncode = process.wait(timeout=START_WAIT)
        exited_at = time.monotonic()
        rest, stderr = process.stdout.read(), process.stderr.read()

    assert connected, f"the hook never connected; exit {returncode}: {stderr[-300:]!r}"
    assert printed == verdict
    assert closed, "stdout was still open while the listener held the connection"
    assert (returncode, rest) == (0, b"")
    assert exited_at - hanging_server.accepted_at[0] < SEND_DEADLINE + EXIT_MARGIN


@pytest.mark.parametrize(
    ("command", "decision"),
    [("ls", None), ("git push origin main", "deny")],
    ids=["allowed", "denied"],
)
def test_exits_zero_when_server_closed(
    command: str,
    decision: str | None,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    server_down_env: dict[str, str],
    tmp_path: Path,
) -> None:
    env = server_down_env | home_env(tmp_path)
    run = partial(run_hook_file, hook_python, stdin=bash(command)(hub), cwd=hub, env=env)
    verdict = run(hub / GUARD).stdout
    assert decision_of(verdict) == decision

    completed = run(hub / HOOK)

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, verdict, b"")


# AC-22 (Q16): the sensor part fails anywhere, even with a SystemExit, or after writing to
# stdout: the verdict stands alone.
SENSOR_FAILURES = {
    "runtime-error": 'raise RuntimeError("sensor broken")\n',
    "system-exit": "raise SystemExit(3)\n",
    "after-writing": 'import os\nprint("printed")\nos.write(1, b"written\\n")\nraise SystemExit\n',
}


@pytest.mark.parametrize("failure", SENSOR_FAILURES.values(), ids=SENSOR_FAILURES.keys())
def test_prints_only_verdict_when_sensor_part_raises(
    failure: str, hub: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    stdin = bash("git push origin main")(hub)
    run = partial(run_hook_file, hook_python, stdin=stdin, cwd=hub, env=home_env(tmp_path))
    verdict = run(hub / GUARD).stdout
    assert decision_of(verdict) == "deny"
    (hub / SENSOR).write_text(failure, encoding="utf-8")

    completed = run(hub / HOOK)

    assert (completed.returncode, completed.stdout) == (0, verdict)


# AC-22 (Q16): the sensor loads, then one of its own functions fails while the hook sends: the
# verdict still stands alone. Appended to the real event_sensor.py, it replaces the function
# ``name``, which logs its call to ``calls``, then fails as the one line ``failure`` does.
REPLACED_SENSOR_FUNCTION = """

def {name}(*args, **kwargs):
    with open({calls!r}, "a", encoding="utf-8") as fh:
        fh.write({name!r} + "\\n")
    {failure}
"""
SENSOR_FUNCTION_FAILURES = {
    "build-envelope-raises": ("build_envelope", 'raise RuntimeError("sensor broken")'),
    "post-envelope-exits-after-writing": (
        "post_envelope",
        'print("printed"); os.write(1, b"written\\n"); raise SystemExit(3)',
    ),
}


@pytest.mark.parametrize(
    ("name", "failure"), SENSOR_FUNCTION_FAILURES.values(), ids=SENSOR_FUNCTION_FAILURES.keys()
)
def test_prints_only_verdict_when_sensor_function_raises(
    name: str,
    failure: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
) -> None:
    stdin, calls = bash("git push origin main")(hub), tmp_path / "calls.txt"
    run = partial(run_hook_file, hook_python, stdin=stdin, cwd=hub, env=home_env(tmp_path))
    verdict = run(hub / GUARD).stdout
    assert decision_of(verdict) == "deny"
    sensor = (hub / SENSOR).read_text(encoding="utf-8")
    replaced = REPLACED_SENSOR_FUNCTION.format(name=name, calls=str(calls), failure=failure)
    (hub / SENSOR).write_text(sensor + replaced, encoding="utf-8")

    completed = run(hub / HOOK)

    assert calls.read_text(encoding="utf-8").splitlines() == [name]
    assert (completed.returncode, completed.stdout) == (0, verdict)


# AC-25: an allowed call loads neither http.client, email.parser nor ssl. argv: a hook file and a
# file holding one event. Runs the hook as __main__ in this process with the event on stdin, then
# lists which of those modules are loaded, before the run and after it.
RUN_AND_LIST_MODULES = """
import contextlib, io, json, runpy
WATCHED = ("http.client", "email.parser", "ssl")
hook, event = sys.argv[1], sys.argv[2]
before = [name for name in WATCHED if name in sys.modules]
with open(event, "rb") as fh:
    sys.stdin = io.TextIOWrapper(io.BytesIO(fh.read()), encoding="utf-8")
out, code = io.StringIO(), None
with contextlib.redirect_stdout(out):
    try:
        runpy.run_path(hook, run_name="__main__")
    except SystemExit as stop:
        code = stop.code
after = [name for name in WATCHED if name in sys.modules]
print(json.dumps({"before": before, "code": code, "stdout": out.getvalue(), "after": after}))
"""


def test_loads_no_http_client_when_allowed_call_runs(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path
) -> None:
    event = tmp_path / "event.json"
    event.write_bytes(bash("ls")(hub))

    # the child's environment points the sensor at a loopback port nothing listens on
    found = run_python(
        hook_python,
        RUN_AND_LIST_MODULES,
        path=hub / HOOKS,
        args=[str(hub / HOOK), str(event)],
        cwd=hub,
        env=home_env(tmp_path),
    )

    assert found["before"] == []
    assert found["code"] in (0, None)
    assert found["stdout"] == ""
    assert found["after"] == []
