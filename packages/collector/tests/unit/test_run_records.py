"""``hub run`` records to executor events (D8, D9, E7): stages, loops, ids and the run's end."""

from typing import Any

import pytest

from agent_hub.collector.run_records import (
    RunEventMapper,
    RunRecordError,
    map_run_records,
)
from agent_hub.core.events.event import Event
from agent_hub.core.events.payload_keys import kept_payload
from agent_hub.core.testing.run_lines import (
    RUN_PR_URL,
    run_lines_failed_in_verify,
    run_lines_picked_to_reported,
)


def _steps(events: list[Event]) -> list[tuple[str, str | None, Any, Any]]:
    return [
        (event.type, event.step, event.payload.get("attempt"), event.payload.get("status"))
        for event in events
        if event.type in {"step.start", "step.end"}
    ]


def test_starts_and_ends_each_stage_when_run_goes_picked_to_reported_stages() -> None:
    events = list(map_run_records(run_lines_picked_to_reported(), project="demo"))

    assert _steps(events) == [
        ("step.start", "pick", 1, None),
        ("step.end", "pick", 1, "ok"),
        ("step.start", "worktree", 1, None),
        ("step.end", "worktree", 1, "ok"),
        ("step.start", "implement", 1, None),
        ("step.end", "implement", 1, "ok"),
        ("step.start", "verify", 1, None),
        ("step.end", "verify", 1, "ok"),
        ("step.start", "pr", 1, None),
        ("step.end", "pr", 1, "ok"),
    ]
    assert {event.session for event in events} == {"run:1a2b3c4d"}
    assert {event.source for event in events} == {"executor"}
    assert {event.workflow for event in events} == {"issue-to-pr"}
    assert {event.project for event in events} == {"demo"}
    assert {event.repo for event in events} == {"demo-api"}


def test_carries_caps_and_mode_when_run_picked_stages() -> None:
    [pick] = [
        e for e in map_run_records(run_lines_picked_to_reported(), project="d") if e.step == "pick"
    ][:1]

    assert pick.payload == {
        "run": "1a2b3c4d",
        "issue": "DEM-7",
        "repo": "demo-api",
        "stage": "PICKED",
        "attempt": 1,
        "mode": "live",
        "caps": {"budget": 10.0, "max_turns": 80, "model": "opus", "transport": "api"},
    }


def test_records_passed_gate_when_gate_ok_stages() -> None:
    [gate] = [
        e
        for e in map_run_records(run_lines_picked_to_reported(), project="d")
        if e.type == "gate.result"
    ]

    assert gate.step == "verify"
    assert gate.payload == {
        "run": "1a2b3c4d",
        "issue": "DEM-7",
        "repo": "demo-api",
        "gate_id": "1a2b3c4d:verify:1",
        "kind": "check",
        "command": "make check",
        "result": "passed",
        "attempt": 1,
        "mode": "live",
    }


def test_ends_run_done_with_pr_and_cost_when_reported() -> None:
    [end] = [
        e
        for e in map_run_records(run_lines_picked_to_reported(), project="d")
        if e.type == "run.end"
    ]

    assert end.step is None
    assert end.payload == {
        "run": "1a2b3c4d",
        "issue": "DEM-7",
        "repo": "demo-api",
        "status": "done",
        "pr_url": RUN_PR_URL,
        "cost_usd": 1.75,
        "mode": "live",
    }


def test_ends_run_failed_with_stage_and_reason_when_reported_after_failure() -> None:
    [end] = [
        e for e in map_run_records(run_lines_failed_in_verify(), project="d") if e.type == "run.end"
    ]

    assert end.payload["status"] == "failed"
    assert end.payload["stage"] == "VERIFYING"
    assert end.payload["reason"] == "gate failed: make check"
    assert "pr_url" not in end.payload


def test_ends_run_failed_when_tracker_report_failed_reported() -> None:
    records = run_lines_picked_to_reported()
    records[-1]["ok"] = False

    [end] = [e for e in map_run_records(records, project="d") if e.type == "run.end"]

    assert end.payload["status"] == "failed"


def test_counts_attempts_when_run_loops_through_verify_loop() -> None:
    events = list(map_run_records(run_lines_failed_in_verify(loops=2), project="demo"))

    assert _steps(events) == [
        ("step.start", "pick", 1, None),
        ("step.end", "pick", 1, "ok"),
        ("step.start", "worktree", 1, None),
        ("step.end", "worktree", 1, "ok"),
        ("step.start", "implement", 1, None),
        ("step.end", "implement", 1, "ok"),
        ("step.start", "verify", 1, None),
        ("step.end", "verify", 1, "failed"),
        ("step.start", "implement", 2, None),
        ("step.end", "implement", 2, "ok"),
        ("step.start", "verify", 2, None),
        ("step.end", "verify", 2, "failed"),
    ]
    failed = [e for e in events if e.payload.get("status") == "failed" and e.type == "step.end"]
    assert failed[0].payload["reason"] == "gate failed: make check"
    assert "FAILED tests" not in failed[0].model_dump_json()


def test_makes_unique_source_ids_when_one_record_yields_several_events_source_id() -> None:
    records = run_lines_failed_in_verify(loops=1)

    events = list(map_run_records(records, project="d"))

    ids = [event.source_id for event in events]
    assert len(ids) == len(set(ids))
    failed = records[-2]
    prefix = f"{failed['run']}:{failed['state']}:{failed['event']}:{failed['ts']}"
    assert [i for i in ids if i.startswith(prefix)] == [
        f"{prefix}:step.end:implement",
        f"{prefix}:step.start:verify",
        f"{prefix}:step.end:verify",
    ]


def test_maps_same_events_when_records_fed_one_by_one_source_id() -> None:
    records = run_lines_picked_to_reported() + run_lines_failed_in_verify()
    mapper = RunEventMapper(project="demo")

    one_by_one = [event for record in records for event in mapper.map(record)]

    assert one_by_one == list(map_run_records(records, project="demo"))


def test_keeps_runs_apart_when_records_interleave_stages() -> None:
    first = run_lines_picked_to_reported("aaaa1111")
    second = run_lines_picked_to_reported("bbbb2222")
    interleaved = [record for pair in zip(first, second, strict=True) for record in pair]

    events = list(map_run_records(interleaved, project="d"))

    for run in ("aaaa1111", "bbbb2222"):
        mine = [e for e in events if e.session == f"run:{run}"]
        assert len([e for e in mine if e.type == "step.start"]) == 5


def test_marks_dry_run_when_record_not_live_stages() -> None:
    records = run_lines_picked_to_reported()
    for record in records:
        record["live"] = False

    events = map_run_records(records, project="d")

    assert {event.payload["mode"] for event in events if "mode" in event.payload} == {"dry_run"}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"ts": "yesterday"}, "ts"),
        ({"ts": "2026-10-11T09:00:00"}, "ts"),
        ({"run": ""}, "run"),
        ({"run": "r" * 197}, "run: longer than 196 characters"),
        ({"state": "DANCING"}, "state"),
        ({"event": 3}, "event"),
    ],
)
def test_rejects_record_when_field_invalid(change: dict[str, Any], reason: str) -> None:
    record = run_lines_picked_to_reported()[0] | change

    with pytest.raises(RunRecordError, match=reason):
        RunEventMapper(project="d").map(record)


def test_maps_only_payload_kept_keys_when_runs_succeed_and_fail() -> None:
    events = [
        *map_run_records(run_lines_picked_to_reported(), project="demo"),
        *map_run_records(run_lines_failed_in_verify(), project="demo"),
    ]

    assert {event.type for event in events} >= {"step.start", "step.end", "gate.result", "run.end"}
    for event in events:
        assert kept_payload(event.type, event.payload) == event.payload, event.type
