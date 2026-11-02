"""The ticket warmer of ``hub web`` (AGH-613, AC-34, A10): while a tab holds the global stream
open and a Linear key is set, a background part reads a feature's tickets into the cache when its
snapshot is missing or 14 min old, within the cache's 60 s holds, and pauses after a rate-limit
answer; with no key, no tab or the MCP transport it reads nothing.

Seam: ``build_app(..., warm_ticker=)``, driven through ``manual_tickers["warm_ticker"]`` (a
``ManualTicker``; its ``wake()`` counts the calls in ``wakes``, as ``stop()`` counts in
``stops``), ``Composed.browsers`` (the app's ``ConnectedBrowsers``) and ``Composed.warm()`` (one
warm tick on the caller's thread). Linear is ``CountingTrackerReader`` over the seeded board
(``build_app(tracker_reader=)``) with a synthetic ``LINEAR_API_KEY`` in the injected environment;
the app's clock is moved by the test. ``ListingReader`` is ``HubFileSystem`` recording each
feature folder listing. No sleep, not ``serial``.
"""

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.settings import ApiSettings
from agent_hub.core.errors import TrackerError, TrackerFailure
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)
from agent_hub.generator.registered_hub_files import HubFileSystem

START = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
OWN = {"Origin": "http://127.0.0.1:7420"}
# The two features naming tickets, by folder, and the issue each names: one read of its ids.
FEATURES = {"alpha": "DEM-1", "beta": "DEM-3"}
EACH_FEATURE = [("DEM-1",), ("DEM-3",)]


class MovableClock:
    """The app's clock: ``START`` until the test moves it."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def at(self, seconds: float) -> None:
        self.now = START + timedelta(seconds=seconds)


class ListingReader(HubFileSystem):
    """``HubFileSystem`` that records the hub path of each feature folder listing."""

    def __init__(self) -> None:
        super().__init__()
        self.listed: list[str] = []

    def feature_folders(self, hub_path: str) -> Any:
        self.listed.append(hub_path)
        return super().feature_folders(hub_path)


def _tracker_error(kind: TrackerFailure, status: int) -> TrackerError:
    return TrackerError(
        operation="issue_summaries",
        cause=f"synthetic {kind} answer",
        fix="nothing to fix: a test fake",
        kind=kind,
        http_status=status,
    )


@dataclass
class WarmWorld:
    """The composed app over a registered hub with ``FEATURES``, and what the test drives."""

    clock: MovableClock
    files: ListingReader
    # Raised by the tracker reads, one per read, while any is left.
    failures: Iterator[TrackerError]
    composed: Any = None
    reader: Any = None
    # When each read reached the reader, in seconds after ``START``, in call order.
    read_at: list[float] = field(default_factory=list)

    def on_read(self) -> None:
        self.read_at.append((self.clock.now - START).total_seconds())
        failure = next(self.failures, None)
        if failure is not None:
            raise failure

    def tick_at(self, seconds: float) -> int:
        """One warm tick at ``START`` + ``seconds``; how many tracker reads it made."""
        self.clock.at(seconds)
        before = self.reader.count
        self.composed.warm()
        return int(self.reader.count - before)

    def reads(self) -> dict[tuple[str, ...], list[float]]:
        """Each feature's read times (its ids: the times, in seconds after ``START``)."""
        found: dict[tuple[str, ...], list[float]] = {}
        for ids, seconds in zip(self.reader.calls, self.read_at, strict=True):
            found.setdefault(ids, []).append(seconds)
        return found


@pytest.fixture
def open_world(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    tickets_kit: Any,
) -> Callable[..., WarmWorld]:
    """Opens ``WarmWorld``: ``keyed`` (default True) sets the synthetic key, ``transport`` the
    hub's ``tracker.transport`` and ``failures`` what the reads raise (default nothing)."""

    def opened(
        *,
        keyed: bool = True,
        transport: str = "api",
        failures: Iterator[TrackerError] | None = None,
    ) -> WarmWorld:
        raised = iter(()) if failures is None else failures
        world = WarmWorld(clock=MovableClock(), files=ListingReader(), failures=raised)
        inner = InMemoryTrackerReader(a_seeded_issue_board())
        world.reader = CountingTrackerReader(inner, before=world.on_read)
        hub = make_hub(change=lambda document: document["tracker"].update(transport=transport))
        for slug, issue in FEATURES.items():
            ticket = {"key": "t1", "id": issue, "title": f"Planned {slug} work", "order": 1}
            tickets_kit.write_feature(hub, tickets_kit.a_ticket_record([ticket]), slug=slug)
        world.composed = open_composed(
            replace(composed_settings, clock=world.clock),
            environ={"LINEAR_API_KEY": tickets_kit.key} if keyed else {},
            tracker_reader=world.reader,
            hub_reader=world.files,
        )
        registered = world.composed.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers=OWN
        )
        assert registered.status_code == 201, registered.text
        return world

    return opened


def test_reads_each_feature_once_when_first_browser_opens_on_cold_cache(
    open_world: Callable[..., WarmWorld],
) -> None:
    """The first tab to open wakes the warm ticker, so its tick runs at once; on a cold cache
    that tick reads each feature once."""
    world = open_world()
    ticker = world.composed.tickers["warm_ticker"]

    world.composed.browsers.opened()

    assert ticker.wakes == 1
    assert world.tick_at(0) == 2
    assert sorted(world.reader.calls) == EACH_FEATURE


def test_reads_again_only_near_stale_limit_when_ticks_run(
    open_world: Callable[..., WarmWorld],
) -> None:
    """AC-34, A10: ticks every 30 s read a feature cold, then only once its snapshot is 14 min
    old (one minute before the cache's 15 min stale limit), never at the 60 s TTL."""
    world = open_world()
    world.composed.browsers.opened()

    for seconds in range(0, 1681, 30):
        world.tick_at(seconds)

    assert world.reads() == {ids: [0, 840, 1680] for ids in EACH_FEATURE}


@pytest.mark.parametrize(
    ("keyed", "transport", "browser"),
    [(False, "api", True), (True, "mcp", True), (True, "api", False)],
    ids=["no-key", "mcp", "no-browser"],
)
def test_reads_nothing_when_no_reader_or_no_browser(
    open_world: Callable[..., WarmWorld], *, keyed: bool, transport: str, browser: bool
) -> None:
    """AC-34: with no reader (no key, or transport ``mcp``) or no tab holding the global stream,
    no tick calls the tracker; with no key a tick lists no feature folder either."""
    world = open_world(keyed=keyed, transport=transport)
    listed = world.composed.client.get("/api/v1/features", params={"project": "demo"})
    assert listed.status_code == 200, listed.text
    assert {item["slug"]: item["problem"] for item in listed.json()["items"]} == {
        "alpha": None,
        "beta": None,
    }
    assert world.files.listed, "the hub reader recorded no feature folder listing"
    world.files.listed.clear()
    if browser:
        world.composed.browsers.opened()

    for seconds in range(0, 961, 30):
        world.tick_at(seconds)

    assert world.reader.count == 0
    # With no key the warmer lists nothing; with one, listing is its own business.
    assert world.files.listed == [] or keyed


def test_asks_failed_feature_again_only_after_hold_when_ticks_run(
    open_world: Callable[..., WarmWorld],
) -> None:
    """A read that fails holds its feature for the cache's 60 s: the ticks ask Linear once per
    hold, not once per 30 s tick."""
    world = open_world(failures=itertools.repeat(_tracker_error("unavailable", 500)))
    world.composed.browsers.opened()

    for seconds in range(0, 301, 30):
        world.tick_at(seconds)

    assert world.reads() == {ids: [0, 60, 120, 180, 240, 300] for ids in EACH_FEATURE}


def test_pauses_until_cooldown_when_linear_rate_limits(
    open_world: Callable[..., WarmWorld],
) -> None:
    """A rate-limit answer (429) ends the tick and pauses the warmer for the cache's 60 s
    cooldown: the paused ticks do nothing, not even list the features; then reads resume."""
    world = open_world(failures=iter([_tracker_error("rate_limited", 429)]))
    world.composed.browsers.opened()

    first = world.tick_at(0)
    world.files.listed.clear()
    paused = [world.tick_at(30), world.tick_at(59)]
    paused_listings = list(world.files.listed)
    resumed = world.tick_at(61)

    assert first == 1, "the tick went on after the 429"
    assert paused == [0, 0]
    assert paused_listings == []
    assert resumed == 2
    assert sorted(world.reader.calls[1:]) == EACH_FEATURE
    assert world.files.listed, "the resumed tick listed no feature folder"
