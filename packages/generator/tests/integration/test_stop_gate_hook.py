"""The hub's stop-gate tests, run on the rendered ``stop_gate.py`` (AC-4.16, E2).

Each test is the counterpart of one test of the hub's
``plugin/hub-workflow/tests/test_stop_gate.py`` and asserts the same values. The workspace is the
hub test's: a rendered demo hub at ``ws/demo-hub`` whose ``hub.json`` each run writes, and the git
repos ``app/`` and ``web/`` beside it. The hook runs as Claude Code runs it, a file on
``hook_python`` with the event on stdin, in an environment from scratch (no ``HUB_CONFIG``, no
``CLAUDE_PROJECT_DIR``; ``TMPDIR`` under ``tmp_path``, so its block counter stays there). The
config comes from the hub that holds the hook (Q-4), not from a walk up from the event's cwd.
"""

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pytest

from agent_hub.core.hub_config.model import MAX_CHECK_FAST_TIMEOUT, HubConfig

HOOK = "plugin/hub-workflow/hooks/stop_gate.py"
TIMEOUT = 60
# The late marker's child touches it LATE_DELAY s after the check starts, and the check starts
# before the hook returns: waiting LATE_MARGIN s more after the return sees any marker a surviving
# child writes.
LATE_DELAY = 2
LATE_MARGIN = 0.5
LATE_AFTER = LATE_DELAY + LATE_MARGIN
# A cut run's marker comes after the latest cut a timeout case makes (the 3 s budget), so only a
# child that outlives the kill can write it.
CUT_DELAY = 4


class RunHook(Protocol):
    """The ``run_hook`` fixture: write ``hub.json``, run the hook, return its JSON output."""

    def __call__(
        self,
        repos: Sequence[Mapping[str, object]],
        cwd: Path,
        *,
        transcript: Path | int | None = None,
        constant: tuple[str, object] | None = None,
        session: str | None = None,
        pass_fds: Sequence[int] = (),
    ) -> dict[str, Any]: ...


@pytest.fixture
def workspace(
    rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig, tmp_path: Path
) -> Path:
    """``ws``: the rendered hub ``demo-hub`` and the git repos ``app`` and ``web``."""
    hub = rendered_hub(demo_config).resolve()
    assert hub.name == "demo-hub"
    git = shutil.which("git")
    assert git is not None
    for repo in ("app", "web"):
        (hub.parent / repo).mkdir()
        subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
            [git, "init", "-q"],
            cwd=hub.parent / repo,
            check=True,
            capture_output=True,
            env=scratch_env(tmp_path),
        )
    return hub.parent


def scratch_env(tmp_path: Path) -> dict[str, str]:
    """``PATH`` from this process; ``HOME`` and ``TMPDIR`` under ``tmp_path``; nothing else."""
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "TMPDIR": str(temp)}


@pytest.fixture
def run_hook(
    workspace: Path,
    hook_python: str,
    *,
    tmp_path: Path,
    run_hook_with_constant: Callable[..., subprocess.CompletedProcess[bytes]],
) -> RunHook:
    """Write ``hub.json`` with ``repos``, run the hook for an event at ``cwd``, return its JSON.

    ``transcript`` becomes the event's ``transcript_path`` (an ``int`` as written: a JSON number),
    ``session`` its ``session_id``, ``constant`` replaces one module constant of the hook, and
    ``pass_fds`` stay open in the hook (with no ``constant``). The hook must exit 0 with an empty
    stderr: its fail-open backstop would otherwise hide an inner error.
    """
    hub = workspace / "demo-hub"
    # The hook's own cwd is outside every hub: only the event's cwd may lead it to one.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def run(
        repos: Sequence[Mapping[str, object]],
        cwd: Path,
        *,
        transcript: Path | int | None = None,
        constant: tuple[str, object] | None = None,
        session: str | None = None,
        pass_fds: Sequence[int] = (),
    ) -> dict[str, Any]:
        assert constant is None or not pass_fds
        document = {"project": {"name": "demo"}, "repos": list(repos)}
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        event: dict[str, object] = {
            "cwd": str(cwd),
            "session_id": session or f"test-{os.getpid()}-{tmp_path.name}",
        }
        if transcript is not None:
            event["transcript_path"] = (
                transcript if isinstance(transcript, int) else str(transcript)
            )
        if constant is None:
            completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, the rendered hook
                [hook_python, str(hub / HOOK)],
                input=json.dumps(event).encode("utf-8"),
                capture_output=True,
                check=False,
                cwd=elsewhere,
                env=scratch_env(tmp_path),
                timeout=TIMEOUT,
                pass_fds=tuple(pass_fds),
            )
        else:
            completed = run_hook_with_constant(
                hook_python,
                hub / HOOK,
                constant=constant,
                stdin=json.dumps(event).encode("utf-8"),
                cwd=elsewhere,
                env=scratch_env(tmp_path),
            )
        stderr = completed.stderr.decode("utf-8", "replace")
        assert completed.returncode == 0, stderr
        assert stderr == ""
        stdout = completed.stdout.decode("utf-8")
        output: dict[str, Any] = json.loads(stdout) if stdout.strip() else {}
        return output

    return run


def write_transcript(
    path: Path,
    *,
    start: datetime | None = None,
    touches: Iterable[tuple[str, str, object]] = (),
    extra_lines: Iterable[str] = (),
) -> Path:
    """A synthetic Claude Code transcript: its first event at ``start``, then one tool call each.

    ``start`` defaults to an hour ago. Each ``(tool, key, value)`` in ``touches`` is an assistant
    line calling ``tool`` with ``{key: value}``; ``extra_lines`` are appended as written.
    """
    first = start or datetime.now(UTC) - timedelta(hours=1)
    stamp = first.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    lines = [json.dumps({"type": "queue-operation", "timestamp": stamp})]
    for tool, key, value in touches:
        call = {"type": "tool_use", "name": tool, "input": {key: value}}
        lines.append(
            json.dumps({"type": "assistant", "timestamp": stamp, "message": {"content": [call]}})
        )
    lines.extend(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def late_marker_check(tmp: Path, *, then: str, delay: int = LATE_DELAY) -> str:
    """A check writing ``ready``, then ``then``; a child touches ``late`` in ``delay`` s.

    Both are in ``tmp``. ``late`` appears only if that child outlives the gate (S5: a marker, not
    ``os.kill(pid, 0)``, which a zombie answers when nothing reaps orphans).
    """
    ready, late = shlex.quote(str(tmp / "ready")), shlex.quote(str(tmp / "late"))
    return f"echo started > {ready}; (sleep {delay}; touch {late}) & {then}"


def sleep_until(deadline: float) -> None:
    """Sleep until ``time.monotonic()`` reaches ``deadline``."""
    time.sleep(max(0.0, deadline - time.monotonic()))


def test_blocks_stop_when_check_fast_fails(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    repos = [{"dir": "app", "check_fast": "echo boom; exit 3"}, {"dir": "web", "check_fast": ""}]
    # From the hub, the gate checks the checkouts the session's file edits touched (D2).
    touches = [("Edit", "file_path", str(workspace / "app" / "a.py"))]
    transcript = write_transcript(tmp_path / "session.jsonl", touches=touches)

    output = run_hook(repos, workspace / "demo-hub", transcript=transcript)

    assert output.get("decision") == "block"
    assert "boom" in output["reason"]


def test_reminds_when_check_fast_passes(run_hook: RunHook, workspace: Path) -> None:
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")

    output = run_hook([{"dir": "app", "check_fast": "true"}], workspace / "app")

    assert "decision" not in output
    assert "green" in output.get("systemMessage", "")


def test_skips_repo_when_check_fast_empty(run_hook: RunHook, workspace: Path) -> None:
    (workspace / "web" / "b.ts").write_text("export {}\n", encoding="utf-8")

    output = run_hook([{"dir": "web", "check_fast": ""}], workspace / "web")

    assert "decision" not in output
    assert "no check_fast configured" in output.get("systemMessage", "")


def test_stays_silent_when_no_code_changed(run_hook: RunHook, workspace: Path) -> None:
    assert run_hook([{"dir": "app", "check_fast": "exit 1"}], workspace / "demo-hub") == {}


def test_gates_repos_when_hooks_run_from_hub_worktree(
    workspace: Path, *, hook_python: str, tmp_path: Path
) -> None:
    # A hub worktree holds its own copy of the hooks and of hub.json. Its hooks keep it as their
    # root (Q-4), but the hub and workspace are the main checkout's, so the repos stay gated.
    hub = workspace / "demo-hub"
    worktree = hub / ".claude" / "worktrees" / "x"
    shutil.copytree(hub, worktree, ignore=shutil.ignore_patterns(".claude"))
    # The worktree's hub.json is the one read: its check fails, the main checkout's passes.
    for folder, check in ((hub, "exit 0"), (worktree, "echo boom; exit 3")):
        document = {"project": {"name": "demo"}, "repos": [{"dir": "app", "check_fast": check}]}
        (folder / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    touches = [("Edit", "file_path", str(workspace / "app" / "a.py"))]
    transcript = write_transcript(tmp_path / "session.jsonl", touches=touches)
    event = {
        "cwd": str(worktree),
        "session_id": f"worktree-{os.getpid()}-{tmp_path.name}",
        "transcript_path": str(transcript),
    }

    completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, the rendered hook
        [hook_python, str(worktree / HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
        cwd=worktree,
        env=scratch_env(tmp_path),
        timeout=TIMEOUT,
    )

    assert completed.returncode == 0, completed.stderr
    output = json.loads(completed.stdout)
    assert output["decision"] == "block"
    assert "## app (app): `echo boom; exit 3` FAILED" in output["reason"]


def test_kills_process_group_when_check_exits(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-5: a background child neither holds the gate up nor outlives it. The ``sleep 30`` keeps
    # the check's stdout open: a gate waiting for the output's end would take 30 s.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    marks = tmp_path / "marks"
    marks.mkdir()
    check = late_marker_check(marks, then="sleep 30 & exit 0")

    start = time.monotonic()
    output = run_hook([{"dir": "app", "check_fast": check}], workspace / "app")
    end = time.monotonic()

    assert "decision" not in output
    assert "green" in output.get("systemMessage", "")
    assert end - start < 20
    sleep_until(end + LATE_AFTER)
    assert (marks / "ready").exists()
    assert not (marks / "late").exists()


@pytest.mark.parametrize(
    ("repo_keys", "constant"),
    [
        pytest.param({}, ("TIMEOUT", 1), id="timeout_constant"),
        pytest.param({"check_fast_timeout": 1}, None, id="own_timeout"),
        pytest.param({}, ("BUDGET", 3), id="budget"),
    ],
)
def test_kills_process_group_when_check_times_out(
    run_hook: RunHook,
    workspace: Path,
    tmp_path: Path,
    *,
    repo_keys: Mapping[str, object],
    constant: tuple[str, object] | None,
) -> None:
    # AC-4: a check cut off at its limit (the module's, the repo's own or the budget) leaves no
    # grandchild behind, and a cut run never blocks (D4).
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    marks = tmp_path / "marks"
    marks.mkdir()
    check = late_marker_check(marks, then="sleep 30", delay=CUT_DELAY)
    repo = {"dir": "app", "check_fast": check, **repo_keys}

    start = time.monotonic()
    output = run_hook([repo], workspace / "app", constant=constant)
    end = time.monotonic()

    assert "decision" not in output
    assert end - start < 20
    sleep_until(end + CUT_DELAY + LATE_MARGIN)
    assert (marks / "ready").exists()
    assert not (marks / "late").exists()


def test_reports_output_tail_when_check_prints_past_pipe_buffer(
    run_hook: RunHook, workspace: Path
) -> None:
    # The output goes to a file the gate reads after the run: 256 KiB (past a 64 KiB pipe buffer)
    # neither blocks the check nor reaches the reason, and stderr's last line is kept.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    check = "head -c 262144 /dev/zero | tr '\\0' x; echo; echo tail-mark >&2; exit 3"

    output = run_hook([{"dir": "app", "check_fast": check}], workspace / "app")

    assert output.get("decision") == "block"
    reason = output["reason"]
    assert reason.rstrip().endswith("tail-mark")
    assert "x" * 2900 in reason
    assert len(reason) < 4000


def test_kills_process_group_when_hook_cancelled(
    workspace: Path, *, hook_python: str, tmp_path: Path
) -> None:
    # Claude Code cancels a hook with SIGTERM (also at its 180 s timeout); the check runs in its
    # own session, so only the gate itself can end its group.
    hub = workspace / "demo-hub"
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    marks = tmp_path / "marks"
    marks.mkdir()
    check = late_marker_check(marks, then="sleep 30")
    document = {"project": {"name": "demo"}, "repos": [{"dir": "app", "check_fast": check}]}
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    event = {"cwd": str(workspace / "app"), "session_id": f"cancel-{os.getpid()}-{tmp_path.name}"}
    with subprocess.Popen(  # noqa: S603 - an interpreter from hook_python, the rendered hook
        [hook_python, str(hub / HOOK)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        env=scratch_env(tmp_path),
    ) as hook:
        try:
            assert hook.stdin is not None
            hook.stdin.write(json.dumps(event).encode("utf-8"))
            hook.stdin.close()
            deadline = time.monotonic() + TIMEOUT
            while not (marks / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (marks / "ready").exists()

            hook.send_signal(signal.SIGTERM)
            stdout, stderr = hook.communicate(timeout=TIMEOUT)
            end = time.monotonic()
        finally:  # a failed assert or a communicate timeout must not leave the hook running
            hook.kill()
            hook.wait(timeout=TIMEOUT)

    sleep_until(end + LATE_AFTER)
    assert not (marks / "late").exists()
    assert hook.returncode == 0
    assert stderr == b""
    assert stdout == b""


# The not-run outcomes (D4): a cut or skipped run never blocks, and its line names the repo.
BUDGET_SPENT_NOTE = (
    "[hub stop-gate] check_fast did not finish in every changed repo; finishing anyway."
)
NO_GATE_NOTE = "[hub] code changed; no changed repo has a check_fast to run."


def touch_both(workspace: Path, tmp_path: Path) -> Path:
    """Change ``app/a.py`` and ``web/b.py``; a transcript that edits both."""
    files = (workspace / "app" / "a.py", workspace / "web" / "b.py")
    for path in files:
        path.write_text("x = 1\n", encoding="utf-8")
    touches = [("Edit", "file_path", str(path)) for path in files]
    return write_transcript(tmp_path / "session.jsonl", touches=touches)


def test_names_repos_not_run_when_budget_spent(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-1: the first run is cut by the 3 s budget, the second never starts.
    transcript = touch_both(workspace, tmp_path)
    started = tmp_path / "web-started"
    web_check = f"touch {shlex.quote(str(started))}; sleep 30"
    repos = [{"dir": "app", "check_fast": "sleep 30"}, {"dir": "web", "check_fast": web_check}]

    start = time.monotonic()
    output = run_hook(repos, workspace / "demo-hub", transcript=transcript, constant=("BUDGET", 3))
    took = time.monotonic() - start

    assert took < 20
    assert not started.exists()
    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(BUDGET_SPENT_NOTE)
    assert "app (app): not run: budget" in message
    assert "web (web): not run: budget" in message


def test_runs_next_repo_in_remaining_budget_when_first_passes(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-2: the time ``app`` leaves is enough for ``web``, whose failure still blocks.
    transcript = touch_both(workspace, tmp_path)
    repos = [{"dir": "app", "check_fast": "sleep 2"}, {"dir": "web", "check_fast": "exit 3"}]

    output = run_hook(repos, workspace / "demo-hub", transcript=transcript, constant=("BUDGET", 6))

    assert output.get("decision") == "block"
    assert "## web (web): `exit 3` FAILED" in output["reason"]
    assert "app (app): not run" not in output["reason"]


def test_reports_timeout_without_block_when_own_timeout_hit(
    run_hook: RunHook, workspace: Path
) -> None:
    # AC-3: the repo's own 1 s cuts the run; a timeout is not a failure.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    repo = {"dir": "app", "check_fast": "sleep 30", "check_fast_timeout": 1}

    start = time.monotonic()
    output = run_hook([repo], workspace / "app")
    took = time.monotonic() - start

    assert took < 20
    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(BUDGET_SPENT_NOTE)
    assert "app (app): not run: timeout (1 s)" in message


def test_releases_after_max_blocks_when_not_run_between(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-6: a run with only not-run outcomes leaves the block counter as it was.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    repos = [{"dir": "app", "check_fast": "echo boom; exit 3"}]
    session = f"max-blocks-{os.getpid()}-{tmp_path.name}"
    counter = tmp_path / "tmp" / f"hub-stop-{session}.json"

    def gate(constant: tuple[str, object] | None = None) -> dict[str, Any]:
        return run_hook(repos, workspace / "app", constant=constant, session=session)

    for _ in range(2):
        output = gate()
        assert output.get("decision") == "block"
        assert "boom" in output["reason"]
    output = gate(("BUDGET", 0))
    assert "decision" not in output
    assert "app (app): not run: budget" in output.get("systemMessage", "")
    assert json.loads(counter.read_text(encoding="utf-8")) == {"blocks": 2}
    output = gate()
    assert output.get("decision") == "block"
    assert "boom" in output["reason"]
    output = gate()
    assert "decision" not in output
    assert "still failing after 3 attempts" in output.get("systemMessage", "")


def test_names_repos_when_check_fast_empty_or_absent(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-9: no command runs; both repos are named, neither blocks.
    transcript = touch_both(workspace, tmp_path)
    repos = [{"dir": "app", "check_fast": ""}, {"dir": "web"}]

    output = run_hook(repos, workspace / "demo-hub", transcript=transcript)

    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(NO_GATE_NOTE)
    assert "app (app): no check_fast configured" in message
    assert "web (web): no check_fast configured" in message


def test_keeps_budget_inside_hook_timeout_when_constants_rendered(
    demo_config: HubConfig, pinned_timeout: Callable[..., Any]
) -> None:
    # AC-18: the shipped values, by literal; the run tests lower them.
    def constant(name: str) -> object:
        value, _ = pinned_timeout(demo_config, hook=HOOK, constant=name, event="Stop")
        return value

    budget, hook_timeouts = pinned_timeout(demo_config, hook=HOOK, constant="BUDGET", event="Stop")

    assert budget == 160
    assert hook_timeouts == {
        "plugin/hub-workflow/hooks/hooks.json": [180],
        ".claude/settings.json": [180],
    }
    assert budget < 180
    timeout = constant("TIMEOUT")
    assert (timeout, constant("MAX_BLOCKS"), constant("MIN_RUN")) == (150, 3, 1)
    assert constant("MAX_SUBAGENT_FILES") == 1024  # E34
    assert timeout <= budget
    assert budget == MAX_CHECK_FAST_TIMEOUT


def test_names_repo_not_run_when_budget_left_below_min_run(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # D3: a check never starts with less than MIN_RUN s of budget left (here 160 < 200).
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    started = tmp_path / "started"
    repo = {"dir": "app", "check_fast": f"touch {shlex.quote(str(started))}"}

    output = run_hook([repo], workspace / "app", constant=("MIN_RUN", 200))

    assert not started.exists()
    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(BUDGET_SPENT_NOTE)
    assert "app (app): not run: budget" in message


def test_names_repo_not_run_when_git_status_cut_by_budget(
    run_hook: RunHook, workspace: Path, *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D4: a git status the budget cuts short reads as empty; that is no clean tree, so the repo
    # is named, never passed over in silence.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    git = shutil.which("git")
    assert git is not None
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "git").write_text(
        f'#!/bin/sh\ncase "$1" in status) exec sleep 30;; esac\nexec {shlex.quote(git)} "$@"\n',
        encoding="utf-8",
    )
    (fake / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ.get('PATH', os.defpath)}")

    start = time.monotonic()
    output = run_hook(
        [{"dir": "app", "check_fast": "true"}], workspace / "app", constant=("BUDGET", 2)
    )
    took = time.monotonic() - start

    assert took < 20
    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(BUDGET_SPENT_NOTE)
    assert "app (app): not run: budget" in message


# The session window (D1): it opens at the main transcript's first timestamp, else today's rule.
GREEN_NOTE = "[hub] code changed and check_fast is green."


def utc_stamp(when: datetime, timespec: str = "milliseconds") -> str:
    """``when`` as Claude Code writes a transcript timestamp: UTC, ``Z`` suffix."""
    return when.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


def set_mtime(path: Path, when: datetime) -> None:
    """Write ``path`` (a code file) and date it ``when``."""
    path.write_text("x = 1\n", encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))


@pytest.mark.parametrize("timespec", ["milliseconds", "microseconds"])
def test_dates_changes_from_transcript_when_session_start_read(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, timespec: str
) -> None:
    # AC-12: the window opens at the first line with a timestamp, here a queue-operation. The
    # lines before it are skipped: one has no timestamp, one has no offset (a naive time read as
    # local would open the window 2 h from now and hide new.py). A later line comes after it: the
    # first stamp opens the window, not the last (start + 30 min would hide new.py).
    start = datetime.now(UTC) - timedelta(hours=1)
    naive = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    lines = [
        json.dumps({"type": "summary"}),
        json.dumps({"type": "summary", "timestamp": naive}),
        json.dumps({"type": "queue-operation", "timestamp": utc_stamp(start, timespec)}),
        json.dumps(
            {"type": "user", "timestamp": utc_stamp(start + timedelta(minutes=30), timespec)}
        ),
    ]
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    repos = [{"dir": "app", "check_fast": "echo ran; exit 3"}]
    set_mtime(workspace / "app" / "old.py", start - timedelta(minutes=10))

    assert run_hook(repos, workspace / "app", transcript=transcript) == {}

    set_mtime(workspace / "app" / "new.py", start + timedelta(minutes=1))
    output = run_hook(repos, workspace / "app", transcript=transcript)

    assert output.get("decision") == "block"
    assert "ran" in output["reason"]
    assert "new.py" in output["reason"]
    assert "old.py" not in output["reason"]


def write_unreadable(variant: str, path: Path, stamp: str) -> Path | int:
    """The ``transcript_path`` of one unusable transcript; its timestamps are ``stamp`` or later."""
    line = json.dumps({"type": "queue-operation", "timestamp": stamp})
    writers: dict[str, Callable[[], object]] = {
        "missing": lambda: None,
        "directory": path.mkdir,
        "fifo": lambda: os.mkfifo(path),
        # The timestamp line itself holds the bad byte: a decoder that replaced it would parse it.
        "not_utf8": lambda: path.write_bytes(line[:-1].encode() + b', "x": "\xff"}\n'),
        "not_json": lambda: path.write_text(f"timestamp: {stamp}\n{line[:-1]}\n", encoding="utf-8"),
        "no_timestamp": lambda: path.write_text(
            "\n".join(
                [json.dumps({"type": "user"}), json.dumps({"type": "user", "time": stamp}), ""]
            ),
            encoding="utf-8",
        ),
        # Python 3.11+ parses any fraction, 3.9 only 3 or 6 digits: the hook takes neither.
        "two_digit_fraction": lambda: path.write_text(
            line.replace(stamp, stamp[:-2] + "Z") + "\n", encoding="utf-8"
        ),
        # A start in the future (a bad clock, a copied transcript) would hide every change.
        "future": lambda: path.write_text(
            line.replace(stamp, utc_stamp(datetime.now(UTC) + timedelta(hours=1))) + "\n",
            encoding="utf-8",
        ),
    }
    if variant in {"int_fd", "stdout_fd"}:
        return {"int_fd": 7, "stdout_fd": 1}[variant]
    writers[variant]()
    return path


@pytest.mark.parametrize(
    "variant",
    [
        "missing",
        "int_fd",
        "stdout_fd",
        "open_fd",
        "directory",
        "fifo",
        "not_utf8",
        "not_json",
        "no_timestamp",
        "two_digit_fraction",
        "future",
    ],
)
def test_uses_fallback_window_when_session_start_unreadable(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-13: no session start read, so today's rule: the transcript's birth time where the
    # platform keeps one, else 12 h ago. Every timestamp the variants hold is 10 min ago
    # (``future``: 1 h ahead): one read by mistake would hide new.py (1 h old) and silence the gate.
    stamp = utc_stamp(datetime.now(UTC) - timedelta(minutes=10))
    set_mtime(workspace / "app" / "new.py", datetime.now(UTC) - timedelta(hours=1))
    path = tmp_path / "session.jsonl"
    repos = [{"dir": "app", "check_fast": "true"}]
    if variant == "open_fd":
        # An int is a file descriptor to os.stat and open: this one, open in the hook, is readable.
        path.write_text(
            json.dumps({"type": "queue-operation", "timestamp": stamp}) + "\n", encoding="utf-8"
        )
        fd = os.open(path, os.O_RDONLY)
        try:
            output = run_hook(repos, workspace / "app", transcript=fd, pass_fds=(fd,))
        finally:
            os.close(fd)
        transcript: Path | int = fd
    else:
        transcript = write_unreadable(variant, path, stamp)
        output = run_hook(repos, workspace / "app", transcript=transcript)

    named = isinstance(transcript, Path) and transcript.exists()
    if named and hasattr(os.stat(transcript), "st_birthtime"):
        assert output == {}
    else:
        assert "decision" not in output
        assert output.get("systemMessage", "").startswith(GREEN_NOTE)


# The fan-out (D2, D8-D10): from the hub, the gate checks only the checkouts holding files the
# session's (and its subagents') Edit, Write, MultiEdit and NotebookEdit calls touched.
FAILING_CHECK = "echo ran-$PWD; exit 3"
UNREADABLE_NOTE = (
    "[hub stop-gate] the session transcript could not be read and the session's cwd is in no"
    " repo checkout, so no repo was checked."
)
UNREADABLE_VARIANTS = [
    "missing",
    "int_fd",
    "stdout_fd",
    "open_fd",
    "directory",
    "fifo",
    "not_utf8",
    "not_json",
    "no_timestamp",
    "two_digit_fraction",
    "future",
]


def partial_note(reason: str) -> str:
    """The note of a transcript scan cut short (S3)."""
    return (
        f"[hub stop-gate] transcripts read in part ({reason}): a repo changed only through the"
        " unread part was not checked."
    )


def init_checkout(path: Path, tmp_path: Path) -> Path:
    """A git repository at ``path``: a worktree to ``checkouts()``, which needs only ``.git``."""
    git = shutil.which("git")
    assert git is not None
    path.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
        [git, "init", "-q"], cwd=path, check=True, capture_output=True, env=scratch_env(tmp_path)
    )
    return path


def changed(path: Path) -> str:
    """Write the code file ``path`` (a change this session) and return it as a string."""
    path.write_text("x = 1\n", encoding="utf-8")
    return str(path)


def subagent_transcript(main: Path, name: str) -> Path:
    """The path of subagent transcript ``name`` of the session whose transcript is ``main``."""
    folder = main.with_suffix("") / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def test_checks_touched_worktree_only_when_fan_out_from_hub(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-14: a stale worktree and the main checkout, both changed, are not this session's.
    worktrees = workspace / "app" / ".claude" / "worktrees"
    mine = init_checkout(worktrees / "dem-1-x", tmp_path)
    stale = init_checkout(worktrees / "dem-2-y", tmp_path)
    changed(stale / "y.py")
    changed(workspace / "app" / "main.py")
    touches = [
        ("Edit", "file_path", changed(mine / "x.py")),
        ("MultiEdit", "file_path", str(mine / "z.py")),
        ("Write", "file_path", changed(workspace / "web" / "w.py")),
        ("NotebookEdit", "notebook_path", str(workspace / "web" / "n.ipynb")),
    ]
    transcript = write_transcript(tmp_path / "session.jsonl", touches=touches)
    repos = [
        {"dir": "app", "check_fast": FAILING_CHECK},
        {"dir": "web", "check_fast": FAILING_CHECK},
    ]

    output = run_hook(repos, workspace / "demo-hub", transcript=transcript)

    assert output.get("decision") == "block"
    reason = output["reason"]
    first = reason.index(f"## app (app/.claude/worktrees/dem-1-x): `{FAILING_CHECK}` FAILED")
    assert reason.index(f"## web (web): `{FAILING_CHECK}` FAILED") > first
    assert "dem-2-y" not in reason
    assert "## app (app):" not in reason


@pytest.mark.parametrize(
    ("tool", "key"),
    [
        pytest.param("Edit", "file_path", id="edit"),
        pytest.param("Write", "file_path", id="write"),
        pytest.param("MultiEdit", "file_path", id="multi_edit"),
        pytest.param("NotebookEdit", "notebook_path", id="notebook_edit"),
    ],
)
def test_adds_candidate_when_fan_out_tool_writes_file(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, tool: str, key: str
) -> None:
    # D9: each file-writing tool alone makes its checkout a candidate.
    changed(workspace / "app" / "a.py")
    transcript = write_transcript(
        tmp_path / "session.jsonl", touches=[(tool, key, str(workspace / "app" / "nb.ipynb"))]
    )

    output = run_hook(
        [{"dir": "app", "check_fast": FAILING_CHECK}], workspace / "demo-hub", transcript=transcript
    )

    assert output.get("decision") == "block"
    assert f"## app (app): `{FAILING_CHECK}` FAILED" in output["reason"]


def test_adds_subagent_touches_when_fan_out_reads_subagents(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-15 (D8): a file only a subagent edited still makes its checkout a candidate.
    main = write_transcript(tmp_path / "session.jsonl")
    write_transcript(
        subagent_transcript(main, "agent-1.jsonl"),
        touches=[("Edit", "file_path", changed(workspace / "web" / "b.py"))],
    )

    output = run_hook(
        [{"dir": "web", "check_fast": FAILING_CHECK}], workspace / "demo-hub", transcript=main
    )

    assert output.get("decision") == "block"
    assert f"## web (web): `{FAILING_CHECK}` FAILED" in output["reason"]


def test_keeps_main_session_start_when_fan_out_reads_subagent(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-15: the session starts at the main transcript's first event (an hour ago), never at a
    # subagent's (two days ago), so a file dated a day back is no change of this session.
    main = write_transcript(tmp_path / "session.jsonl")
    old, new = workspace / "web" / "old.py", workspace / "web" / "new.py"
    write_transcript(
        subagent_transcript(main, "agent-1.jsonl"),
        start=datetime.now(UTC) - timedelta(days=2),
        touches=[("Edit", "file_path", str(old)), ("Write", "file_path", str(new))],
    )
    set_mtime(old, datetime.now(UTC) - timedelta(days=1))
    repos = [{"dir": "web", "check_fast": FAILING_CHECK}]

    assert run_hook(repos, workspace / "demo-hub", transcript=main) == {}

    changed(new)
    output = run_hook(repos, workspace / "demo-hub", transcript=main)

    assert output.get("decision") == "block"
    assert "new.py" in output["reason"]
    assert "old.py" not in output["reason"]


@pytest.mark.parametrize("variant", ["missing_dir", "directory_file", "not_utf8"])
def test_ignores_subagent_when_fan_out_cannot_read_it(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-15 (D8, fail open): an unreadable subagent transcript adds nothing; the gate goes on.
    main = write_transcript(tmp_path / "session.jsonl")
    target = changed(workspace / "web" / "b.py")
    line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": target}}]
            },
        }
    )
    if variant == "directory_file":  # uid 0 reads through mode bits: a folder, not a chmod
        subagent_transcript(main, "agent-1.jsonl").mkdir()
    elif variant == "not_utf8":  # the touching line itself holds the bad byte
        subagent_transcript(main, "agent-1.jsonl").write_bytes(
            line[:-1].encode() + b', "x": "\xff"}\n'
        )

    output = run_hook(
        [{"dir": "web", "check_fast": FAILING_CHECK}], workspace / "demo-hub", transcript=main
    )

    assert output == {}


def test_checks_cwd_first_when_fan_out_adds_touched(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # AC-16: cwd's checkout comes first, then the touched ones (web sorts after app).
    changed(workspace / "web" / "b.py")
    touches = [("Edit", "file_path", changed(workspace / "app" / "a.py"))]
    transcript = write_transcript(tmp_path / "session.jsonl", touches=touches)
    repos = [
        {"dir": "app", "check_fast": FAILING_CHECK},
        {"dir": "web", "check_fast": FAILING_CHECK},
    ]

    output = run_hook(repos, workspace / "web", transcript=transcript)

    assert output.get("decision") == "block"
    reason = output["reason"]
    assert reason.index("## web (web):") < reason.index("## app (app):")


@pytest.mark.parametrize(
    "variant",
    [
        "outside",
        "hub",
        "number",
        "empty",
        "relative",
        "read_tool",
        "bash_tool",
        "sibling_prefix",
        "edit",
        "dotdot",
        "symlink",
    ],
)
def test_adds_no_candidate_when_fan_out_path_ignored(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-16 (D2, D9): only an absolute path in a repo checkout, from a file-writing tool, counts.
    # ``relative`` would land in app from the hook's own cwd, ``sibling_prefix`` in app by a bare
    # string prefix (``app2``). ``edit`` proves the setup can block; ``dotdot`` and ``symlink``
    # reach app only once resolved.
    target = changed(workspace / "app" / "a.py")
    (workspace / "app2").mkdir()
    (tmp_path / "link").symlink_to(workspace / "app")
    touches: dict[str, tuple[str, str, object]] = {
        "outside": ("Edit", "file_path", str(tmp_path / "outside" / "x.py")),
        "hub": ("Edit", "file_path", str(workspace / "demo-hub" / "x.py")),
        "number": ("Edit", "file_path", 5),
        "empty": ("Write", "file_path", ""),
        "relative": ("Edit", "file_path", os.path.relpath(target, tmp_path / "elsewhere")),
        "read_tool": ("Read", "file_path", target),
        "bash_tool": ("Bash", "command", f"echo y > {shlex.quote(target)}"),
        "sibling_prefix": ("Edit", "file_path", str(workspace / "app2" / "x.py")),
        "edit": ("Edit", "file_path", target),
        "dotdot": ("Edit", "file_path", str(workspace / "demo-hub" / ".." / "app" / "a.py")),
        "symlink": ("Edit", "file_path", str(tmp_path / "link" / "a.py")),
    }
    transcript = write_transcript(tmp_path / "session.jsonl", touches=[touches[variant]])

    output = run_hook(
        [{"dir": "app", "check_fast": FAILING_CHECK}], workspace / "demo-hub", transcript=transcript
    )

    if variant in {"edit", "dotdot", "symlink"}:
        assert output.get("decision") == "block"
        assert f"## app (app): `{FAILING_CHECK}` FAILED" in output["reason"]
    else:
        assert output == {}


@pytest.mark.parametrize("name", [pytest.param([], id="list"), pytest.param({}, id="dict")])
def test_reads_next_call_when_fan_out_tool_name_odd(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, name: object
) -> None:
    # Fail open: a tool name that is no string (unhashable, too) is skipped, never the gate.
    target = changed(workspace / "app" / "a.py")
    calls = [
        {"type": "tool_use", "name": name, "input": {"file_path": target}},
        {"type": "tool_use", "name": "Edit", "input": {"file_path": target}},
    ]
    lines = [json.dumps({"type": "assistant", "message": {"content": [call]}}) for call in calls]
    transcript = write_transcript(tmp_path / "session.jsonl", extra_lines=lines)

    output = run_hook(
        [{"dir": "app", "check_fast": FAILING_CHECK}], workspace / "demo-hub", transcript=transcript
    )

    assert output.get("decision") == "block"
    assert f"## app (app): `{FAILING_CHECK}` FAILED" in output["reason"]


def run_with_unreadable(
    run_hook: RunHook, variant: str, *, workspace: Path, cwd: Path, check: str, tmp_path: Path
) -> dict[str, Any]:
    """Run the gate with the AC-13 transcript ``variant`` after ``app/new.py`` changed."""
    path = tmp_path / "session.jsonl"
    stamp = utc_stamp(datetime.now(UTC) - timedelta(minutes=10))
    repos = [{"dir": "app", "check_fast": check}]
    if variant != "open_fd":
        transcript = write_unreadable(variant, path, stamp)
        changed(workspace / "app" / "new.py")  # after the transcript: newer than its birth time
        return run_hook(repos, cwd, transcript=transcript)
    path.write_text(
        json.dumps({"type": "queue-operation", "timestamp": stamp}) + "\n", encoding="utf-8"
    )
    changed(workspace / "app" / "new.py")
    fd = os.open(path, os.O_RDONLY)
    try:
        return run_hook(repos, cwd, transcript=fd, pass_fds=(fd,))
    finally:
        os.close(fd)


@pytest.mark.parametrize("variant", UNREADABLE_VARIANTS)
def test_checks_nothing_when_fan_out_fallback_unreadable(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-17 (D10): no touched path can be read and cwd is the hub: nothing runs, and a note says so.
    ran = tmp_path / "ran"
    check = f"touch {shlex.quote(str(ran))}; exit 3"

    output = run_with_unreadable(
        run_hook,
        variant,
        workspace=workspace,
        cwd=workspace / "demo-hub",
        check=check,
        tmp_path=tmp_path,
    )

    assert output == {"systemMessage": UNREADABLE_NOTE}
    assert not ran.exists()


@pytest.mark.parametrize("variant", UNREADABLE_VARIANTS)
def test_checks_cwd_checkout_when_fan_out_fallback_in_repo(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-17 (D10): with cwd in a checkout, that checkout is still checked.
    output = run_with_unreadable(
        run_hook,
        variant,
        workspace=workspace,
        cwd=workspace / "app",
        check=FAILING_CHECK,
        tmp_path=tmp_path,
    )

    assert output.get("decision") == "block"
    assert f"## app (app): `{FAILING_CHECK}` FAILED" in output["reason"]


def test_notes_partial_read_when_fan_out_scan_cut_by_budget(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # S3, S4: no budget left for the scan or the status; both are named, nothing passes silently.
    changed(workspace / "app" / "a.py")
    transcript = write_transcript(tmp_path / "session.jsonl")

    output = run_hook(
        [{"dir": "app", "check_fast": "true"}],
        workspace / "app",
        transcript=transcript,
        constant=("BUDGET", 0),
    )

    assert "decision" not in output
    message = output.get("systemMessage", "")
    assert message.startswith(BUDGET_SPENT_NOTE)
    assert "\napp (app): not run: budget\n" in message
    assert message.endswith("\n" + partial_note("budget spent"))


def test_notes_partial_read_when_fan_out_scan_cut_by_files(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # S3: subagent files past MAX_SUBAGENT_FILES (lowered to 1) are not read; a note says so.
    # The newest are read first (E34): the one touching web is the older.
    main = write_transcript(tmp_path / "session.jsonl")
    write_transcript(subagent_transcript(main, "agent-1.jsonl"))
    older = write_transcript(
        subagent_transcript(main, "agent-2.jsonl"),
        touches=[("Edit", "file_path", changed(workspace / "web" / "b.py"))],
    )
    back = time.time() - 60
    os.utime(older, (back, back))

    output = run_hook(
        [{"dir": "web", "check_fast": FAILING_CHECK}],
        workspace / "demo-hub",
        transcript=main,
        constant=("MAX_SUBAGENT_FILES", 1),
    )

    assert output == {"systemMessage": partial_note("more than 1 subagent file")}


def test_reads_newest_subagent_first_when_fan_out_cap_reached(
    run_hook: RunHook, workspace: Path, tmp_path: Path
) -> None:
    # E34: past the cap, the newest subagent transcripts are the ones read. The newer file sorts
    # last by name, so a read in name order would take the older one and miss web.
    main = write_transcript(tmp_path / "session.jsonl")
    newer = write_transcript(
        subagent_transcript(main, "agent-b.jsonl"),
        touches=[("Edit", "file_path", changed(workspace / "web" / "b.py"))],
    )
    older = write_transcript(subagent_transcript(main, "agent-a.jsonl"))
    now = time.time()
    os.utime(older, (now - 60, now - 60))
    os.utime(newer, (now - 30, now - 30))

    output = run_hook(
        [{"dir": "web", "check_fast": FAILING_CHECK}],
        workspace / "demo-hub",
        transcript=main,
        constant=("MAX_SUBAGENT_FILES", 1),
    )

    assert output.get("decision") == "block"
    reason = output["reason"]
    assert f"## web (web): `{FAILING_CHECK}` FAILED" in reason
    assert reason.endswith("\n" + partial_note("more than 1 subagent file"))
