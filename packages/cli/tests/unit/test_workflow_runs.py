"""A run's snapshot (AGH-355): the pack files each node type needs, and no silent skip."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_hub.cli.workflow_runs as workflow_runs
from agent_hub.cli.workflow_runs import snapshot_run
from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.workflow_fakes import a_plan
from agent_hub.core.workflows.plan import WorkflowPlan

ACTION = {"id": "send", "type": "action", "action": "send-queue-message"}
EXPECT = {"id": "wait", "type": "expect", "action": "get-order", "every": "5s", "timeout": "1m"}
EXPECT |= {"until_when": "$self.output.status == 'OK'", "depends_on": ["send"]}


def test_copies_no_pack_file_when_snapshot_holds_action_nodes(tmp_path: Path) -> None:
    plan = a_plan(ACTION, EXPECT, kind="scenario")

    pack, content_hash = snapshot_run(tmp_path, document={}, plan=plan, pack_root=tmp_path)

    assert sorted(path.name for path in pack.parent.rglob("*") if path.is_file()) == [
        "workflow.json"
    ]
    assert content_hash.startswith("sha256:")


def test_refuses_node_when_snapshot_meets_unknown_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = a_plan(ACTION)
    unknown = SimpleNamespace(id="odd", type="mystery")
    monkeypatch.setattr(WorkflowPlan, "all_nodes", lambda self: iter([unknown]))

    with pytest.raises(TypeError, match="mystery"):
        snapshot_run(tmp_path, document={}, plan=plan, pack_root=tmp_path)


def test_restores_polls_when_expect_poll_recorded() -> None:
    def polled(attempt: int, poll: int) -> dict[str, JsonValue]:
        return {"event": "expect.poll", "node": "wait", "attempt": attempt, "poll": poll}

    records: list[dict[str, JsonValue]] = [
        {"event": "start", "run": "walk-1"},
        polled(1, 1),
        polled(1, 2),
        {"event": "step_end", "node": "wait", "attempt": 1, "status": "failed"},
        {"event": "resume"},
        polled(2, 1),
        {"event": "expect.poll", "node": "other", "attempt": 1, "poll": 1},
    ]

    state = workflow_runs.prior_state(records)

    # The 1000-poll bound counts every poll of a node in the run, retries and resumes too (E-7).
    assert state.polls == {"wait": 3, "other": 1}
    assert state.attempts["wait"] == 2
