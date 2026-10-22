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


REPO = Path(__file__).resolve().parents[8]
FULL_GOLDEN = REPO / "packages/generator/tests/integration/golden/retro_metrics/full.golden"
TABLE_HEAD = (
    "Skills and agents: runs in the last 7 days, never used first.\n\n"
    "| Project | Kind | Name | 7 d | 30 d | 90 d | Last used |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)
SKILL_TABLE = TABLE_HEAD + (
    "| demo | skill | /refactor | 0 | 0 | 3 | 2026-08-01 |\n"
    "| demo | agent | evaluator | 0 | 1 | 1 | 2026-09-30 |\n"
    "| demo | skill | /feature | 2 | 5 | 9 | 2026-10-20 |\n"
)
MINING = (
    "# Transcript mining — last 7 days (2026-10-22)\n\n"
    "Sessions: 12 · cost (sessions with cost records): $34.5 · Stop-gate blocks: 3\n\n"
    "## Recurring tool errors (candidates for a hook, lint or AGENTS.md line)\n\n"
    "- 4× **Bash**: `secret reason text`\n\n"
    "## Guard / hook / permission blocks\n\n"
    "- 5× `denied: push to main by someone`\n"
    "- 2× `asked: edit docs/adr`\n\n"
    "## Bash commands failing repeatedly (first word)\n\n"
    "- 3× `make`\n"
)
EMPTY_REPORT = json.dumps(
    {"window": "", "prs": {}, "agent_runs": {"outcomes": {}, "cost_per_issue": {}}, "ci": {}}
)


def golden_stdout(path: Path) -> str:
    text = path.read_text()
    return text.split("--- stdout", 1)[1].split("---\n", 1)[1].split("\n--- stderr", 1)[0]


class FakeRunner:
    """Answers each command by its script or subcommand name; records the argv it got."""

    def __init__(self, answers: dict[str, tuple[int, str, str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        self.calls.append((argv, timeout))
        name = Path(argv[1] if argv[0] == "python3" else argv[0]).name
        return self.answers.get(name, (127, "", f"{name}: not found"))


def test_flattens_retro_metrics_when_report_complete() -> None:
    reading = load().parse_retro_metrics(0, golden_stdout(FULL_GOLDEN), "")

    assert reading.metrics == {
        "issue_runs.outcome.failed:verify": 2,
        "issue_runs.outcome.pr_opened": 5,
        "issue_runs.outcome.failed:check": 1,
        "issue_runs.cost_usd.TST-5": 2.0,
        "issue_runs.cost_usd.TST-1": 1.45,
        "issue_runs.cost_usd.TST-3": 0.3,
        "issue_runs.cost_usd.TST-2": 0.17,
        "issue_runs.cost_usd.TST-4": 0.0,
        "prs.acme/api.merged": 3,
        "prs.acme/api.median_cycle_h": 1.1,
        "prs.acme/api.agent_prs": 2,
        "prs.acme/api.agent_merged_without_edits": 1,
        "prs.acme/web.merged": 0,
        "prs.acme/web.agent_prs": 0,
        "prs.acme/web.agent_merged_without_edits": 0,
        "prs.acme/demo-hub.merged": 4,
        "prs.acme/demo-hub.median_cycle_h": 2.7,
        "prs.acme/demo-hub.agent_prs": 1,
        "prs.acme/demo-hub.agent_merged_without_edits": 1,
        "ci.acme/api.runs": 8,
        "ci.acme/api.failed": 6,
        "ci.acme/web.runs": 2,
        "ci.acme/web.failed": 1,
        "ci.acme/demo-hub.runs": 0,
        "ci.acme/demo-hub.failed": 0,
        "memory.inbox_pending": 2,
        "memory.learnings_added_or_changed": 3,
    }
    assert reading.sources == [
        {"name": "issue_runs", "status": "ok", "reason": ""},
        {"name": "github", "status": "ok", "reason": ""},
    ]


def test_drops_github_keys_when_gh_warning_printed() -> None:
    warning = "warning: gh pr list failed: HTTP 503: " + "-" * 300 + "\n"

    reading = load().parse_retro_metrics(0, golden_stdout(FULL_GOLDEN), warning * 3)

    assert not any(key.startswith("prs.") for key in reading.metrics)
    assert reading.metrics["ci.acme/api.runs"] == 8
    assert reading.metrics["issue_runs.outcome.pr_opened"] == 5
    [github] = [item for item in reading.sources if item["name"] == "github"]
    assert github["status"] == "missing"
    assert github["reason"].startswith("warning: gh pr list failed: HTTP 503")
    assert len(github["reason"]) == 200

    both = warning + "warning: gh run list failed: no network\n"
    reading = load().parse_retro_metrics(0, golden_stdout(FULL_GOLDEN), both)
    assert not any(key.startswith(("prs.", "ci.")) for key in reading.metrics)


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ((1, "", "hub.json: project.hub_repo and every repos[].github are required\n"), "exit 1: "),
        ((124, "", "timed out after 300 s"), "exit 124: timed out"),
        ((0, "Traceback? not json", ""), "not a JSON object"),
        ((0, "[1, 2]", ""), "not a JSON object"),
    ],
)
def test_marks_issue_runs_missing_when_retro_metrics_fails(
    answer: tuple[int, str, str], reason: str
) -> None:
    reading = load().parse_retro_metrics(*answer)

    assert reading.metrics == {}
    assert [item["status"] for item in reading.sources] == ["missing", "missing"]
    assert reading.sources[0]["name"] == "issue_runs"
    assert reading.sources[0]["reason"].startswith(reason)


def test_lists_idle_skills_when_skill_usage_table_parsed() -> None:
    reading = load().parse_skill_usage(0, SKILL_TABLE, "", days=7)

    assert reading.metrics == {
        "skills.idle": 1,
        "agents.idle": 1,
        "skill.refactor.runs_7d": 0,
        "agent.evaluator.runs_7d": 0,
        "skill.feature.runs_7d": 2,
    }
    assert reading.extras == {"skills": ["refactor"], "agents": ["evaluator"]}
    assert reading.sources == [{"name": "skill_usage", "status": "ok", "reason": ""}]

    wider = load().parse_skill_usage(0, SKILL_TABLE, "", days=90)
    assert wider.metrics["skill.refactor.runs_90d"] == 3
    assert wider.extras == {"skills": [], "agents": []}


@pytest.mark.parametrize(
    ("since", "window"), [(1, 7), (7, 7), (8, 30), (30, 30), (31, 90), (90, 90)]
)
def test_picks_smallest_window_covering_since_when_days_given(since: int, window: int) -> None:
    assert load().skill_window(since) == window


@pytest.mark.parametrize(
    ("rc", "out", "err"),
    [
        (2, "", "Error: No such command 'skill-usage'.\n"),
        (127, "", "./hub: not found"),
        (0, "no table here\n", ""),
    ],
)
def test_marks_skill_usage_missing_when_command_unknown(rc: int, out: str, err: str) -> None:
    reading = load().parse_skill_usage(rc, out, err, days=7)

    assert reading.metrics == {}
    assert reading.extras == {}
    assert reading.sources[0]["status"] == "missing"
    assert reading.sources[0]["reason"]


def test_marks_skill_usage_partial_when_not_read_line_printed() -> None:
    table = SKILL_TABLE + "| demo | skill | /odd | x | 1 | 1 | never |\n\n"
    table += "Some items were not read; the list may be incomplete.\n"

    reading = load().parse_skill_usage(0, table, "", days=7)

    assert reading.sources == [
        {
            "name": "skill_usage",
            "status": "partial",
            "reason": "some items were not read; 1 rows not parsed",
        }
    ]
    assert "skill.odd.runs_7d" not in reading.metrics
    assert reading.metrics["skill.feature.runs_7d"] == 2


def test_keeps_only_counts_when_transcript_report_parsed() -> None:
    reading = load().parse_mining(0, MINING, "")

    assert reading.metrics == {
        "transcripts.sessions": 12,
        "transcripts.cost_usd": 34.5,
        "transcripts.stop_gate_blocks": 3,
        "transcripts.guard_blocks": 7,
    }
    assert reading.sources == [{"name": "transcripts", "status": "ok", "reason": ""}]
    assert "push to main" not in json.dumps(reading)
    assert "secret reason" not in json.dumps(reading)

    missing = load().parse_mining(0, "# Transcript mining\n\nno counts\n", "")
    assert missing.metrics == {}
    assert missing.sources[0]["status"] == "missing"


def test_counts_issue_runs_in_runs_when_retro_metrics_has_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".agent-runs" / "workflows").mkdir(parents=True)
    report = json.dumps({"agent_runs": {"outcomes": {"pr_opened": 2}, "cost_per_issue": {}}})
    runner = FakeRunner(
        {
            "retro_metrics.py": (0, report, ""),
            "hub": (0, TABLE_HEAD, ""),
            "mine_transcripts.py": (0, MINING, ""),
        }
    )

    code = load().main(["--days", "8", "--root", str(tmp_path), "--today", TODAY], runner=runner)
    found = json.loads(capsys.readouterr().out)

    assert code == 0
    assert (found["runs"], found["nothing"]) == (2, False)
    assert [item["name"] for item in found["sources"]] == [
        "runs",
        "issue_runs",
        "github",
        "skill_usage",
        "transcripts",
    ]
    assert runner.calls == [
        (["python3", "scripts/retro_metrics.py", "--days", "8"], 300),
        (["./hub", "skill-usage", "--days", "30"], 120),
        (["python3", "scripts/mine_transcripts.py", "--days", "8"], 300),
    ]
    assert "lower bound" in found["summary"]


def test_exits_one_when_every_source_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = load().main(["--days", "7", "--root", str(tmp_path)], runner=FakeRunner({}))

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith("metrics.py: every source is missing")
