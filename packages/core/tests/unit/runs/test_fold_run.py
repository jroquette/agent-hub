from datetime import timedelta
from decimal import Decimal

import pytest

from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.fold_run import fold_runs
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.read_model_builders import a_session
from agent_hub.core.testing.session_scenarios import a_run_events, as_stored, shuffled


def test_keys_steps_by_step_and_attempt_when_verify_loops_and_fails() -> None:
    events = as_stored(a_run_events(loops=1, fails=True))

    run = fold_runs(events)["1a2b3c4d"]

    assert [(step.key, step.attempt, step.status) for step in run.steps] == [
        ("pick", 1, "ok"),
        ("worktree", 1, "ok"),
        ("implement", 1, "ok"),
        ("verify", 1, "failed"),
        ("implement", 2, "ok"),
        ("verify", 2, "failed"),
    ]
    verify = [step for step in run.steps if step.key == "verify"]
    assert {step.max_attempts for step in verify} == {2}
    assert run.stage == Stage.FAILED
    assert run.failure is not None
    assert run.failure.stage == Stage.VERIFYING
    assert run.failure.reason == "check failed: make check"
    failing = [item for item in events if item.event_id == run.failure.failing_event_id]
    assert failing[0].event.type == "step.end"
    assert failing[0].event.payload["attempt"] == 2
    assert run.issue is not None
    assert run.issue.key == "DEM-7"
    assert run.cost_usd == Decimal("1.25")
    assert run.cost_source == "executor"
    assert run.ended_at == events[-1].event.timestamp


def test_ignores_second_run_end_when_it_arrives_later() -> None:
    events = a_run_events(fails=True)
    late = events[-1].model_copy(
        update={
            "source_id": "late",
            "timestamp": events[-1].timestamp + timedelta(minutes=3),
            "payload": dict(events[-1].payload) | {"status": "done", "pr_url": "https://x/1"},
        }
    )

    run = fold_runs(as_stored([late, *events]))["1a2b3c4d"]

    assert run.stage == Stage.FAILED
    assert run.pr_url is None
    assert run.ended_at == events[-1].timestamp


def test_reports_run_with_caps_and_pr_when_run_succeeds() -> None:
    run = fold_runs(as_stored(a_run_events()))["1a2b3c4d"]

    assert run.stage == Stage.REPORTED
    assert run.failure is None
    assert run.mode == "live"
    assert run.caps is not None
    assert (run.caps.budget_usd, run.caps.max_turns, run.caps.model) == (Decimal(10), 80, "opus")
    assert run.caps.tracker_transport == "api"
    assert run.pr_url == "https://github.com/acme/demo-api/pull/7"
    assert run.workflow == "issue-to-pr"
    assert run.repo == "demo-api"


@pytest.mark.parametrize(
    "pr_url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "http://github.com/acme/demo-api/pull/7",
        "//evil.example/pull/7",
        "https://",
        "https://[::1/pull/7",
        " https://github.com/acme/demo-api/pull/7",
        "https://github.com/acme/demo-api/pull/7\nx",
    ],
)
def test_drops_pr_url_when_it_is_not_an_https_url(pr_url: str) -> None:
    events = a_run_events()
    end = events[-1].model_copy(update={"payload": dict(events[-1].payload) | {"pr_url": pr_url}})

    run = fold_runs(as_stored([*events[:-1], end]))["1a2b3c4d"]

    assert run.stage == Stage.REPORTED
    assert run.pr_url is None


def test_shows_latest_stage_running_when_run_in_flight() -> None:
    events = a_run_events()[:5]

    run = fold_runs(as_stored(events))["1a2b3c4d"]

    assert run.stage == Stage.IMPLEMENTING
    assert run.steps[-1].status == "running"
    assert run.ended_at is None


def test_fails_at_stage_when_failed_step_has_no_run_end_yet() -> None:
    events = a_run_events(fails=True)[:-1]

    run = fold_runs(as_stored(events))["1a2b3c4d"]

    assert run.stage == Stage.FAILED
    assert run.failure is not None
    assert run.failure.stage == Stage.VERIFYING


def test_sums_session_costs_and_links_sessions_when_sessions_given() -> None:
    sessions = {
        "s-1": a_session(id="s-1", run_id="1a2b3c4d", step="implement", attempt=1),
        "s-2": a_session(
            id="s-2", run_id="1a2b3c4d", step="implement", attempt=2, cost_usd=Decimal("0.5")
        ),
        "s-3": a_session(id="s-3", run_id="other"),
    }

    run = fold_runs(as_stored(a_run_events(loops=1)), sessions=sessions)["1a2b3c4d"]

    assert run.cost_usd == Decimal("0.0412") + Decimal("0.5")
    assert run.cost_source == "sessions"
    assert run.session_ids == ("s-1", "s-2")
    implement = [step for step in run.steps if step.key == "implement"]
    assert [step.session_ids for step in implement] == [("s-1",), ("s-2",)]


def test_lists_gate_results_when_executor_ran_gates() -> None:
    gate = an_event(
        type="gate.result",
        source="executor",
        session="run:1a2b3c4d",
        payload={"run": "1a2b3c4d", "result": "passed", "command": "make check", "exit_code": 0},
    )

    run = fold_runs(as_stored([*a_run_events(), gate]))["1a2b3c4d"]

    assert [(gate.result, gate.command, gate.exit_code) for gate in run.gate_results] == [
        ("passed", "make check", 0)
    ]


def test_folds_same_run_when_events_shuffled_with_duplicates() -> None:
    events = as_stored(a_run_events(loops=2, fails=True))
    expected = fold_runs(events)

    for seed in range(30):
        assert fold_runs(shuffled([*events, *events[:4]], seed)) == expected


def test_never_creates_run_when_only_session_events_exist() -> None:
    assert fold_runs(as_stored([an_event()])) == {}


@pytest.mark.parametrize(
    ("fails", "delivery"), [(False, "delivered"), (True, "failed")], ids=["pr", "failure"]
)
def test_derives_delivery_when_run_end_has_no_outcome(*, fails: bool, delivery: str) -> None:
    run = fold_runs(as_stored(a_run_events(fails=fails)))["1a2b3c4d"]

    assert run.delivery == delivery
    assert run.delivery_reason is None


def test_takes_delivery_from_outcome_when_run_end_names_one() -> None:
    events = a_run_events()
    end = events[-1].model_copy(
        update={"payload": dict(events[-1].payload) | {"status": "failed", "outcome": "delivered"}}
    )

    run = fold_runs(as_stored([*events[:-1], end]))["1a2b3c4d"]

    assert run.delivery == "delivered"
    assert run.failure is not None


@pytest.mark.parametrize("outcome", ["no_changes", "blocked"])
def test_ends_reported_without_failure_when_run_not_delivered(outcome: str) -> None:
    events = a_run_events()
    payload = {key: value for key, value in events[-1].payload.items() if key != "pr_url"} | {
        "status": "done",
        "outcome": outcome,
        "reason": "no commit on the branch",
    }
    end = events[-1].model_copy(update={"payload": payload})

    run = fold_runs(as_stored([*events[:-1], end]))["1a2b3c4d"]

    assert run.stage == Stage.REPORTED
    assert run.failure is None
    assert run.pr_url is None
    assert (run.delivery, run.delivery_reason) == (outcome, "no commit on the branch")


def test_leaves_delivery_unset_when_run_in_flight() -> None:
    run = fold_runs(as_stored(a_run_events()[:5]))["1a2b3c4d"]

    assert run.delivery is None
