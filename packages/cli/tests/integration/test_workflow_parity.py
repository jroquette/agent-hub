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
  ``reason`` are compared without trailing whitespace; a gate's diagnosis holds only its stderr
  (the fake gate prints its failure there), where ``hub run``'s holds stdout then stderr;
- the session's verdict carries ``done`` (the loop's ``until_field``): the fake ``claude`` adds it
  for both runs (``FAKE_CLAUDE_DONE``), and ``hub run`` ignores it;
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
from agent_hub.storage.event_store import open_event_store

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
BRANCH = "jdoe/dem-1"
SCENARIOS: Mapping[str, tuple[Mapping[str, str], int, str]] = {
    "done": ({}, 0, "delivered"),
    "no-commit": ({"FAKE_CLAUDE_MODE": "done-no-commit"}, 0, "no_changes"),
    "blocked": ({"FAKE_CLAUDE_MODE": "blocked"}, 3, "blocked"),
    "error": ({"FAKE_CLAUDE_MODE": "error"}, 1, "failed"),
    "gate-fail": ({"FAKE_MAKE_EXIT": "2"}, 1, "failed"),
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
    monkeypatch.setenv("FAKE_CLAUDE_DONE", "1")
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
