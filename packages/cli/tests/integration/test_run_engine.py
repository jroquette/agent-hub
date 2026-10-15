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
from click import unstyle
from typer.testing import Result

from agent_hub.cli import run_command as run_module
from agent_hub.cli import run_steps, step_command
from agent_hub.core.workflows.failures import NodeFailedError
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
    """The hub's own ``workflows/issue-to-pr/`` (seeded by init, AGH-227): the built-in's copy,
    its document ``text``."""
    pack = hub / "workflows" / "issue-to-pr"
    shutil.copytree(BUILTIN_WORKFLOWS / "issue-to-pr", pack, dirs_exist_ok=True)
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
    assert "--from verify needs the input start in issue-to-pr" in " ".join(
        unstyle(result.stderr).split()
    )
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


def test_keeps_gate_line_breaks_when_gate_fails(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MAKE_EXIT", "2")
    monkeypatch.setenv("FAKE_MAKE_STDOUT", "1")

    result = run_command(run_workspace.workspace.hub, *LIVE)

    assert result.exit_code == 1, result.output
    (failed,) = [r for r in records(run_workspace.workspace.hub) if r["event"] == "failed"]
    assert failed["reason"] == "gate failed: make check\ngate stdout line\nsynthetic gate output\n"


def test_exits_130_without_tracker_write_when_step_interrupted(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupted(*arguments: object, **options: object) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(step_command, "git_output", interrupted)

    result = run_command(run_workspace.workspace.hub, *LIVE)

    assert result.exit_code == 130, result.output
    assert [call[0] for call in tracked.calls] == ["get_issue"]
    assert "failed" not in [r["event"] for r in records(run_workspace.workspace.hub)]


def test_fails_with_step_reason_when_in_process_step_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_HUB_ROOT", str(tmp_path))
    shown: list[str] = []

    with pytest.raises(NodeFailedError) as raised:
        step_command.run_in_process(
            ["commits", "--target", "{}"], stdin=b"", echo=shown.append, prefix="p"
        )

    assert raised.value.kind == "exec_failed"
    assert raised.value.detail.startswith(f"{tmp_path.resolve()}: not a hub: no hub.json")
    assert shown == []


def test_reads_pack_snapshot_when_hub_pack_changes_during_run(
    run_workspace: Workspace, run_command: CommandRunner, tracked: Any
) -> None:
    hub = run_workspace.workspace.hub
    builtin = (BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_text()
    rewrite = """
  - id: rewrite
    type: shell
    depends_on: [worktree]
    command: [bash, -c, 'printf CHANGED > workflows/issue-to-pr/prompts/implement.md']
"""
    text = builtin.replace(
        "    depends_on: [worktree]\n    when:", "    depends_on: [worktree, rewrite]\n    when:"
    )
    hub_pack(hub, text + rewrite)

    result = run_command(hub, *LIVE)

    assert result.exit_code == 0, result.output
    assert (hub / "workflows" / "issue-to-pr" / "prompts" / "implement.md").read_text() == "CHANGED"
    (call,) = run_workspace.calls("claude")
    prompt = call["argv"][call["argv"].index("-p") + 1]
    assert "You are implementing issue DEM-1" in prompt


IMPLEMENT_CAPS = """    when: "$INPUTS.start != 'verify'"
    model: large
    limits: {max_turns: 9, max_cost_usd: 2.5}
"""


@pytest.mark.parametrize(
    ("flags", "expected"),
    [((), ("9", "2.5", "opus")), (("--max-turns", "7", "--model", "haiku"), ("7", "2.5", "haiku"))],
    ids=["node", "flags"],
)
def test_takes_node_caps_unless_flag_given_when_hub_implement_sets_them(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    flags: tuple[str, ...],
    expected: tuple[str, str, str],
) -> None:
    hub = run_workspace.workspace.hub
    builtin = (BUILTIN_WORKFLOWS / "issue-to-pr" / "issue-to-pr.yaml").read_text()
    hub_pack(hub, builtin.replace("    when: \"$INPUTS.start != 'verify'\"\n", IMPLEMENT_CAPS))

    result = run_command(hub, *LIVE, *flags)

    assert result.exit_code == 0, result.output
    (call,) = run_workspace.calls("claude")
    argv = call["argv"]
    turns, budget, model = expected
    assert argv[argv.index("--max-turns") + 1 :][:5] == [
        turns,
        "--max-budget-usd",
        budget,
        "--model",
        model,
    ]
    picked = records(hub)[0]
    assert (picked["max_turns"], picked["budget"], picked["model"]) == (
        int(turns),
        float(budget),
        model,
    )


def test_names_entry_point_in_warning_when_workflow_run_title_unmatched(
    run_workspace: Workspace,
    run_command: CommandRunner,
    tracked: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_workspace.workspace.use_conventions(project={"commit_title": "{ISSUE}: {summary}"})
    monkeypatch.setenv("FAKE_CLAUDE_SUBJECTS", "WIP")
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    result = run_command(run_workspace.workspace.hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 0, result.output
    warnings = [line for line in result.stderr.splitlines() if "does not match" in line]
    assert len(warnings) == 1
    assert warnings[0].startswith("hub workflow run: warning: ")
