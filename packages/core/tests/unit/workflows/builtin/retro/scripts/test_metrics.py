"""The retro pack's ``metrics.py`` (AGH-488), in process: step 1's numbers for the weekly retro."""

import importlib.util
import json
import os
import sys
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

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


TODAY = "2026-10-22"
IN_WINDOW = datetime(2026, 10, 20, 12, tzinfo=UTC).timestamp()


def write_run(root: Path, run: str, lines: list[str], *, mtime: float = IN_WINDOW) -> Path:
    folder = root / ".agent-runs" / "workflows" / run
    folder.mkdir(parents=True)
    (folder / "records.jsonl").write_text("".join(f"{line}\n" for line in lines))
    os.utime(folder, (mtime, mtime))
    return folder


def run_lines(workflow: str) -> list[str]:
    return [json.dumps(start(workflow)), json.dumps(end("done"))]


def source(found: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in found["sources"] if item["name"] == name)


def run_main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = load().main(argv)
    out = capsys.readouterr().out
    return code, (json.loads(out) if out else {})


def test_marks_runs_partial_when_record_large_or_bad_lines(tmp_path: Path) -> None:
    metrics = load()
    big = write_run(tmp_path, "big", [])
    with (big / "records.jsonl").open("wb") as file:
        file.truncate(metrics.MAX_RECORD_BYTES + 1)
    write_run(tmp_path, "bad", [*run_lines("deliver"), "{not json", "[1, 2]"])

    records, problems = metrics.read_runs(tmp_path, SINCE)

    assert [len(run) for run in records] == [2]
    assert problems == ["1 run records over 16 MiB", "2 bad lines"]
    reading = metrics.runs_source(tmp_path, SINCE)
    assert reading.sources == [
        {"name": "runs", "status": "partial", "reason": "1 run records over 16 MiB; 2 bad lines"}
    ]
    assert reading.metrics["workflow.deliver.runs"] == 1


def test_reads_newest_five_hundred_runs_when_more_in_window(tmp_path: Path) -> None:
    metrics = load()
    write_run(tmp_path, "oldest", run_lines("spike"), mtime=IN_WINDOW - 3600)
    for n in range(metrics.MAX_RUNS):
        write_run(tmp_path, f"run-{n}", run_lines("deliver"), mtime=IN_WINDOW + n)
    write_run(tmp_path, "before", run_lines("upgrade"), mtime=IN_WINDOW - 30 * 86400)

    reading = metrics.runs_source(tmp_path, SINCE)

    assert reading.metrics["workflow.deliver.runs"] == 500
    assert not any(
        key.startswith(("workflow.spike.", "workflow.upgrade.")) for key in reading.metrics
    )
    assert source({"sources": reading.sources}, "runs") == {
        "name": "runs",
        "status": "partial",
        "reason": "more than 500 runs; oldest left out",
    }


def test_skips_link_when_run_folder_is_symlink(tmp_path: Path) -> None:
    metrics = load()
    elsewhere = write_run(tmp_path / "other", "real", run_lines("deliver"))
    (tmp_path / ".agent-runs" / "workflows").mkdir(parents=True)
    (tmp_path / ".agent-runs" / "workflows" / "linked").symlink_to(elsewhere)
    kept = write_run(tmp_path, "kept", [])
    (kept / "records.jsonl").unlink()
    (kept / "records.jsonl").symlink_to(elsewhere / "records.jsonl")

    records, problems = metrics.read_runs(tmp_path, SINCE)

    assert records == []
    assert problems == []


def test_caps_metrics_at_three_hundred_keys_when_sources_large() -> None:
    metrics = load()
    many = {f"prs.acme/r{n}.merged": n for n in range(250)}
    workflow = {f"workflow.w{n}.runs": 1 for n in range(150)}
    readings = [
        metrics.Reading(many, [{"name": "github", "status": "ok", "reason": ""}], {}),
        metrics.Reading(workflow, [{"name": "runs", "status": "ok", "reason": ""}], {}),
    ]

    found = metrics.assemble(readings, days=7, since=SINCE, until=date(2026, 10, 22))

    assert len(found["metrics"]) == 300
    assert list(found["metrics"])[:150] == list(workflow)
    assert found["runs"] == 150
    assert "100 metrics over the 300 cap" in found["left_out"]


def test_says_nothing_when_no_run_in_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agent-runs" / "workflows").mkdir(parents=True)

    code, found = run_main(["--days", "7", "--root", str(tmp_path), "--today", TODAY], capsys)

    assert code == 0
    assert (found["days"], found["since"], found["until"]) == (7, "2026-10-15", TODAY)
    assert (found["runs"], found["nothing"], found["metrics"]) == (0, True, {})
    assert found["idle"] == {"skills": [], "agents": []}
    assert source(found, "runs") == {"name": "runs", "status": "ok", "reason": ""}
    assert "2026-10-15 .. 2026-10-22" in found["summary"]
    assert "nothing to change" in found["summary"]


def test_names_left_out_metrics_when_assembled() -> None:
    metrics = load()

    found = metrics.assemble([], days=7, since=SINCE, until=date(2026, 10, 22))

    assert found["left_out"] == [
        "per-workflow cost (not recorded per workflow yet)",
        "per-workflow numbers from the event store (folded here from the run records instead)",
        "guard denies from the event store (no command prints them;"
        " transcript blocks are counted instead)",
        "GitHub review rounds on PRs (scripts get no GitHub token;"
        " workflow review rounds are counted)",
    ]
    assert all(line in found["summary"] for line in found["left_out"])


@pytest.mark.parametrize("days", ["0", "91", "x"])
def test_exits_two_when_days_outside_one_to_ninety(
    days: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = load().main(["--days", days, "--root", str(tmp_path)])

    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "metrics.py: " in captured.err
