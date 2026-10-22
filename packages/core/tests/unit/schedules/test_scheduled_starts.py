"""Scheduled and event starts (AGH-481): AC-1, AC-2 and AC-3 on the use case's ports."""

from datetime import UTC, datetime
from typing import Any

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.schedules.scheduled_starts import (
    EventQuery,
    EventRef,
    ScheduledHub,
    StartScheduledRuns,
)
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.schedule_fakes import (
    InMemoryStartLedger,
    RecordingRunStarter,
    ScriptedEventSource,
    StaticScheduledHubs,
)
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.launch import RunConflictError
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

HUB = "/hubs/demo"
WEEKLY = {"workflow": "retro", "cron": "0 9 * * 1", "inputs": {"days": 7}}
ON_MERGE = {"workflow": "verify", "on": "merge", "repo": "demo-api", "inputs": {"label": "x"}}
MERGES = EventQuery("merge", "acme/demo-api", "main")
SHA_A, SHA_B, SHA_C = "a" * 40, "b" * 40, "c" * 40


def a_workflow(name: str, **inputs: Any) -> WorkflowPlan:
    document = {
        "version": 1,
        "name": name,
        "revision": 1,
        "inputs": inputs,
        "nodes": [{"id": "work", "type": "shell", "command": ["true"]}],
    }
    return plan_workflow(parse_workflow(document))


class Plans:
    def __init__(self) -> None:
        self.plans = {
            "retro": a_workflow("retro", days={"type": "integer"}),
            "verify": a_workflow("verify", sha={"type": "string"}, label={"type": "string"}),
            "notes": a_workflow("notes", label={"type": "string"}),
        }

    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        if name not in self.plans:
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return HUB, self.plans[name]


class World:
    def __init__(self, **starts: list[dict[str, Any]]) -> None:
        document = a_hub_document()
        document.update(starts)
        self.hub = ScheduledHub("demo", HUB, HubConfig.model_validate(document))
        self.ledger = InMemoryStartLedger()
        self.events = ScriptedEventSource()
        self.start = RecordingRunStarter()

    def scheduler(self) -> StartScheduledRuns:
        """A fresh use case over the same ledger: what ``hub web`` builds at each start."""
        return StartScheduledRuns(
            hubs=StaticScheduledHubs(self.hub),
            plans=Plans(),
            ledger=self.ledger,
            events=self.events,
            start=self.start,
        )


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def merge(sha: str) -> EventRef:
    return EventRef(id=sha, data={"sha": sha})


def test_starts_one_schedule_run_then_none_when_ticked_twice_past_the_slot() -> None:
    world = World(schedules=[WEEKLY])
    scheduler = world.scheduler()

    first = scheduler.start_due_slots(at("2026-10-26T09:05"))
    second = scheduler.start_due_slots(at("2026-10-26T09:06"))

    assert [(run.workflow, run.trigger) for run in first.started] == [("retro", "schedule")]
    assert (first.failures, second.started, second.failures) == ((), (), ())
    [(request, trigger, environment)] = world.start.calls
    assert (request.project, request.workflow, dict(request.inputs)) == (
        "demo",
        "retro",
        {"days": 7},
    )
    assert (trigger, environment) == ("schedule", None)
    assert world.ledger.states[HUB].slots == {"retro": at("2026-10-26T09:00")}


def test_starts_one_schedule_run_when_hub_web_restarts_after_two_missed_slots() -> None:
    world = World(schedules=[WEEKLY])
    world.scheduler().start_due_slots(at("2026-10-26T09:05"))

    # Down from 2026-10-26 to 2026-11-10: the slots of 11-02 and 11-09 were missed.
    report = world.scheduler().start_due_slots(at("2026-11-10T08:00"))

    assert [run.workflow for run in report.started] == ["retro"]
    assert len(world.start.calls) == 2
    assert world.ledger.states[HUB].slots == {"retro": at("2026-11-09T09:00")}
    assert world.scheduler().start_due_slots(at("2026-11-10T08:01")).started == ()


def test_starts_nothing_when_schedule_slot_is_not_yet_due() -> None:
    world = World(schedules=[WEEKLY])
    world.scheduler().start_due_slots(at("2026-10-26T09:05"))

    report = world.scheduler().start_due_slots(at("2026-11-02T08:59"))

    assert report.started == ()
    assert len(world.start.calls) == 1


def test_records_slot_and_reports_failure_when_schedule_start_is_refused() -> None:
    world = World(schedules=[WEEKLY])
    world.start.refused["retro"] = RunConflictError(code="live_run", reason="the issue is busy")
    scheduler = world.scheduler()

    report = scheduler.start_due_slots(at("2026-10-26T09:05"))

    assert report.started == ()
    assert [(f.project, f.workflow, f.reason) for f in report.failures] == [
        ("demo", "retro", "the issue is busy")
    ]
    assert world.ledger.states[HUB].slots == {"retro": at("2026-10-26T09:00")}
    # At most once: the refused slot is not retried.
    assert scheduler.start_due_slots(at("2026-10-26T09:06")).failures == ()


def test_skips_hub_and_reports_failure_when_schedule_ledger_is_unreadable() -> None:
    world = World(schedules=[WEEKLY])
    world.ledger.unreadable.add(HUB)

    report = world.scheduler().start_due_slots(at("2026-10-26T09:05"))

    assert report.started == ()
    assert [(f.project, f.workflow) for f in report.failures] == [("demo", None)]
    assert world.start.calls == []


def test_leaves_ledger_untouched_when_hub_declares_no_schedule() -> None:
    world = World()
    world.ledger.unreadable.add(HUB)
    scheduler = world.scheduler()

    assert scheduler.start_due_slots(at("2026-10-26T09:05")).failures == ()
    assert world.ledger.writes == 0
