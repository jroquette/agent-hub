"""``ScheduledStartsRuntime`` (AGH-481): hub web's tick for scheduled and event starts."""

import asyncio
import logging
from datetime import UTC, datetime

import pytest

from agent_hub.api.scheduled_starts_runtime import ScheduledStartsRuntime
from agent_hub.core.schedules.scheduled_starts import StartedRun, StartFailure, StartReport

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 26, 9, 5, tzinfo=UTC)


class FakeStarts:
    """Counts each call; ``failing`` ticks raise first."""

    def __init__(self, *, failing: int = 0) -> None:
        self.slots: list[datetime] = []
        self.polls = 0
        self.failing = failing

    def start_due_slots(self, now: datetime) -> StartReport:
        self.slots.append(now)
        if self.failing:
            self.failing -= 1
            msg = "the tick failed"
            raise RuntimeError(msg)
        started = StartedRun(project="demo", workflow="retro", run_id="r1", trigger="schedule")
        return StartReport(started=(started,))

    def poll_events(self) -> StartReport:
        self.polls += 1
        failure = StartFailure(project="demo", workflow="verify", reason="gh timed out")
        return StartReport(failures=(failure,))


class Ticks:
    """A monotonic clock moved by the test."""

    def __init__(self) -> None:
        self.at = 0.0

    def __call__(self) -> float:
        return self.at


async def _ticks(starts: FakeStarts, count: int) -> None:
    async with asyncio.timeout(5):
        while len(starts.slots) < count:
            await asyncio.sleep(0.001)


async def test_ticks_at_start_then_polls_once_per_five_minutes_when_scheduler_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    starts, ticks = FakeStarts(), Ticks()
    runtime = ScheduledStartsRuntime(starts, clock=lambda: NOW, tick_seconds=3600, monotonic=ticks)
    caplog.set_level(logging.INFO)

    await runtime.start()
    async with asyncio.timeout(5):
        # The first tick ends with its poll's log: stopping earlier would cancel it midway.
        while not any("failed" in record.getMessage() for record in caplog.records):
            await asyncio.sleep(0.001)
    await runtime.stop()
    for at in (60.0, 240.0, 300.0, 360.0):
        ticks.at = at
        await runtime.tick()

    # A tick at start (a missed slot runs then), and a poll at 0 s and at 300 s only.
    assert (starts.slots, starts.polls) == ([NOW] * 5, 2)
    messages = [record.getMessage() for record in caplog.records]
    assert "scheduled run started: demo retro r1 (schedule)" in messages
    assert "scheduled start failed: demo verify: gh timed out" in messages


async def test_keeps_ticking_when_a_schedule_tick_raises() -> None:
    starts = FakeStarts(failing=1)
    runtime = ScheduledStartsRuntime(
        starts, clock=lambda: NOW, tick_seconds=0.001, monotonic=Ticks()
    )

    await runtime.start()
    await _ticks(starts, 2)
    await runtime.stop()

    assert len(starts.slots) >= 2


async def test_ignores_exit_when_scheduler_never_started() -> None:
    runtime = ScheduledStartsRuntime(FakeStarts(), clock=lambda: NOW)

    runtime.begin_exit()
    await runtime.stop()


async def test_logs_the_start_error_when_a_scheduled_start_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = OSError(2, "No such file or directory")
    failure = StartFailure(
        project="demo", workflow="retro", reason="the run could not start (OSError)", error=error
    )

    class RaisingStarts(FakeStarts):
        def start_due_slots(self, now: datetime) -> StartReport:
            return StartReport(failures=(failure,))

    runtime = ScheduledStartsRuntime(RaisingStarts(), clock=lambda: NOW, monotonic=Ticks())
    caplog.set_level(logging.INFO)

    await runtime.tick()

    [record] = [r for r in caplog.records if "retro" in r.getMessage()]
    assert record.exc_info is not None
    assert record.exc_info[1] is error
