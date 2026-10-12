"""Synthetic ``.agent-runs/*.jsonl`` records of ``hub run`` for tests, made with ``run_record``.

Each builder returns the records of one run in the order ``hub run`` writes them, one second
apart, with made-up ids, issue and costs.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.run_record import Stage, picked_data, reported_data, run_record

RUN_START: Final = datetime(2026, 10, 11, 9, 0, 0, tzinfo=UTC)
RUN_PR_URL: Final = "https://github.com/acme/demo-api/pull/7"

type Record = dict[str, JsonValue]


class _RunWriter:
    def __init__(self, run_id: str, *, issue: str, repo: str) -> None:
        self.run_id = run_id
        self.issue = issue
        self.repo = repo
        self.records: list[Record] = []

    def add(self, state: Stage, event: str, data: dict[str, JsonValue] | None = None) -> None:
        moment = RUN_START + timedelta(seconds=len(self.records))
        self.records.append(
            run_record(
                ts=moment.isoformat(timespec="seconds"),
                run_id=self.run_id,
                issue_id=self.issue,
                repo=self.repo,
                state=state,
                event=event,
                live=True,
                data=data or {},
            )
        )

    def start(self) -> None:
        self.add(
            Stage.PICKED,
            "picked",
            picked_data(budget=10.0, max_turns=80, model="opus", transport="api"),
        )
        self.add(Stage.WORKTREE, "worktree_ready", {"path": "/work/demo-api/.claude/worktrees/x"})

    def implement(self) -> None:
        self.add(
            Stage.IMPLEMENTING,
            "agent_finished",
            {"cost_usd": 1.5, "turns": 12, "subtype": "success", "verdict": None},
        )
        self.add(Stage.IMPLEMENTING, "commits", {"commits": ["feat: export button (DEM-7)"]})


def run_lines_picked_to_reported(
    run_id: str = "1a2b3c4d", *, issue: str = "DEM-7", repo: str = "demo-api"
) -> list[Record]:
    """A run that goes PICKED to REPORTED and opens its PR."""
    writer = _RunWriter(run_id, issue=issue, repo=repo)
    writer.start()
    writer.implement()
    writer.add(Stage.VERIFYING, "gate_ok", {"gate": "make check"})
    writer.add(Stage.PR_OPEN, "pr_open", {"url": RUN_PR_URL})
    writer.add(
        Stage.REPORTED,
        "reported",
        reported_data(ok=True, failed_stage=None, total_cost_usd=1.75, pr=RUN_PR_URL),
    )
    return writer.records


def run_lines_failed_in_verify(
    loops: int = 2, run_id: str = "5e6f7a8b", *, issue: str = "DEM-8", repo: str = "demo-api"
) -> list[Record]:
    """A run that implements and fails its gate ``loops`` times, then reports the failure."""
    writer = _RunWriter(run_id, issue=issue, repo=repo)
    writer.start()
    reason = "gate failed: make check\nFAILED tests/test_app.py::test_export - assert 1 == 2"
    for _ in range(loops):
        writer.implement()
        writer.add(Stage.VERIFYING, "failed", {"stage": Stage.VERIFYING.value, "reason": reason})
    writer.add(
        Stage.REPORTED,
        "reported",
        reported_data(ok=True, failed_stage=Stage.VERIFYING, total_cost_usd=3.0, pr=""),
    )
    return writer.records
