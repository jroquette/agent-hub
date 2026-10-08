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


def test_blocks_stop_when_check_fast_fails(run_hook: RunHook, workspace: Path) -> None:
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    repos = [{"dir": "app", "check_fast": "echo boom; exit 3"}, {"dir": "web", "check_fast": ""}]

    output = run_hook(repos, workspace / "demo-hub")

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
    event = {"cwd": str(worktree), "session_id": f"worktree-{os.getpid()}-{tmp_path.name}"}

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
    # local would open the window 2 h from now and hide new.py).
    start = datetime.now(UTC) - timedelta(hours=1)
    naive = (datetime.now(UTC) + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    lines = [
        json.dumps({"type": "summary"}),
        json.dumps({"type": "summary", "timestamp": naive}),
        json.dumps({"type": "queue-operation", "timestamp": utc_stamp(start, timespec)}),
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
    """The ``transcript_path`` of one unusable transcript; each timestamp in it is ``stamp``."""
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
    ],
)
def test_uses_fallback_window_when_session_start_unreadable(
    run_hook: RunHook, workspace: Path, tmp_path: Path, *, variant: str
) -> None:
    # AC-13: no session start read, so today's rule: the transcript's birth time where the
    # platform keeps one, else 12 h ago. Every timestamp the variants hold is 10 min ago: one read
    # by mistake would hide new.py (1 h old) and silence the gate.
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
