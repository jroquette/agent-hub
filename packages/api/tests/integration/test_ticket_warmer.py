"""The ticket warmer of ``hub web`` (AGH-613, AC-34, A10): while a tab holds the global stream
open and a Linear key is set, a background part reads a feature's tickets into the cache when its
snapshot is missing or 14 min old, within the cache's 60 s holds, at most 224 features a tick,
and pauses after a rate-limit answer or a refused key; with no key, no tab or the MCP transport
it reads nothing.

Seam: ``build_app(..., warm_ticker=)``, driven through ``manual_tickers["warm_ticker"]`` (a
``ManualTicker``; its ``wake()`` counts the calls in ``wakes``, as ``stop()`` counts in
``stops``), ``Composed.browsers`` (the app's ``ConnectedBrowsers``) and ``Composed.warm()`` (one
warm tick on the caller's thread). Linear is ``CountingTrackerReader`` over the seeded board
(``build_app(tracker_reader=)``) with a synthetic ``LINEAR_API_KEY`` in the injected environment
or in Settings' key file; the app's clock is moved by the test. ``ListingReader`` is
``HubFileSystem`` recording each feature folder listing. ``TabStream`` holds
``GET /api/v1/events/stream`` open on the composed app as a tab does. The cap and the refused
key build ``TicketWarmer(requests, snapshots, browsers, *, ticker, key_digest, clock)`` directly
over a real ``CachedTicketSnapshots``, with a ``ManualTicker`` and one open stream. No sleep, not
``serial``.
"""

import hashlib
import itertools
import logging
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest

from agent_hub.api.connected_browsers import ConnectedBrowsers
from agent_hub.api.linear_connection import KEY_FILE_NAME, LinearKeyFile
from agent_hub.api.settings import ApiSettings
from agent_hub.api.ticket_snapshots import CachedTicketSnapshots
from agent_hub.api.ticket_warmer import TicketWarmer
from agent_hub.core.errors import TrackerError, TrackerFailure
from agent_hub.core.features.ticket_snapshots import SnapshotRequest
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
# How long a ``TabStream`` stays open at most if the test never leaves (a failed assertion).
TAB_LIMIT_SECONDS = 30


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


def _write_features(hub: Path, tickets_kit: Any) -> None:
    """``FEATURES`` in ``hub``, each naming its one issue."""
    for slug, issue in FEATURES.items():
        ticket = {"key": "t1", "id": issue, "title": f"Planned {slug} work", "order": 1}
        tickets_kit.write_feature(hub, tickets_kit.a_ticket_record([ticket]), slug=slug)


@pytest.fixture
def open_world(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    tickets_kit: Any,
) -> Callable[..., WarmWorld]:
    """Opens ``WarmWorld``: ``keyed`` (default True) sets the synthetic key in the environment,
    ``saved_key`` saves it in Settings' key file instead, ``transport`` is the hub's
    ``tracker.transport`` and ``failures`` what the reads raise (default nothing)."""

    def opened(
        *,
        keyed: bool = True,
        saved_key: bool = False,
        transport: str = "api",
        failures: Iterator[TrackerError] | None = None,
    ) -> WarmWorld:
        raised = iter(()) if failures is None else failures
        world = WarmWorld(clock=MovableClock(), files=ListingReader(), failures=raised)
        inner = InMemoryTrackerReader(a_seeded_issue_board())
        world.reader = CountingTrackerReader(inner, before=world.on_read)
        hub = make_hub(change=lambda document: document["tracker"].update(transport=transport))
        _write_features(hub, tickets_kit)
        settings = replace(composed_settings, clock=world.clock)
        world.composed = open_composed(
            settings,
            environ={"LINEAR_API_KEY": tickets_kit.key} if keyed and not saved_key else {},
            tracker_reader=world.reader,
            hub_reader=world.files,
        )
        registered = world.composed.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers=OWN
        )
        assert registered.status_code == 201, registered.text
        if saved_key:
            LinearKeyFile(settings.registry_path.parent / KEY_FILE_NAME).write(tickets_kit.key)
        return world

    return opened


@pytest.mark.parametrize("saved_key", [False, True], ids=["environment", "settings"])
def test_reads_each_feature_once_when_first_browser_opens_on_cold_cache(
    open_world: Callable[..., WarmWorld], *, saved_key: bool
) -> None:
    """The first tab to open wakes the warm ticker, so its tick runs at once; on a cold cache
    that tick reads each feature once, whether the key is in the environment or was saved from
    Settings (the key file ``hub web`` reads at call time)."""
    world = open_world(saved_key=saved_key)
    ticker = world.composed.tickers["warm_ticker"]

    world.composed.browsers.opened()

    assert ticker.wakes == 1
    assert world.tick_at(0) == 2
    assert sorted(world.reader.calls) == EACH_FEATURE


class TabStream:
    """A tab holding ``GET path`` open on the composed app, served on the app's own event loop
    (the test client's portal) as uvicorn serves it (ASGI spec 2.3), one chunk at a time; the
    test client itself answers only once a response ends, which the global stream never does.

    ``leave()`` is the tab closing: the client disconnects, and it returns once the app has ended
    the request. A tab never left disconnects after ``TAB_LIMIT_SECONDS``.
    """

    def __init__(self, composed: Any, path: str) -> None:
        portal = composed.client.portal
        assert portal is not None, "the test client is not open: it has no event loop"
        self._portal = portal
        self._asked = False
        self._left: anyio.Event = portal.call(anyio.Event)
        self.first_chunk = threading.Event()
        self.chunks: list[bytes] = []
        self.statuses: list[int] = []
        port = composed.settings.port
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", f"127.0.0.1:{port}".encode()), (b"accept", b"text/event-stream")],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", port),
            "state": {},
        }
        self._served = portal.start_task_soon(composed.client.app, scope, self._receive, self._send)

    async def _receive(self) -> dict[str, Any]:
        if not self._asked:
            self._asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        with anyio.move_on_after(TAB_LIMIT_SECONDS):
            await self._left.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.statuses.append(message["status"])
        elif message["type"] == "http.response.body" and message.get("body"):
            self.chunks.append(message["body"])
            self.first_chunk.set()

    def leave(self) -> None:
        self._portal.call(self._left.set)
        self._served.result(timeout=5)


def test_counts_tab_until_stream_closes_when_global_stream_served(
    open_world: Callable[..., WarmWorld],
) -> None:
    """AC-34: the composed app counts a tab's ``GET /api/v1/events/stream`` in the count the
    warmer reads: once its first chunk is sent the count is connected and the warm ticker was
    woken once; once the tab leaves, the count is back to none."""
    world = open_world()
    ticker = world.composed.tickers["warm_ticker"]
    assert (world.composed.browsers.connected(), ticker.wakes) == (False, 0)

    tab = TabStream(world.composed, "/api/v1/events/stream")
    got_first = tab.first_chunk.wait(5)
    while_open = (world.composed.browsers.connected(), ticker.wakes)
    tab.leave()

    assert got_first, "the stream sent no chunk within 5 s"
    assert tab.statuses == [200]
    assert tab.chunks[0].startswith(b"retry:")
    assert while_open == (True, 1)
    assert not world.composed.browsers.connected()


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


FEATURE_A = SnapshotRequest(project="demo", transport="api", ids=("DEM-1",))
FEATURE_B = SnapshotRequest(project="demo", transport="api", ids=("DEM-3",))


def _warmer(
    requests: tuple[SnapshotRequest, ...],
    snapshots: CachedTicketSnapshots,
    *,
    ticker: Any,
    key_digest: Callable[[], str | None],
    clock: MovableClock,
) -> TicketWarmer:
    """``TicketWarmer`` over ``requests`` in that order, with one global stream open."""
    browsers = ConnectedBrowsers()
    browsers.opened()
    return TicketWarmer(
        lambda: requests, snapshots, browsers, ticker=ticker, key_digest=key_digest, clock=clock
    )


@pytest.mark.anyio
async def test_warms_at_most_cap_and_logs_rest_once_when_features_exceed_cap(
    manual_tickers: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A tick warms at most 224 features (the cache's 256 entries less 32 kept for the pages' own
    reads), the first in order, so no warmed entry falls out of the cache before the next tick;
    how many it leaves out is logged once, as a warning."""
    clock = MovableClock()
    reader = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()))
    snapshots = CachedTicketSnapshots(lambda _request: reader, clock=clock)
    requests = tuple(
        SnapshotRequest(project="demo", transport="api", ids=(f"DEM-{number}",))
        for number in range(1, 301)
    )
    ticker = manual_tickers["refresh_ticker"]  # a ManualTicker the test drives
    digest = hashlib.sha256(b"synthetic key").hexdigest()
    await _warmer(
        requests, snapshots, ticker=ticker, key_digest=lambda: digest, clock=clock
    ).start()
    caplog.set_level(logging.WARNING)

    for seconds in range(0, 811, 30):
        clock.at(seconds)
        ticker.tick()

    warned = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert reader.calls == [request.ids for request in requests[:224]]
    assert {snapshots.cached(request).source for request in requests[:224]} == {"linear"}
    assert len(warned) == 1
    assert re.search(r"\b76\b", warned[0]), warned[0]


@dataclass
class KeyedLinear:
    """Linear behind a key the test changes: each read is refused while the key is refused."""

    key: str = "old"
    refused: set[str] = field(default_factory=set)

    def digest(self) -> str:
        """``key_digest``: the SHA-256 of the current key."""
        return hashlib.sha256(self.key.encode()).hexdigest()

    def use_new_key(self) -> None:
        self.key = "new"

    def refuse_old_key(self) -> None:
        self.refused.add("old")

    def check(self) -> None:
        """``CountingTrackerReader``'s ``before``: Linear refuses a read made with a refused key."""
        if self.key in self.refused:
            raise _tracker_error("unauthorized", 401)


# Each step: (seconds after START, what happens, how many tracker reads it makes, or None).
# A "page fetch" is a feature page's ``snapshots.fetch`` of FEATURE_A, the warmer's first feature.
_PAUSED_14_MIN = [(seconds, "tick", 0) for seconds in range(30, 900, 30)]
KEY_PAUSES = {
    # The key unchanged: no call for 15 min after the refusal, then the next tick asks again.
    "same-key": [
        (0, "refuse old key", None),
        (0, "tick", 1),
        *_PAUSED_14_MIN,
        (899, "tick", 0),
        (901, "tick", 1),
    ],
    # A new key 20 s after the refusal, first seen at 30 s: the refused feature's hold ends at
    # 60 s, yet the tick at 90 s, a minute after the key was first seen, is the first to read,
    # and each read reaches Linear.
    "new-key": [
        (0, "refuse old key", None),
        (0, "tick", 1),
        (20, "new key", None),
        (30, "tick", 0),
        (60, "tick", 0),
        (90, "tick", 2),
    ],
    # A feature page refused with the old key 70 s after the warmer, a new key 10 s later, first
    # seen at 90 s: the warmer's next calls come a minute after that and reach Linear.
    "page-refusal": [
        (0, "refuse old key", None),
        (0, "tick", 1),
        (30, "tick", 0),
        (60, "tick", 0),
        (70, "page fetch", 1),
        (80, "new key", None),
        (90, "tick", 0),
        (120, "tick", 0),
        (150, "tick", 2),
    ],
    # Unpaused with fresh entries: a feature page refused with the old key, a new key 10 s later,
    # first seen at 120 s, when the tick meets the held refusal: no 15 min pause; the warmer waits
    # out 90 s (the 60 s hold and the 30 s read wait), then reads that feature with the new key.
    "held-refusal": [
        (0, "tick", 2),
        (30, "tick", 0),
        (60, "tick", 0),
        (90, "tick", 0),
        (100, "refuse old key", None),
        (100, "page fetch", 1),
        (110, "new key", None),
        (120, "tick", 0),
        (150, "tick", 0),
        (180, "tick", 0),
        (209, "tick", 0),
        (211, "tick", 1),
    ],
}


@pytest.mark.anyio
@pytest.mark.parametrize("steps", list(KEY_PAUSES.values()), ids=list(KEY_PAUSES))
async def test_pauses_until_new_key_or_pause_ends_when_linear_refuses_key(
    manual_tickers: dict[str, Any], *, steps: list[tuple[int, str, int | None]]
) -> None:
    """A refused key ends the tick and pauses the warmer for 15 min, or until it has seen another
    key (compared by digest) for a minute, since the cache holds a refusal that long whatever the
    key; a refusal met within 90 s of first seeing a new key starts no 15 min pause."""
    clock, linear = MovableClock(), KeyedLinear()
    inner = InMemoryTrackerReader(a_seeded_issue_board())
    reader = CountingTrackerReader(inner, before=linear.check)
    snapshots = CachedTicketSnapshots(lambda _request: reader, clock=clock)
    ticker = manual_tickers["refresh_ticker"]  # a ManualTicker the test drives
    features = (FEATURE_A, FEATURE_B)
    warmer = _warmer(features, snapshots, ticker=ticker, key_digest=linear.digest, clock=clock)
    await warmer.start()
    actions: dict[str, Callable[[], object]] = {
        "tick": ticker.tick,
        "page fetch": lambda: snapshots.fetch(FEATURE_A),
        "new key": linear.use_new_key,
        "refuse old key": linear.refuse_old_key,
    }

    for seconds, action, reads in steps:
        clock.at(seconds)
        before = reader.count
        actions[action]()
        assert reads is None or reader.count - before == reads, f"{action} at {seconds} s"
