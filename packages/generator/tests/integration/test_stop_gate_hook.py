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
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig

HOOK = "plugin/hub-workflow/hooks/stop_gate.py"
TIMEOUT = 60

type RunHook = Callable[[Sequence[Mapping[str, str]], Path], dict[str, Any]]


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
def run_hook(workspace: Path, hook_python: str, tmp_path: Path) -> RunHook:
    """Write ``hub.json`` with ``repos``, run the hook for an event at ``cwd``, return its JSON."""
    hub = workspace / "demo-hub"
    # The hook's own cwd is outside every hub: only the event's cwd may lead it to one.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def run(repos: Sequence[Mapping[str, str]], cwd: Path) -> dict[str, Any]:
        document = {"project": {"name": "demo"}, "repos": list(repos)}
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        event = {"cwd": str(cwd), "session_id": f"test-{os.getpid()}-{tmp_path.name}"}
        completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, the rendered hook
            [hook_python, str(hub / HOOK)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
            cwd=elsewhere,
            env=scratch_env(tmp_path),
            timeout=TIMEOUT,
        )
        assert completed.returncode == 0, completed.stderr
        output: dict[str, Any] = json.loads(completed.stdout) if completed.stdout.strip() else {}
        return output

    return run


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
