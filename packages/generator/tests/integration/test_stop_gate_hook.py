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
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pytest

from agent_hub.core.hub_config.model import HubConfig

HOOK = "plugin/hub-workflow/hooks/stop_gate.py"
TIMEOUT = 60


class RunHook(Protocol):
    """The ``run_hook`` fixture: write ``hub.json``, run the hook, return its JSON output."""

    def __call__(
        self,
        repos: Sequence[Mapping[str, object]],
        cwd: Path,
        *,
        transcript: Path | None = None,
        constant: tuple[str, object] | None = None,
        session: str | None = None,
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

    ``transcript`` becomes the event's ``transcript_path``, ``session`` its ``session_id``, and
    ``constant`` replaces one module constant of the hook. The hook must exit 0 with an empty
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
        transcript: Path | None = None,
        constant: tuple[str, object] | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        document = {"project": {"name": "demo"}, "repos": list(repos)}
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        event = {"cwd": str(cwd), "session_id": session or f"test-{os.getpid()}-{tmp_path.name}"}
        if transcript is not None:
            event["transcript_path"] = str(transcript)
        if constant is None:
            completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, the rendered hook
                [hook_python, str(hub / HOOK)],
                input=json.dumps(event).encode("utf-8"),
                capture_output=True,
                check=False,
                cwd=elsewhere,
                env=scratch_env(tmp_path),
                timeout=TIMEOUT,
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


def late_marker_check(tmp: Path, *, then: str) -> str:
    """A check writing ``<tmp>/ready``, whose child touches ``<tmp>/late`` in 2 s, then ``then``.

    ``late`` appears only if that child outlives the gate (S5: a marker, not ``os.kill(pid, 0)``,
    which a zombie answers when nothing reaps orphans).
    """
    ready, late = shlex.quote(str(tmp / "ready")), shlex.quote(str(tmp / "late"))
    return f"echo started > {ready}; (sleep 2; touch {late}) & {then}"


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
    took = time.monotonic() - start

    assert "decision" not in output
    assert "green" in output.get("systemMessage", "")
    assert took < 2.5
    sleep_until(start + 3.5)
    assert (marks / "ready").exists()
    assert not (marks / "late").exists()


@pytest.mark.parametrize(
    ("repo_keys", "constant"),
    [pytest.param({}, ("TIMEOUT", 1), id="timeout_constant")],
)
def test_kills_process_group_when_check_times_out(
    run_hook: RunHook,
    workspace: Path,
    tmp_path: Path,
    *,
    repo_keys: Mapping[str, object],
    constant: tuple[str, object] | None,
) -> None:
    # AC-4: a check cut off at its limit leaves no grandchild behind.
    (workspace / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    marks = tmp_path / "marks"
    marks.mkdir()
    repo = {"dir": "app", "check_fast": late_marker_check(marks, then="sleep 30"), **repo_keys}

    start = time.monotonic()
    run_hook([repo], workspace / "app", constant=constant)
    took = time.monotonic() - start

    assert took < 3
    sleep_until(start + 3.5)
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
