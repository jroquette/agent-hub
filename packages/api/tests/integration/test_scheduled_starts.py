"""Scheduled and event starts through hub web's parts (AGH-481, AC-1 to AC-3): a hub folder with
``schedules`` and ``events`` and a workflow pack, the file ledger, the real ``StartWorkflowRun``
over a recording launcher, a scripted event source and a fake clock."""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.composition import workflow_source_of
from agent_hub.api.scheduled_starts_runtime import ScheduledStartsRuntime
from agent_hub.api.start_ledger import FileStartLedger
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.schedules.scheduled_starts import (
    EventQuery,
    EventRef,
    ScheduledHub,
    StartScheduledRuns,
)
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.schedule_fakes import ScriptedEventSource
from agent_hub.core.workflows.launch import LaunchSpec, RunGuard, StartWorkflowRun
from agent_hub.core.workflows.workflow_reads import ReadWorkflows

pytestmark = pytest.mark.anyio

WORKFLOW = """\
version: 1
name: {name}
revision: 1
inputs:
  sha:
    type: string
  days:
    type: integer
nodes:
  - id: work
    type: shell
    command: ["true"]
"""
MERGES = EventQuery("merge", "acme/demo-api", "main")
SHA_A, SHA_B = "a" * 40, "b" * 40


class Hubs:
    def __init__(self, hub: ScheduledHub) -> None:
        self.hub = hub

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [(self.hub.project, self.hub.hub_path)]

    def scheduled_hubs(self) -> Iterable[ScheduledHub]:
        return [self.hub]


class RecordingLauncher:
    def __init__(self) -> None:
        self.specs: list[LaunchSpec] = []

    def start(self, spec: LaunchSpec) -> None:
        self.specs.append(spec)

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        return {}


class Clock:
    def __init__(self, text: str) -> None:
        self.now = datetime.fromisoformat(text).replace(tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class World:
    def __init__(self, tmp_path: Path) -> None:
        document = a_hub_document()
        document["schedules"] = [{"workflow": "retro", "cron": "0 9 * * 1", "inputs": {"days": 7}}]
        document["events"] = [{"workflow": "verify", "on": "merge", "repo": "demo-api"}]
        hub = tmp_path / "demo-hub"
        for name in ("retro", "verify"):
            pack = hub / "workflows" / "demo" / f"{name}.yaml"
            pack.parent.mkdir(parents=True, exist_ok=True)
            pack.write_text(WORKFLOW.format(name=name))
        (hub / "hub.json").write_text(json.dumps(document))
        self.hub_path = str(hub)
        self.hubs = Hubs(ScheduledHub("demo", self.hub_path, HubConfig.model_validate(document)))
        self.launcher = RecordingLauncher()
        self.events = ScriptedEventSource()
        self.clock = Clock("2026-10-26T09:05")

    def runtime(self) -> ScheduledStartsRuntime:
        """What ``hub web`` builds at each start, over the same hub folder."""
        workflows = ReadWorkflows(self.hubs, workflow_source_of)
        guard = RunGuard(runs=None, launcher=self.launcher)  # type: ignore[arg-type]
        starts = StartScheduledRuns(
            hubs=self.hubs,
            plans=workflows,
            ledger=FileStartLedger(),
            events=self.events,
            start=StartWorkflowRun(workflows, guard),
        )
        return ScheduledStartsRuntime(starts, clock=self.clock, monotonic=lambda: 0.0)

    def started(self) -> list[tuple[str, Any, str | None]]:
        return [(spec.workflow, dict(spec.inputs), spec.trigger) for spec in self.launcher.specs]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


async def test_starts_one_schedule_run_then_none_when_hub_web_ticks_twice(world: World) -> None:
    runtime = world.runtime()

    await runtime.tick()
    world.clock.now = world.clock.now.replace(minute=6)
    await runtime.tick()

    assert world.started() == [("retro", {"days": 7}, "schedule")]
    assert world.launcher.specs[0].hub_path == world.hub_path


async def test_starts_one_schedule_run_when_restarted_across_two_slots(world: World) -> None:
    await world.runtime().tick()
    world.clock.now = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)

    await world.runtime().tick()
    await world.runtime().tick()

    assert world.started() == [("retro", {"days": 7}, "schedule")] * 2


async def test_starts_one_event_run_with_merge_sha_when_hub_web_polls_after_baseline(
    world: World,
) -> None:
    world.events.answers[MERGES] = (EventRef(SHA_A, {"sha": SHA_A}),)
    await world.runtime().tick()
    world.events.answers[MERGES] = (
        EventRef(SHA_B, {"sha": SHA_B}),
        EventRef(SHA_A, {"sha": SHA_A}),
    )

    await world.runtime().tick()
    await world.runtime().tick()

    events = [run for run in world.started() if run[2] == "event"]
    assert events == [("verify", {"sha": SHA_B}, "event")]
