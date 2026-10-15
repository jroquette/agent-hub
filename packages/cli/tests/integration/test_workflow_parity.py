"""v0.14 ``hub run`` and ``hub workflow run issue-to-pr --live`` give the same run (AC-213.12).

Each scenario runs twice in one copy of the ``DEMO`` workspace, with the same fakes (``claude``,
``gh``, ``make``) and a fresh recording tracker each time: first ``hub run``, then, after the
worktree and the branch are removed, the built-in workflow. Both must make the same tracker calls,
write the same ``.agent-runs`` records, store the same events and end with the same delivery and
exit code (delivered 0, no_changes 0, blocked 3, failed 1).

Intended differences, left out of the comparison:

- the run id (each run has its own) and every timestamp;
- a failure's diagnosis loses its trailing line break: the workflow reads it from the failed
  node's record, whose detail is stripped, so the comment bodies and the ``failed`` record's
  ``reason`` are compared without trailing whitespace (the gate's stdout and stderr are kept, in
  ``hub run``'s order);
- the workflow's own record (``.agent-runs/workflows/<run>/``) exists only for the workflow; its
  node events are not sent for issue-to-pr, so the events are ``hub run``'s.
"""

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli import run_command as run_module
from agent_hub.cli import run_log
from agent_hub.cli.errors import RunLogError
from agent_hub.storage.event_store import open_event_store

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
BRANCH = "jdoe/dem-1"
SCENARIOS: Mapping[str, tuple[Mapping[str, str], int, str]] = {
    "done": ({}, 0, "delivered"),
    "no-commit": ({"FAKE_CLAUDE_MODE": "done-no-commit"}, 0, "no_changes"),
    "prose": ({"FAKE_CLAUDE_MODE": "prose"}, 0, "delivered"),
    "silent": ({"FAKE_CLAUDE_MODE": "silent"}, 0, "no_changes"),
    "blocked": ({"FAKE_CLAUDE_MODE": "blocked"}, 3, "blocked"),
    "blocked-text": ({"FAKE_CLAUDE_MODE": "blocked-text"}, 3, "blocked"),
    "done-dirty": ({"FAKE_CLAUDE_MODE": "done-dirty"}, 1, "failed"),
    "error": ({"FAKE_CLAUDE_MODE": "error"}, 1, "failed"),
    "gate-fail": ({"FAKE_MAKE_EXIT": "2"}, 1, "failed"),
    "gate-fail-stdout": ({"FAKE_MAKE_EXIT": "2", "FAKE_MAKE_STDOUT": "1"}, 1, "failed"),
    "pr-fail": ({"FAKE_GH_MODE": "fail"}, 1, "failed"),
}


class Resolve:
    """Replaces ``run_command.resolve_tracker_client``: returns the run's tracker."""

    def __init__(self, client: object) -> None:
        self.client = client

    def __call__(self, config: object, environ: object, *, hub_root: object) -> object:
        return self.client


@dataclass(frozen=True)
class Seen:
    """What one run left, its run id taken out."""

    exit_code: int
    calls: list[tuple[str, ...]]
    records: list[dict[str, Any]]
    events: list[tuple[str, str | None, dict[str, Any]]]


def records_of(hub: Path) -> list[dict[str, Any]]:
    found = []
    for path in sorted((hub / ".agent-runs").glob("*.jsonl")):
        found += [json.loads(line) for line in path.read_text().splitlines()]
    return found


def run_once(
    hub: Path,
    tracker: Any,
    invoke: Callable[[], Result],
    *,
    monkeypatch: pytest.MonkeyPatch,
    db: Path,
) -> Seen:
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(tracker))
    before = len(records_of(hub))
    known = {event.source_id for event in open_event_store(db).read_all()}

    result = invoke()

    records = records_of(hub)[before:]
    assert records, result.output
    run_id = records[0]["run"]
    events = [
        (event.type, event.step, {k: unrun(v, run_id) for k, v in event.payload.items()})
        for event in open_event_store(db).read_all()
        if event.source_id not in known
    ]
    assert {event.session for event in open_event_store(db).read_all()} >= {f"run:{run_id}"}
    calls = [
        tuple(argument.replace(run_id, "<run>").rstrip() for argument in call)
        for call in tracker.calls
    ]
    kept = [
        {k: v.rstrip() if k == "reason" else v for k, v in record.items() if k not in {"ts", "run"}}
        for record in records
    ]
    return Seen(result.exit_code, calls, kept, events)


def unrun(value: object, run_id: str) -> object:
    return value.replace(run_id, "<run>") if isinstance(value, str) else value


def reset(workspace: Workspace) -> None:
    """Remove the run's worktree and its branch, in the clone and the origin."""
    clone = workspace.ws / "demo-api"
    worktree = clone / ".claude" / "worktrees" / "dem-1"
    workspace.git(clone, "worktree", "remove", "--force", str(worktree))
    workspace.git(clone, "branch", "-D", BRANCH)
    origin = workspace.origin("demo-api")
    if workspace.git(origin, "branch", "--list", BRANCH):
        workspace.git(origin, "branch", "-D", BRANCH)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_matches_hub_run_when_same_scenario_runs(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
) -> None:
    variables, exit_code, delivery = SCENARIOS[scenario]
    workspace = run_workspace.workspace
    db = tmp_path / "events" / "events.db"
    monkeypatch.setenv("AGENT_HUB_DB", str(db))
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    issue = ("DEM-1", "--repo", "demo-api", "--live")
    inputs = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    fresh = copy.deepcopy(run_tracker)

    hub_run = run_once(
        workspace.hub,
        run_tracker,
        lambda: run_command(workspace.hub, "run", *issue),
        monkeypatch=monkeypatch,
        db=db,
    )
    reset(workspace)
    workflow = run_once(
        workspace.hub,
        fresh,
        lambda: run_command(workspace.hub, "workflow", "run", "issue-to-pr", *inputs),
        monkeypatch=monkeypatch,
        db=db,
    )

    assert (hub_run.exit_code, workflow.exit_code) == (exit_code, exit_code)
    assert workflow.calls == hub_run.calls
    assert workflow.records == hub_run.records
    assert workflow.records[-1]["outcome"] == delivery
    assert workflow.events == hub_run.events
    (end,) = [payload for kind, _, payload in workflow.events if kind == "run.end"]
    assert end["outcome"] == delivery


def test_refuses_issue_text_when_given_as_input(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--input", "issue_text=x")

    result = run_command(
        run_workspace.workspace.hub, "workflow", "run", "issue-to-pr", *given, "--live"
    )

    assert result.exit_code == 2
    assert "issue_text is read from the tracker" in result.stderr
    assert run_tracker.calls == []


def test_prints_nodes_without_tracker_when_not_live(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api")

    result = run_command(run_workspace.workspace.hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == (
        "would run: worktree (shell): hub step worktree --issue '$INPUTS.issue'"
        " --repo '$INPUTS.repo'"
    )
    assert run_tracker.calls == []


@pytest.mark.parametrize("option", ["--resume", "--abandon"])
def test_refuses_resume_and_abandon_when_run_is_issue_to_pr(
    run_workspace: Workspace,
    run_command: CommandRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    folder = run_workspace.workspace.hub / ".agent-runs" / "workflows" / "abc12345"
    folder.mkdir(parents=True)
    start = {"event": "start", "run": "abc12345", "workflow": "issue-to-pr"}
    (folder / "records.jsonl").write_text(json.dumps(start) + "\n")

    result = run_command(run_workspace.workspace.hub, "workflow", "run", option, "abc12345")

    assert result.exit_code == 2
    assert "resume and abandon are not supported for issue-to-pr; start a new run" in (
        " ".join(result.stderr.split())
    )
    assert sorted(path.name for path in folder.iterdir()) == ["records.jsonl"]
    assert (folder / "records.jsonl").read_text() == json.dumps(start) + "\n"


def test_refuses_run_when_hub_issue_to_pr_lacks_inputs(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = run_workspace.workspace.hub
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    pack = hub / "workflows" / "issue-to-pr"
    pack.mkdir(parents=True)
    (pack / "issue-to-pr.yaml").write_text(
        "version: 1\nname: issue-to-pr\nrevision: 1\n"
        "inputs: {issue: {required: true}, repo: {required: true}}\n"
        "nodes: [{id: a, type: shell, command: [echo]}]\n"
    )
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    result = run_command(hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 2, result.output
    assert "issue-to-pr must declare the inputs issue, repo and issue_text" in (
        " ".join(result.stderr.split())
    )
    assert run_tracker.calls == []
    assert not (hub / ".agent-runs" / "workflows").exists()


def test_keeps_tokens_from_children_when_issue_to_pr_runs_live(
    logged_git: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = logged_git.workspace
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    monkeypatch.setenv("GH_TOKEN", "gh" + "o_" + "y" * 36)
    script = b'#!/bin/sh\nexport -p > "$FAKE_RUN_LOGS/setup-env.txt"\n'
    workspace.advance("demo-api", {"scripts/worktree-setup.sh": (script, 0o755)})
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    result = run_command(workspace.hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 0, result.output
    calls = {tool: logged_git.calls(tool) for tool in ("git", "gh", "make", "claude")}
    assert all(calls.values()), calls
    for call in (call for tool_calls in calls.values() for call in tool_calls):
        assert KEY_VARIABLE not in call["env"], call["argv"]
    token_bearing = [call for call in calls["git"] if {"fetch", "push"} & set(call["argv"])]
    assert token_bearing
    for call in calls["git"]:
        assert ("GH_TOKEN" in call["env"]) == (call in token_bearing), call["argv"]
    for call in (*calls["make"], *calls["claude"]):
        assert "GH_TOKEN" not in call["env"]
    assert all("GH_TOKEN" in call["env"] for call in calls["gh"])
    setup = (logged_git.logs / "setup-env.txt").read_text()
    assert "GH_TOKEN" not in setup
    assert KEY_VARIABLE not in setup


def test_leaves_no_run_folder_when_issue_read_fails(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = run_workspace.workspace.hub
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    run_tracker.fail_on.add("get_issue")
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    result = run_command(hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 1
    assert [(r["state"], r["event"]) for r in records_of(hub)] == [("PICKED", "failed")]
    assert list((hub / ".agent-runs" / "workflows").iterdir()) == []


def test_stops_run_when_record_cannot_be_written(
    run_workspace: Workspace,
    run_command: CommandRunner,
    run_tracker: Any,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = run_workspace.workspace.hub
    monkeypatch.setattr(run_module, "resolve_tracker_client", Resolve(run_tracker))
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)
    real = run_log.RunLog.record

    def record(self: Any, event: str, data: Any = None) -> None:
        if event == "worktree_ready":
            raise RunLogError(OSError(28, "No space left on device"))
        real(self, event, data)

    monkeypatch.setattr(run_log.RunLog, "record", record)
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--live")

    result = run_command(hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 1
    assert "No space left on device" in result.stderr
    assert run_workspace.calls("claude") == []
    assert [call[0] for call in run_tracker.calls] == ["get_issue"]
