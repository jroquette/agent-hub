"""The retro pack's ``metrics.py`` (AGH-488), in process: step 1's numbers for the weekly retro."""

import importlib.util
import sys
from datetime import date
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/retro/scripts/metrics.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.retro.scripts.metrics"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


SINCE = date(2026, 10, 15)
DAY = "2026-10-20"


def start(workflow: str, *, at: str = f"{DAY}T09:00:00+00:00", **extra: Any) -> dict[str, Any]:
    return {"event": "start", "ts": at, "run": f"{workflow}-1", "workflow": workflow} | extra


def step_end(node: str, *, status: str = "ok", output: Any = None) -> dict[str, Any]:
    line = {"event": "step_end", "ts": f"{DAY}T09:30:00+00:00", "node": node, "attempt": 1}
    return line | {"status": status, "failure_kind": None, "output": output}


def end(status: str, *, outcome: Any = None, reason: str | None = None) -> dict[str, Any]:
    line = {"event": "end", "ts": f"{DAY}T10:00:00+00:00", "status": status}
    return line | {"outcome": outcome, "reason": reason}


def test_counts_runs_and_outcomes_per_workflow_when_records_folded() -> None:
    runs = [
        [start("deliver"), step_end("rounds__check"), end("done", outcome="delivered")],
        [
            start("deliver"),
            step_end("rounds__check", status="failed"),
            {"event": "retry", "ts": f"{DAY}T09:31:00+00:00", "node": "rounds__check"},
            end("failed", reason="rounds__check"),
        ],
    ]

    found = load().fold_runs(runs, since=SINCE)

    assert found["workflow.deliver.runs"] == 2
    assert found["workflow.deliver.done"] == 1
    assert found["workflow.deliver.failed"] == 1
    assert found["workflow.deliver.cancelled"] == 0
    assert found["workflow.deliver.open"] == 0
    assert found["workflow.deliver.retries"] == 1
    assert found["workflow.deliver.outcome.delivered"] == 1
    assert found["workflow.deliver.failed_at.rounds__check"] == 1


def test_counts_review_rounds_when_review_body_nodes_end() -> None:
    runs = [
        [start("deliver"), *[step_end("rounds__review")] * 3, end("done")],
        [start("implement"), *[step_end("pass-1__rounds__review")] * 2, end("done")],
        [start("implement"), step_end("rounds__review", status="skipped"), end("done")],
    ]

    found = load().fold_runs(runs, since=SINCE)

    assert found["workflow.deliver.review_rounds"] == 3
    assert found["workflow.implement.review_rounds"] == 2


def test_computes_no_ship_rate_when_eval_verdicts_recorded() -> None:
    verdicts = ["SHIP", "NO-SHIP", "SHIP-WITH-OWNER-STEPS", "SHIP"]
    runs = [
        [start("implement"), step_end("eval", output={"verdict": v}), end("done")] for v in verdicts
    ]
    runs.append([start("review"), step_end("lens", output={"verdict": "PASS"}), end("done")])

    found = load().fold_runs(runs, since=SINCE)

    assert found["workflow.implement.evals"] == 4
    assert found["workflow.implement.no_ship"] == 1
    assert found["workflow.implement.no_ship_rate"] == 0.25
    assert found["workflow.review.evals"] == 0
    assert "workflow.review.no_ship_rate" not in found


def test_counts_open_runs_and_gate_wait_when_gate_decided_later() -> None:
    gate = {"event": "gate", "ts": f"{DAY}T10:00:00+00:00", "node": "pick", "attempt": 1}
    decision = {"event": "decision", "ts": f"{DAY}T13:00:00+00:00", "node": "pick", "attempt": 1}
    runs = [
        [start("implement"), gate, decision, end("done")],
        [start("implement"), gate | {"node": "plan"}],
    ]

    found = load().fold_runs(runs, since=SINCE)

    assert found["workflow.implement.gates"] == 2
    assert found["workflow.implement.gate_wait_h_median"] == 3.0
    assert found["workflow.implement.open"] == 1
    assert found["workflow.implement.done"] == 1


def test_leaves_out_retro_issue_to_pr_and_scenarios_when_records_folded() -> None:
    runs = [
        [start("retro"), end("done", outcome="drafted")],
        [start("issue-to-pr"), end("done")],
        [start("deliver", kind="scenario"), end("done")],
        [step_end("orphan")],
        [start("deliver"), end("done")],
    ]

    found = load().fold_runs(runs, since=SINCE)

    assert {key.split(".")[1] for key in found} == {"deliver"}
    assert found["workflow.deliver.runs"] == 1


def test_ignores_run_started_before_window_when_records_folded() -> None:
    runs = [
        [start("deliver", at="2026-10-14T23:59:00+00:00"), end("done")],
        [start("deliver", at="2026-10-15T00:00:00+00:00"), end("done")],
    ]

    found = load().fold_runs(runs, since=SINCE)

    assert found["workflow.deliver.runs"] == 1
