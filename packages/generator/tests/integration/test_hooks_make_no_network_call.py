"""Every rendered hook makes no network call, checked with the outbound probe (AC-28, AC-29).

Each ``HOOK_EVENTS`` row runs as Claude Code runs it: the hook file on ``hook_python`` with a
valid input of its event on stdin (``a_hook_input``), in the probe's environment
(``agent_hub.core.testing.outbound_probe``): stand-ins for gh, uv, uvx, claude, curl, wget and
ssh first on ``PATH``, every proxy variable at a recording proxy, and a sitecustomize that records
and refuses each socket call that would leave the machine. Two more cases take the paths that
reach for a server: the guard denying a push to main (it then sends its decision), and the sensor
given a control plane on another host. The workspace is synthetic: the rendered demo hub at
``ws/demo-hub`` and its repo ``ws/demo-api``, both committed git checkouts, a synthetic
transcript, and the hooks' ``TMPDIR`` under the test's folder.

A case passes when the hook gives its normal exit code and output, the probe's marker shows it
loaded in the process the test started, and nothing was recorded. A case listed in
``KNOWN_CALLS`` is a strict xfail naming the ticket that removes its call; none is listed. The one
call allowed by design is SessionStart's detached refresh (ADR 0055): with no brief cache, its
``uvx … hub brief --write-cache``, for the ``session_start.py --refresh`` process only.
"""

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.hub_files.release_commit import ReleaseCommit
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hook_inputs import a_hook_input
from agent_hub.core.testing.outbound_probe import (
    LOADED_LOG,
    outbound_calls,
    outbound_env,
    recording_proxy,
    write_stubs,
)
from agent_hub.generator.built_json import HOOK_EVENTS
from agent_hub.generator.render_hub import render_hub

HOOKS = "plugin/hub-workflow/hooks"
RESEARCHER = "plugin/hub-workflow/agents/researcher.md"
# The two cases beside the rows: the guard denying a push to main, after which it sends its
# decision, and the sensor given a control plane on a TEST-NET-1 host (RFC 5737), which it must
# not try.
GUARD_DENY = "guard-PreToolUse-deny"
REMOTE_URL = "event_sensor-remote-url"
REMOTE_CONTROL_PLANE = "http://192.0.2.1:7420"
# Each case: the hook file it runs and the event of its input.
CASES: dict[str, tuple[str, str]] = {
    **{f"{hook.file[:-3]}-{hook.event}": (hook.file, hook.event) for hook in HOOK_EVENTS},
    GUARD_DENY: ("guard.py", "PreToolUse"),
    REMOTE_URL: ("event_sensor.py", "PostToolUse"),
}
# A case that still calls out, mapped to the ticket that removes the call: the case becomes a
# strict xfail, so the entry has to go once the call does. Empty: no hook calls out.
KNOWN_CALLS: dict[str, str] = {}

# The brief cache (ADR 0055), as test_session_start_hook.py writes it.
CACHE_DIR = ".hub-cache"
CACHE = f"{CACHE_DIR}/brief.json"
REFRESH_LOCK = f"{CACHE_DIR}/refresh.lock"
CACHED_BRIEF = "# Brief\n\n## Now\nShip the cache.\n"
# Under the 5 min refresh floor, so no refresh starts; shown as "3 min", rounded or cut.
FRESH_AGE = 200
# How long the cold case waits for its refresh to end.
REFRESH_WAIT = 10.0

# What a case prints on a normal run, the guard's reason left out (test_guard_hook.py owns its
# words): SessionStart's context from a warm cache, headed with its age, and the guard's deny.
# Every other case prints nothing: the sensor never prints, the guard prints nothing for a call it
# lets through, and the other hooks' normal runs are silent (their goldens).
PRINTS: dict[str, dict[str, Any]] = {
    "session_start-SessionStart": {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"(brief from 3 min ago)\n\n{CACHED_BRIEF.strip()}",
        }
    },
    GUARD_DENY: {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
    },
}

# ADR 0054: with the release commit in hub.lock, the refresh's brief is one uvx call from the
# commit, with no resolve step. The source is written out, as the ADR spells it.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
COMMIT_SOURCE = (
    "git+https://github.com/jroquette/agent-hub@0123456789abcdef0123456789abcdef01234567"
    "#subdirectory=packages/agent-hub"
)
# The first line SessionStart shows with no brief cache, while its refresh runs.
COLD_HEAD = "# Brief (fallback: hub brief no brief cache)"

# The workspace's git: the test's own identity, no background repack writing into .git while a
# hook reads it.
GIT_SETTINGS = (
    "user.name=Test User",
    "user.email=test@example.com",
    "init.defaultBranch=main",
    "commit.gpgsign=false",
    "gc.auto=0",
    "maintenance.auto=false",
)

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]

pytestmark = pytest.mark.usefixtures("no_process_left")


@dataclass(frozen=True)
class Workspace:
    """The rendered demo ``hub`` and its ``repo`` ``demo-api``, both committed git checkouts, the
    session's synthetic ``transcript``, a ``home`` for runs outside the probe, and the hooks'
    ``temp`` (``TMPDIR``)."""

    hub: Path
    repo: Path
    transcript: Path
    home: Path
    temp: Path


def commit_all(checkout: Path, *, home: Path) -> None:
    """Make ``checkout`` a git repository whose one commit holds all it has."""
    git = shutil.which("git")
    assert git is not None, "git is needed for the workspace's checkouts"
    settings = [part for setting in GIT_SETTINGS for part in ("-c", setting)]
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "test: workspace")):
        subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
            [git, *settings, *args], cwd=checkout, env=env, check=True, capture_output=True
        )


def write_transcript(path: Path) -> Path:
    """The session's synthetic transcript: a request and its answer, an hour ago."""
    first = datetime.now(UTC) - timedelta(hours=1)
    stamp = first.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    request = {"role": "user", "content": "/feature add the export button"}
    answer = {"role": "assistant", "content": [{"type": "text", "text": "Reading the spec."}]}
    lines = [
        {"type": "user", "timestamp": stamp, "message": request},
        {"type": "assistant", "timestamp": stamp, "message": answer},
    ]
    path.write_text("".join(f"{json.dumps(line)}\n" for line in lines), encoding="utf-8")
    return path


@pytest.fixture
def workspace(
    rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig, tmp_path: Path
) -> Workspace:
    """``ws/demo-hub`` (the builder's ``hub.json``) and ``ws/demo-api``, committed."""
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    repo = hub.parent / "demo-api"
    repo.mkdir()
    (repo / "app.py").write_text("A = 1\n", encoding="utf-8")
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    for checkout in (hub, repo):
        commit_all(checkout, home=home)
    transcript = write_transcript(tmp_path / "session-1.jsonl")
    return Workspace(hub=hub, repo=repo, transcript=transcript, home=home, temp=temp)


@contextlib.contextmanager
def probed(folder: Path, variables: Mapping[str, str]) -> Iterator[dict[str, str]]:
    """The probe's environment for a hook, plus ``variables``, with its recorder serving until
    the block ends."""
    folder.mkdir()
    write_stubs(folder)
    with recording_proxy(folder) as port:
        yield outbound_env(folder, port, os.environ.get("PATH", os.defpath)) | dict(variables)


def hook_input(event: str, workspace: Workspace, **fields: Any) -> bytes:
    """A valid ``event`` input at the hub, with the synthetic transcript, then ``fields``."""
    at_hub = {"cwd": str(workspace.hub), "transcript_path": str(workspace.transcript)}
    return json.dumps(a_hook_input(event, **(at_hub | fields))).encode()


def case_fields(case: str, workspace: Workspace) -> dict[str, Any]:
    """What a case's input sets beside ``a_hook_input``'s: post_edit's Edit of a file in
    ``demo-api``, the read-only researcher for the gate, and the push to main the guard denies."""
    file, _ = CASES[case]
    if file == "post_edit.py":
        edited = str(workspace.repo / "app.py")
        edit = {"file_path": edited, "old_string": "A = 1", "new_string": "A = 2"}
        return {"tool_name": "Edit", "tool_input": edit, "tool_response": {"filePath": edited}}
    if file == "readonly_gate.py":
        return {"agent_type": "researcher"}
    if case == GUARD_DENY:
        return {"tool_input": {"command": "git push origin main", "description": "Push"}}
    return {}


def case_env(case: str, workspace: Workspace) -> dict[str, str]:
    """What a case adds to the probe's environment: the hooks' ``TMPDIR``, and for
    ``REMOTE_URL`` a control plane on another host."""
    variables = {"TMPDIR": str(workspace.temp)}
    if case == REMOTE_URL:
        variables["AGENT_HUB_WEB_URL"] = REMOTE_CONTROL_PLANE
    return variables


def printed(stdout: bytes) -> object:
    """What a hook printed, as ``PRINTS`` holds it: None for nothing, its JSON object without the
    guard's reason, or the text itself when it is not one."""
    text = stdout.decode("utf-8", "replace").strip()
    if not text.startswith("{"):
        return text or None
    output: dict[str, Any] = json.loads(text)
    output.get("hookSpecificOutput", {}).pop("permissionDecisionReason", None)
    return output


def started_markers(folder: Path, hook: Path) -> list[dict[str, Any]]:
    """The probe's markers of the hook run this test started: a child of this process whose argv
    is the hook file."""
    log = folder / LOADED_LOG
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    markers = [json.loads(line) for line in lines]
    started = (os.getpid(), [str(hook)])
    return [marker for marker in markers if (marker["ppid"], marker["argv"]) == started]


def known_call(case: str) -> list[pytest.MarkDecorator]:
    """A strict xfail for a case in ``KNOWN_CALLS``, naming the ticket that removes its call."""
    if case not in KNOWN_CALLS:
        return []
    return [pytest.mark.xfail(strict=True, reason=f"calls out until {KNOWN_CALLS[case]}")]


def no_setup(workspace: Workspace, run: RunHook) -> None:
    """The workspace as it is."""


def warm_cache(workspace: Workspace, run: RunHook) -> None:
    """A brief cache under the refresh floor: SessionStart shows it and starts no refresh."""
    write_cache(workspace.hub, age=FRESH_AGE)


def declared_researcher(workspace: Workspace, run: RunHook) -> None:
    """The base researcher, the read-only agent the gate acts for, as rendered."""
    definition = (workspace.hub / RESEARCHER).read_text(encoding="utf-8")
    assert "mutates_checkout: false" in definition


def started_researcher(workspace: Workspace, run: RunHook) -> None:
    """The researcher's SubagentStart, run first as Claude Code does (outside the probe): silent,
    the gate's start state saved in ``TMPDIR``."""
    declared_researcher(workspace, run)
    start = a_hook_input("SubagentStart", agent_type="researcher")
    started = run(
        workspace.hub / HOOKS / "readonly_gate.py",
        stdin=hook_input("SubagentStart", workspace, agent_type="researcher"),
        env={"HOME": str(workspace.home), "TMPDIR": str(workspace.temp)},
    )
    assert (started.returncode, started.stdout, started.stderr) == (0, b"", b"")
    state = f"hub-readonly-{start['session_id']}-{start['agent_id']}.json"
    assert sorted(path.name for path in workspace.temp.iterdir()) == [state]


# Each case's state before its run; a case not named runs in the workspace as it is.
SETUPS: dict[str, Callable[[Workspace, RunHook], None]] = {
    "session_start-SessionStart": warm_cache,
    "readonly_gate-SubagentStart": declared_researcher,
    "readonly_gate-SubagentStop": started_researcher,
}


@pytest.mark.parametrize(
    "case", [pytest.param(case, id=case, marks=known_call(case)) for case in CASES]
)
def test_makes_no_network_call_when_hook_runs(
    case: str, *, workspace: Workspace, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    file, event = CASES[case]
    hook = workspace.hub / HOOKS / file
    run = partial(run_hook_file, hook_python, cwd=workspace.hub)
    SETUPS.get(case, no_setup)(workspace, run)
    folder = tmp_path / "probe"

    with probed(folder, case_env(case, workspace)) as env:
        completed = run(
            hook, stdin=hook_input(event, workspace, **case_fields(case, workspace)), env=env
        )
    calls = outbound_calls(folder)

    assert (completed.returncode, completed.stderr) == (0, b""), case
    assert printed(completed.stdout) == PRINTS.get(case), case
    assert len(started_markers(folder, hook)) == 1, f"{case}: no probe marker of {hook}"
    assert calls == [], f"{case} called out:\n" + "\n".join(calls)


def test_allows_only_refresh_uvx_when_session_starts_cold(
    workspace: Workspace, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hub = workspace.hub
    hook = hub / HOOKS / "session_start.py"
    write_lock(hub, commit=COMMIT)
    assert not (hub / CACHE_DIR).exists()
    folder = tmp_path / "probe"

    with probed(folder, {"TMPDIR": str(workspace.temp)}) as env:
        completed = run_hook_file(
            hook_python, hook, stdin=hook_input("SessionStart", workspace), cwd=hub, env=env
        )
        # The recorder logs only what it accepted before the block ends: the refresh ends here.
        ended = refresh_ended(hub)
    calls = outbound_calls(folder)

    assert (completed.returncode, completed.stderr) == (0, b"")
    context = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
    assert context.splitlines()[0] == COLD_HEAD
    assert ended, "the detached refresh did not end"
    assert len(started_markers(folder, hook)) == 1, f"no probe marker of {hook}"
    refresh = f"{hook} --refresh {hub}"
    assert calls == [f"uvx --from {COMMIT_SOURCE} hub brief --write-cache by {refresh}"], (
        "session_start cold start called out:\n" + "\n".join(calls)
    )


def write_lock(hub: Path, *, commit: str) -> None:
    """The lock ``hub sync`` writes for the demo, with the release ``commit`` read from the
    default repository (test_session_start_hook.py's, at the demo's own version)."""
    document = a_hub_document()
    config = HubConfig.model_validate(document)
    release = ReleaseCommit(commit=commit, repository=DEFAULT_REPOSITORY)
    content = lock_bytes(
        build_hub_lock(rendered=render_hub(config), config=config, release=release)
    )
    (hub / "hub.lock").write_bytes(content)
    lock = json.loads(content)
    version = document["platform"]["version"]
    assert (lock["platform_version"], lock.get("platform_commit")) == (version, commit)


# The session-start helpers below are copies of test_session_start_hook.py's, which keeps its own.


def write_cache(hub: Path, *, age: float, brief: str = CACHED_BRIEF) -> None:
    """The cache ``hub brief --write-cache`` leaves, made ``age`` seconds ago."""
    folder = hub / CACHE_DIR
    folder.mkdir(exist_ok=True)
    (folder / ".gitignore").write_text("*\n", encoding="utf-8")
    document = {"made_at": time.time() - age, "brief": brief}
    (hub / CACHE).write_text(json.dumps(document), encoding="utf-8")


def wait_until(condition: Callable[[], object], deadline: float = REFRESH_WAIT) -> bool:
    """True once ``condition()`` is truthy, polled until ``deadline`` seconds have passed."""
    end = time.monotonic() + deadline
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


def refresh_ended(hub: Path, deadline: float = REFRESH_WAIT) -> bool:
    """True once the refresh lock exists and is free: the refresh that held it has ended."""
    end = time.monotonic() + deadline
    lock = hub / REFRESH_LOCK
    if not wait_until(lock.exists, deadline):
        return False
    return is_lock_free_within(lock, max(end - time.monotonic(), 0.0))


def is_lock_free_within(lock_path: Path, deadline: float) -> bool:
    """True once an exclusive lock on ``lock_path`` can be taken ("r+": it must exist)."""
    end = time.monotonic() + deadline
    with lock_path.open("r+") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.01)
            else:
                return True
