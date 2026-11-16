from datetime import timedelta
from decimal import Decimal

import pytest

from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.fold_run import fold_runs
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.read_model_builders import a_session
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    WORKFLOW_HASH,
    NodeVisit,
    a_run_events,
    a_workflow_run_events,
    as_stored,
    shuffled,
)
from agent_hub.core.workflows.ports import RunStatus


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


def test_derives_status_and_issue_to_pr_kinds_when_run_is_legacy() -> None:
    done = fold_runs(as_stored(a_run_events()))["1a2b3c4d"]
    failed = fold_runs(as_stored(a_run_events(fails=True)))["1a2b3c4d"]
    running = fold_runs(as_stored(a_run_events()[:5]))["1a2b3c4d"]

    assert (done.status, failed.status, running.status) == ("done", "failed", "running")
    assert [(step.key, step.kind) for step in done.steps] == [
        ("pick", None),
        ("worktree", "shell"),
        ("implement", "loop"),
        ("verify", "shell"),
        ("pr", "shell"),
    ]
    assert (done.outcome, done.revision, done.content_hash) == (None, None, None)
    assert failed.failure is not None
    assert failed.failure.failure_kind is None


def test_keeps_node_ids_and_causes_when_engine_run_fails() -> None:
    visits = [
        NodeVisit("build"),
        NodeVisit("review__lint", "failed", failure_kind="exec_failed"),
        NodeVisit("review__lint", "failed", failure_kind="exec_failed"),
        NodeVisit("deploy", "skipped", skip_cause="upstream_failed", origin="review__lint"),
    ]
    events = as_stored(a_workflow_run_events(visits, status="failed"))

    run = fold_runs(events)["5e6f7a8b"]

    assert [
        (step.key, step.attempt, step.status, step.failure_kind, step.skip_cause)
        for step in run.steps
    ] == [
        ("build", 1, "ok", None, None),
        ("review__lint", 1, "failed", "exec_failed", None),
        ("review__lint", 2, "failed", "exec_failed", None),
        ("deploy", 1, "skipped", None, "upstream_failed"),
    ]
    assert {step.kind for step in run.steps} == {None}
    assert run.steps[-1].reason == "review__lint"
    assert (run.workflow, run.status, run.stage) == ("ship", "failed", Stage.FAILED)
    assert (run.revision, run.content_hash) == (3, WORKFLOW_HASH)
    assert run.failure is not None
    assert (run.failure.stage, run.failure.failure_kind) == (Stage.FAILED, "exec_failed")
    assert run.failure.reason == "review__lint"
    assert (run.outcome, run.delivery) == (None, "failed")


def test_takes_highest_run_end_when_engine_run_resumed() -> None:
    first = a_workflow_run_events(
        [NodeVisit("build", "failed", failure_kind="config")], status="failed"
    )
    later = SCENARIO_START + timedelta(hours=1)
    ends = [a_workflow_run_events([], status="failed", end_index=n, start=later)[0] for n in (2, 9)]
    final = a_workflow_run_events([], status="done", outcome=True, end_index=10, start=later)
    final = [final[0].model_copy(update={"timestamp": later + timedelta(minutes=5)})]
    events = as_stored([*first, *ends, *final])

    for seed in range(10):
        run = fold_runs(shuffled(events, seed))["5e6f7a8b"]

        assert (run.status, run.outcome, run.failure) == ("done", True, None)
        assert run.ended_at == later + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("status", "outcome", "delivery"),
    [
        ("done", None, None),
        ("cancelled", None, None),
        ("failed", None, "failed"),
        ("done", False, None),
        ("done", "no_changes", "no_changes"),
    ],
)
def test_maps_outcome_by_status_when_engine_run_ends(
    status: RunStatus, *, outcome: bool | str | None, delivery: str | None
) -> None:
    visits = [NodeVisit("build", "failed" if status == "failed" else "ok")]
    events = as_stored(a_workflow_run_events(visits, status=status, outcome=outcome))

    run = fold_runs(events)["5e6f7a8b"]

    assert (run.status, run.outcome, run.delivery) == (status, outcome, delivery)
    assert run.stage == (Stage.FAILED if status == "failed" else Stage.REPORTED)
    assert (run.failure is None) == (status != "failed")


def test_derives_stage_and_kinds_when_engine_runs_issue_to_pr() -> None:
    visits = [NodeVisit("worktree"), NodeVisit("implement", "running")]
    running = a_workflow_run_events(visits, workflow="issue-to-pr")
    other = a_workflow_run_events(visits, run="9c0d1e2f", workflow="implement")
    visits = [NodeVisit("worktree"), NodeVisit("implement"), NodeVisit("pr"), NodeVisit("report")]
    done = a_workflow_run_events(
        visits, run="3a4b5c6d", workflow="issue-to-pr", status="done", outcome="delivered"
    )

    runs = fold_runs(as_stored([*running, *other, *done]))

    assert runs["5e6f7a8b"].stage == Stage.IMPLEMENTING
    assert [step.kind for step in runs["5e6f7a8b"].steps] == ["shell", "loop"]
    assert runs["9c0d1e2f"].stage == Stage.PICKED
    assert [step.kind for step in runs["9c0d1e2f"].steps] == [None, None]
    assert runs["3a4b5c6d"].steps[-1].kind == "shell"
    assert (runs["3a4b5c6d"].stage, runs["3a4b5c6d"].delivery) == (Stage.REPORTED, "delivered")


def test_keeps_pinned_document_when_run_starts_with_skipped_node() -> None:
    visits = [NodeVisit("gate", "skipped", skip_cause="condition"), NodeVisit("build")]
    events = as_stored(a_workflow_run_events(visits, status="done"))

    run = fold_runs(events)["5e6f7a8b"]

    assert (run.revision, run.content_hash) == (3, WORKFLOW_HASH)


def test_runs_again_when_engine_run_resumed_after_its_last_end() -> None:
    first = a_workflow_run_events([NodeVisit("build", "failed")], status="failed")
    later = SCENARIO_START + timedelta(hours=1)
    resumed = a_workflow_run_events([NodeVisit("deploy", "running")], start=later)
    ended = a_workflow_run_events(
        [], status="done", end_index=1, start=later + timedelta(minutes=5)
    )

    running = fold_runs(as_stored([*first, *resumed]))["5e6f7a8b"]
    done = fold_runs(as_stored([*first, *resumed, *ended]))["5e6f7a8b"]

    assert (running.status, running.ended_at, running.failure) == ("running", None, None)
    assert running.delivery is None
    assert (done.status, done.ended_at) == ("done", later + timedelta(minutes=5))
