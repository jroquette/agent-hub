"""``hub run --live`` runs the ``issue-to-pr`` workflow through the engine (AGH-224, AC-213.13).

``test_run_command.py`` is the bar for what ``hub run`` does; these tests cover what only the
engine adds: the hub's own ``workflows/issue-to-pr/`` is the one run when present, ``--from
verify`` is an input of the workflow, the session flags reach the ``implement`` node, and a failed
stage's failure kind (AGH-179) reaches the ``failed`` record and its ``step.end`` event.
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli import run_command as run_module
from agent_hub.cli import run_steps
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.storage.event_store import open_event_store

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
LIVE = ("run", "DEM-1", "--repo", "demo-api", "--live")
MARKER_NODE = """
  - id: marker
    type: shell
    depends_on: [worktree]
    command: [bash, -c, 'printf ran > engine-ran']
"""
NO_START = """version: 1
name: issue-to-pr
revision: 1
inputs:
  issue: {required: true}
  repo: {required: true}
  issue_text: {required: true}
nodes: [{id: a, type: shell, command: [bash, -c, 'exit 0']}]
"""


class Resolve:
    """Replaces ``run_command.resolve_tracker_client``: returns the run's tracker."""

    def __init__(self, client: object) -> None:
        self.client = client

    def __call__(self, config: object, environ: object, *, hub_root: object) -> object:
        return self.client


@pytest.fixture
def tracked(run_tracker: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    return run_tracker


def hub_pack(hub: Path, text: str | None = None) -> Path:
    """The hub's own ``workflows/issue-to-pr/``: the built-in's copy, its document ``text``."""
    pack = hub / "workflows" / "issue-to-pr"
    shutil.copytree(BUILTIN_WORKFLOWS / "issue-to-pr", pack)
    if text is not None:
        (pack / "issue-to-pr.yaml").write_text(text)
    return pack


def records(hub: Path) -> list[dict[str, Any]]:
    found = []
    for path in sorted((hub / ".agent-runs").glob("*.jsonl")):
        found += [json.loads(line) for line in path.read_text().splitlines()]
    return found


def test_runs_hub_workflow_when_hub_defines_issue_to_pr(
    run_workspace: Workspace, run_command: CommandRunner, tracked: Any
) -> None:
    hub = run_workspace.workspace.hub
    builtin = (BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_text()
    hub_pack(hub, builtin + MARKER_NODE)

    result = run_command(hub, *LIVE)

    assert result.exit_code == 0, result.output
    assert (hub / "engine-ran").read_text() == "ran"
    assert records(hub)[-1]["outcome"] == "delivered"
    assert not (hub / ".agent-runs" / "workflows").exists()
    assert not [line for line in result.stdout.splitlines() if line.startswith("run ")]


def test_refuses_run_when_hub_issue_to_pr_does_not_load(
    run_workspace: Workspace, run_command: CommandRunner, tracked: Any
) -> None:
    hub = run_workspace.workspace.hub
    hub_pack(hub, "version: 1\nname: issue-to-pr\nnodes: []\n")

    result = run_command(hub, *LIVE)

    assert result.exit_code == 1
    assert "workflows/issue-to-pr/issue-to-pr.yaml" in result.stderr
    assert tracked.calls == []
    assert run_workspace.calls("claude") == []


def test_refuses_from_verify_when_hub_issue_to_pr_lacks_start(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    hub = run_workspace.workspace.hub
    hub_pack(hub, NO_START)

    result = run_command(hub, *LIVE, "--from", "verify")

    assert result.exit_code == 2, result.output
    assert "--from verify needs the input start in issue-to-pr" in " ".join(result.stderr.split())
    assert tracked.calls == []


def test_passes_session_flags_to_implement_node_when_given(
    run_workspace: Workspace, run_command: CommandRunner, tracked: Any
) -> None:
    flags = ("--model", "opus", "--effort", "high", "--max-turns", "7", "--budget", "1.5")

    result = run_command(run_workspace.workspace.hub, *LIVE, *flags)

    assert result.exit_code == 0, result.output
    (call,) = run_workspace.calls("claude")
    argv = call["argv"]
    assert argv[argv.index("--max-turns") + 1 :][:5] == [
        "7",
        "--max-budget-usd",
        "1.5",
        "--model",
        "opus",
    ]
    assert argv[argv.index("--settings") + 1] == '{"effortLevel": "high"}'
    picked = records(run_workspace.workspace.hub)[0]
    assert (picked["budget"], picked["max_turns"], picked["model"]) == (1.5, 7, "opus")


@pytest.mark.parametrize(
    ("variables", "timeout", "kind"),
    [({"FAKE_MAKE_EXIT": "2"}, None, "exec_failed"), ({"FAKE_MAKE_SLEEP": "30"}, 1.0, "timeout")],
    ids=["exit", "timeout"],
)
def test_records_failure_kind_when_stage_fails(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    variables: dict[str, str],
    timeout: float | None,
    kind: str,
) -> None:
    db = tmp_path / "events" / "events.db"
    monkeypatch.setenv("AGENT_HUB_DB", str(db))
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    if timeout is not None:
        monkeypatch.setattr(run_steps, "GATE_TIMEOUT", timeout)

    result = run_command(run_workspace.workspace.hub, *LIVE)

    assert result.exit_code == 1, result.output
    (failed,) = [r for r in records(run_workspace.workspace.hub) if r["event"] == "failed"]
    assert (failed["stage"], failed["failure_kind"]) == ("VERIFYING", kind)
    (end,) = [
        event
        for event in open_event_store(db).read_all()
        if event.type == "step.end" and event.payload["status"] == "failed"
    ]
    assert (end.step, end.payload["failure_kind"]) == ("verify", kind)


def test_keeps_failure_kind_out_when_issue_read_fails(
    run_workspace: Workspace, run_command: CommandRunner, tracked: Any
) -> None:
    tracked.fail_on.add("get_issue")

    result = run_command(run_workspace.workspace.hub, *LIVE)

    assert result.exit_code == 1
    (failed,) = records(run_workspace.workspace.hub)
    assert (failed["event"], failed["stage"]) == ("failed", "PICKED")
    assert "failure_kind" not in failed
