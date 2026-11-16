"""Scheduled and event starts (AGH-481): AC-1, AC-2 and AC-3 on the use case's ports."""

from datetime import UTC, datetime
from typing import Any

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.schedules.scheduled_starts import (
    EventPollError,
    EventQuery,
    EventRef,
    ScheduledHub,
    StartScheduledRuns,
    StartState,
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
            "triage": a_workflow("triage", pr={"type": "integer"}, ci_run={"type": "integer"}),
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
    assert scheduler.poll_events().failures == ()
    assert (world.ledger.writes, world.events.queries) == (0, [])


def test_records_baseline_and_starts_nothing_when_scheduler_polls_a_source_first() -> None:
    world = World(events=[ON_MERGE])
    world.events.answers[MERGES] = (merge(SHA_B), merge(SHA_A))

    report = world.scheduler().poll_events()

    assert (report.started, report.failures) == ((), ())
    assert world.events.queries == [MERGES]
    assert world.ledger.states[HUB].seen == {"verify merge demo-api": (SHA_B, SHA_A)}


def test_starts_one_event_run_with_merge_sha_when_scheduler_polls_a_new_merge() -> None:
    world = World(events=[ON_MERGE])
    world.events.answers[MERGES] = (merge(SHA_A),)
    scheduler = world.scheduler()
    scheduler.poll_events()
    world.events.answers[MERGES] = (merge(SHA_B), merge(SHA_A))

    report = scheduler.poll_events()

    assert [(run.workflow, run.trigger) for run in report.started] == [("verify", "event")]
    [(request, trigger, _)] = world.start.calls
    assert dict(request.inputs) == {"label": "x", "sha": SHA_B}
    assert trigger == "event"


def test_starts_none_twice_when_scheduler_sees_an_event_again() -> None:
    world = World(events=[ON_MERGE])
    world.events.answers[MERGES] = (merge(SHA_A),)
    world.scheduler().poll_events()
    world.events.answers[MERGES] = (merge(SHA_C), merge(SHA_B), merge(SHA_A))

    first = world.scheduler().poll_events()
    again = world.scheduler().poll_events()

    # One merge, one run, on its newest commit; each commit is recorded, across a restart.
    assert [request.inputs["sha"] for request, _, _ in world.start.calls] == [SHA_C]
    assert (len(first.started), again.started) == (1, ())
    assert world.ledger.states[HUB].seen["verify merge demo-api"] == (SHA_C, SHA_B, SHA_A)


def test_keeps_ledger_and_starts_nothing_when_scheduler_event_poll_fails() -> None:
    world = World(events=[ON_MERGE])
    world.events.answers[MERGES] = (merge(SHA_A),)
    world.scheduler().poll_events()
    world.events.answers[MERGES] = EventPollError("gh timed out")

    report = world.scheduler().poll_events()

    assert report.started == ()
    assert [(f.workflow, f.reason) for f in report.failures] == [
        ("verify", "event poll failed: verify merge demo-api: gh timed out")
    ]
    assert world.ledger.states[HUB] == StartState(seen={"verify merge demo-api": (SHA_A,)})
    assert world.start.calls == []


def test_passes_only_declared_event_inputs_when_scheduler_starts_an_event_run() -> None:
    world = World(events=[{**ON_MERGE, "workflow": "notes"}])
    query = MERGES
    world.events.answers[query] = ()
    world.scheduler().poll_events()
    world.events.answers[query] = (merge(SHA_A),)

    world.scheduler().poll_events()

    # notes declares no sha: the event offers it, the run does not get it.
    assert world.start.inputs() == [{"label": "x"}]


ON_PULL = {"workflow": "notes", "on": "pr_opened", "repo": "demo-api"}
ON_RED = {"workflow": "triage", "on": "ci_red", "repo": "demo-api"}
RED_KEY = "triage ci_red demo-api"
PULLS = EventQuery("pr_opened", "acme/demo-api", "main")
RED_RUNS = EventQuery("ci_red", "acme/demo-api", "main")
PULL_KEY = "notes pr_opened demo-api"


def pull(number: int) -> EventRef:
    return EventRef(id=str(number), data={"pr": number, "sha": SHA_A})


def test_starts_each_new_pull_request_oldest_first_when_scheduler_polls_pulls() -> None:
    world = World(events=[{**ON_PULL, "workflow": "triage"}])
    world.events.answers[PULLS] = (pull(7),)
    world.scheduler().poll_events()
    world.events.answers[PULLS] = (pull(9), pull(8), pull(7))

    first = world.scheduler().poll_events()
    again = world.scheduler().poll_events()

    assert world.start.inputs() == [{"pr": 8}, {"pr": 9}]
    assert (len(first.started), again.started) == (2, ())
    assert world.ledger.states[HUB].marks == {"triage pr_opened demo-api": 9}


def test_starts_nothing_when_an_older_unseen_pull_request_enters_the_schedule_page() -> None:
    world = World(events=[ON_PULL])
    world.events.answers[PULLS] = tuple(pull(number) for number in range(40, 20, -1))
    world.scheduler().poll_events()
    # PR 40 closed: PR 20, older than every recorded one, enters the page.
    world.events.answers[PULLS] = tuple(pull(number) for number in range(39, 19, -1))

    report = world.scheduler().poll_events()

    assert (report.started, world.start.calls) == ((), [])


def test_starts_nothing_when_a_known_pull_request_outlives_the_schedule_seen_window() -> None:
    world = World(events=[ON_PULL])
    world.events.answers[PULLS] = (pull(1),)
    world.scheduler().poll_events()
    # More than MAX_SEEN newer PRs came and went; PR 1 is still open and on the page.
    for newest in range(2, 2 + 150):
        world.events.answers[PULLS] = (pull(newest), pull(1))
        world.scheduler().poll_events()
    world.events.answers[PULLS] = (pull(1),)

    assert world.scheduler().poll_events().started == ()
    # One run per newer PR, none for PR 1, which the baseline recorded.
    assert len(world.start.calls) == 150


def red(run: int) -> EventRef:
    return EventRef(str(run), {"ci_run": run, "sha": SHA_B})


def test_starts_one_run_per_failed_run_above_the_floor_when_scheduler_polls_red_runs() -> None:
    world = World(events=[ON_RED])
    world.events.answers[RED_RUNS] = (EventRef("500", {"ci_run": 500, "sha": SHA_A}),)
    world.scheduler().poll_events()
    world.events.answers[RED_RUNS] = (
        EventRef("502", {"ci_run": 502, "sha": SHA_B}),
        EventRef("501", {"ci_run": 501, "sha": SHA_B}),
        EventRef("400", {"ci_run": 400, "sha": SHA_C}),
    )

    report = world.scheduler().poll_events()

    # One run per failed Actions run, oldest first, never one below the baseline's floor.
    assert len(report.started) == 2
    assert world.start.inputs() == [{"ci_run": 501}, {"ci_run": 502}]
    state = world.ledger.states[HUB]
    assert (state.marks, state.seen) == ({RED_KEY: 500}, {RED_KEY: ("502", "501", "500")})


def test_starts_a_red_run_that_failed_after_a_newer_one_when_scheduler_polls_red_runs() -> None:
    world = World(events=[ON_RED])
    world.events.answers[RED_RUNS] = (red(99),)
    world.scheduler().poll_events()
    # lint (101) fails first; tests (100), created before it, fails later.
    world.events.answers[RED_RUNS] = (red(101),)
    world.scheduler().poll_events()
    world.events.answers[RED_RUNS] = (red(101), red(100))

    world.scheduler().poll_events()

    assert world.start.inputs() == [{"ci_run": 101}, {"ci_run": 100}]


def test_raises_the_floor_when_red_run_ids_leave_the_schedule_seen_window() -> None:
    world = World(events=[ON_RED])
    world.events.answers[RED_RUNS] = (red(1),)
    world.scheduler().poll_events()
    for run in range(2, 2 + 150):
        world.events.answers[RED_RUNS] = (red(run), red(1))
        world.scheduler().poll_events()

    state = world.ledger.states[HUB]
    assert len(state.seen[RED_KEY]) == 100
    assert state.marks[RED_KEY] == 51
    assert len(world.start.calls) == 150


def test_drops_stale_pull_request_seen_ids_when_scheduler_writes_the_ledger() -> None:
    world = World(events=[ON_PULL])
    world.ledger.states[HUB] = StartState(seen={PULL_KEY: ("7",)}, marks={PULL_KEY: 7})
    world.events.answers[PULLS] = (pull(8), pull(7))

    world.scheduler().poll_events()

    assert world.ledger.states[HUB] == StartState(marks={PULL_KEY: 8})


def test_reports_failure_and_starts_the_next_when_a_schedule_start_raises() -> None:
    world = World(schedules=[WEEKLY, {"workflow": "notes", "cron": "0 9 * * 1"}])
    world.start.refused["retro"] = OSError("hub: no such file")

    report = world.scheduler().start_due_slots(at("2026-10-26T09:05"))

    assert [run.workflow for run in report.started] == ["notes"]
    assert [(f.workflow, f.reason) for f in report.failures] == [
        ("retro", "the run could not start (OSError)")
    ]


def test_keeps_failed_source_while_another_updates_when_scheduler_polls_two_sources() -> None:
    world = World(events=[ON_MERGE, ON_PULL])
    world.events.answers[MERGES] = (merge(SHA_A),)
    world.events.answers[PULLS] = (pull(7),)
    world.scheduler().poll_events()
    world.events.answers[MERGES] = EventPollError("gh timed out")
    world.events.answers[PULLS] = (pull(8), pull(7))

    report = world.scheduler().poll_events()

    assert [run.workflow for run in report.started] == ["notes"]
    state = world.ledger.states[HUB]
    assert state.seen == {"verify merge demo-api": (SHA_A,)}
    assert state.marks == {PULL_KEY: 8}


def test_drops_undeclared_entries_when_schedule_and_event_are_removed() -> None:
    world = World(schedules=[WEEKLY], events=[ON_MERGE, ON_PULL])
    world.events.answers[MERGES] = (merge(SHA_A),)
    world.events.answers[PULLS] = (pull(7),)
    world.scheduler().start_due_slots(at("2026-10-26T09:05"))
    world.scheduler().poll_events()
    trimmed = World(schedules=[{"workflow": "notes", "cron": "0 9 * * 1"}], events=[ON_PULL])
    trimmed.ledger, trimmed.events = world.ledger, world.events

    trimmed.scheduler().start_due_slots(at("2026-10-26T09:06"))
    trimmed.scheduler().poll_events()

    state = world.ledger.states[HUB]
    assert set(state.slots) == {"notes"}
    assert (state.seen, state.marks) == ({}, {PULL_KEY: 7})
