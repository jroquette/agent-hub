"""The background part of ``hub web`` (AGH-608): a daemon ticker whose stop never waits for a
running tick, and the refresher part that rereads the hubs at start, ticks the hub snapshot and
logs each failed doctor run as one line naming the hub and the error's type only.

Seam: ``DaemonTicker(interval, *, name)`` with ``start(tick)``, ``stop()`` and ``thread``;
``DoctorRefresher(hubs, *, ticker)``, an ``AppLifecycle`` part (``start``, ``begin_exit``,
``stop``) over ``hubs.reread_hubs()`` and ``hubs.refresh() -> RefreshReport``. The
``manual_tickers`` fixture's ``ManualTicker`` runs a kept tick on the test's thread. A log line
is read as ``hub web`` writes it, through ``JsonFormatter``.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_hub.api.doctor_refresher import DaemonTicker, DoctorRefresher
from agent_hub.api.json_logging import JsonFormatter
from agent_hub.core.hubs.hub_registry import HubRegistryError
from agent_hub.core.hubs.hub_snapshot import RefreshFailure, RefreshReport

HUB_PATH = "/home/demo/demo-hub"
# A line of a synthetic note, quoted by a failed read's message: it must never reach a log.
NOTE_LINE = "Launch checklist for the synthetic demo team"


@dataclass
class FakeHubs:
    """The hub reads the refresher drives: records each call with its ``written`` mark;
    ``reread_error`` is raised by the next ``reread_hubs``; ``refresh`` answers ``report``."""

    report: RefreshReport = field(default_factory=lambda: RefreshReport(checked=(), failures=()))
    reread_error: Exception | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def reread_hubs(self, written: str | None = None) -> None:
        self.calls.append(("reread_hubs", written))
        if self.reread_error is not None:
            error, self.reread_error = self.reread_error, None
            raise error

    def refresh(self) -> RefreshReport:
        self.calls.append(("refresh", None))
        return self.report


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [JsonFormatter().format(record) for record in caplog.records]


def test_stops_without_joining_when_tick_is_running() -> None:
    """AC-27: ``stop()`` returns while a tick runs, and ends the wait for the next one."""
    entered, release = threading.Event(), threading.Event()
    ticks: list[str] = []

    def tick() -> None:
        ticks.append(threading.current_thread().name)
        entered.set()
        release.wait(30)

    ticker = DaemonTicker(3600, name="test-ticker")
    ticker.start(tick)
    assert entered.wait(5), "the first tick did not run at once"
    stopping = threading.Thread(target=ticker.stop, daemon=True)

    stopping.start()
    stopping.join(5)

    assert not stopping.is_alive(), "stop() waited for the running tick"
    assert ticker.thread.is_alive()
    assert (ticker.thread.daemon, ticker.thread.name) == (True, "test-ticker")
    release.set()
    ticker.thread.join(5)
    assert not ticker.thread.is_alive(), "the stopped ticker went on waiting for its interval"
    assert ticks == ["test-ticker"]


def test_logs_and_ticks_again_when_tick_raises(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    again = threading.Event()
    ticks: list[int] = []

    def tick() -> None:
        ticks.append(len(ticks))
        if len(ticks) == 1:
            raise RuntimeError("synthetic tick failure")
        again.set()

    ticker = DaemonTicker(0.01, name="test-ticker")
    ticker.start(tick)
    ran_again = again.wait(5)
    ticker.stop()
    ticker.thread.join(5)

    assert ran_again, "no tick ran after the one that raised"
    assert any("RuntimeError" in line for line in _lines(caplog))


@pytest.mark.anyio
async def test_rereads_hubs_before_first_tick_when_started(manual_tickers: dict[str, Any]) -> None:
    """AC-24: the first request already sees every hub (with null health): ``start`` rereads
    them and runs no doctor; the ticks refresh."""
    hubs = FakeHubs()
    ticker = manual_tickers["refresh_ticker"]
    refresher = DoctorRefresher(hubs, ticker=ticker)

    await refresher.start()

    assert hubs.calls == [("reread_hubs", None)]
    ticker.tick()
    assert hubs.calls == [("reread_hubs", None), ("refresh", None)]


@pytest.mark.anyio
async def test_starts_without_raising_when_first_reread_fails(
    manual_tickers: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding 5: a registry that cannot be read at start is logged with its type, the
    ticks still start, and the first one reads again."""
    caplog.set_level(logging.WARNING)
    hubs = FakeHubs(reread_error=HubRegistryError("the registry of hubs could not be read"))
    ticker = manual_tickers["refresh_ticker"]
    refresher = DoctorRefresher(hubs, ticker=ticker)

    await refresher.start()

    assert any("HubRegistryError" in line for line in _lines(caplog))
    ticker.tick()
    assert hubs.calls == [("reread_hubs", None), ("refresh", None)]


@pytest.mark.anyio
async def test_logs_only_error_type_and_hub_path_when_run_fails(
    manual_tickers: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding 18: a failed run is one warning with the hub path and the error's type,
    never its message (which can quote file text) or a traceback."""
    caplog.set_level(logging.DEBUG)
    failure = RefreshFailure(hub_path=HUB_PATH, error=OSError(f"brain/now.md: {NOTE_LINE}"))
    hubs = FakeHubs(report=RefreshReport(checked=(), failures=(failure,)))
    ticker = manual_tickers["refresh_ticker"]
    await DoctorRefresher(hubs, ticker=ticker).start()
    caplog.clear()

    ticker.tick()

    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    [record] = warnings
    line = JsonFormatter().format(record)
    assert record.levelno == logging.WARNING
    assert HUB_PATH in line
    assert "OSError" in line
    assert NOTE_LINE not in caplog.text
    assert (record.exc_info, record.stack_info) == (None, None)
