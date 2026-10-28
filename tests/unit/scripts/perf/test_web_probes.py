"""The perf suite's ``hub web`` probes (``scripts/perf/web_probes.py``): readiness by an HTTP
answer, hub registration with the server's ``Origin``, the canonical route and restart paths, the
200-and-sessions checks, the two restart rows per start, and peak RSS from ``VmHWM``.

Every process, request and clock is injected, so no test starts ``hub web`` or opens a socket.
Seam: ``start_web(argv, env, *, spawn, get, clock, sleep)`` returns an object with
``base_url`` and ``token``; ``register_hub(base_url, hub_dir, *, post)``; ``route_probes()``
(items with ``kind`` and ``path``) and the ``ROUTE_PATHS`` and ``RESTART_PATHS`` constants;
``measure_route(base_url, probe, *, runs, get, clock)``; ``restart_rows(argv, env, *, runs, spawn,
get, clock, sleep, peak_rss)`` returns items with ``kind``, ``path``, ``samples_ms`` and
``rss_mb``; ``peak_rss_mb(pid, *, proc)``. ``spawn`` is called like ``subprocess.Popen`` (text
mode) and ``get``/``post`` like ``httpx.get``/``httpx.post``; a suite failure raises
``SuiteError`` naming the path."""

import io
import re
import signal
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest

from scripts.perf import web_probes
from scripts.perf.fixture import FEATURE_SLUG
from scripts.perf.web_probes import (
    RESTART_PATHS,
    ROUTE_PATHS,
    SuiteError,
    measure_route,
    peak_rss_mb,
    register_hub,
    restart_rows,
    route_probes,
    start_web,
)

PORT = 7431
BASE_URL = f"http://127.0.0.1:{PORT}"
URL_NONCE = "synthetic-token"
URL_LINE = f"agent-hub at {BASE_URL}/?token={URL_NONCE}\n"
# The route and restart rows, written out by hand.
ROUTES = (
    "/api/v1/sessions",
    "/api/v1/sessions?issue=AGH-7",
    "/api/v1/features",
    f"/api/v1/features/perf/{FEATURE_SLUG}",
    "/api/v1/projects/perf/skills",
    "/api/v1/search?q=make",
    "/api/v1/live-sessions",
)
RESTARTS = ("hub web start → GET /", "hub web start → /api/v1/sessions")
# One page of GET /api/v1/sessions (docs/API.md, "Pagination").
SESSIONS_PAGE = {"items": [{"session": "perf-00000"}], "next_cursor": None, "total_estimate": 1}
EMPTY_PAGE = {"items": [], "next_cursor": None, "total_estimate": 0}
ARGV = ["/venv/bin/hub", "web", "--host", "127.0.0.1", "--port", str(PORT), "--no-open"]
ENV = {"HOME": "/perf-root/home", "PATH": "/perf-root/bin"}


class FakeClock:
    """Seconds that move on ``sleep`` and on each fake request."""

    def __init__(self) -> None:
        self.now = 500.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class FakeProcess:
    """A ``Popen`` stand-in whose stdout holds the URL line; a signal ends it."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.stdout = io.StringIO(URL_LINE)
        self.stderr = io.StringIO("")
        self.returncode: int | None = None
        self.signals: list[int] = []

    def poll(self) -> int | None:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self.returncode = -sig

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class Spawner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, argv: Sequence[object], **_: object) -> FakeProcess:
        self.calls.append([str(part) for part in argv])
        process = FakeProcess(4000 + len(self.processes))
        self.processes.append(process)
        return process


Answer = Callable[[str, int], httpx.Response]


class FakeGet:
    """Records each URL; ``answer(url, call_number)`` gives the response or raises."""

    def __init__(self, clock: FakeClock, answer: Answer) -> None:
        self.clock = clock
        self.answer = answer
        self.urls: list[str] = []

    def __call__(self, url: object, **_: object) -> httpx.Response:
        self.urls.append(str(url))
        self.clock.now += 0.005
        return self.answer(str(url), len(self.urls))


def _response(url: str, status: int, body: object = None) -> httpx.Response:
    request = httpx.Request("GET", url)
    if body is None:
        return httpx.Response(status, text="<!doctype html>", request=request)
    return httpx.Response(status, json=body, request=request)


def _healthy(url: str, _call: int) -> httpx.Response:
    if url.split("?")[0].endswith("/api/v1/sessions"):
        return _response(url, 200, SESSIONS_PAGE)
    if "/api/" in url:
        return _response(url, 200, {"items": []})
    return _response(url, 200)


def _route(path: str) -> object:
    found = [probe for probe in route_probes() if probe.path == path]
    assert len(found) == 1, [probe.path for probe in route_probes()]
    return found[0]


def test_waits_for_an_http_answer_when_the_url_line_is_printed() -> None:
    clock = FakeClock()
    spawn = Spawner()

    def refused_twice(url: str, call: int) -> httpx.Response:
        if call <= 2:
            raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))
        return _response(url, 200)

    get = FakeGet(clock, refused_twice)

    web = start_web(ARGV, ENV, spawn=spawn, get=get, clock=clock, sleep=clock.sleep)

    assert spawn.calls == [ARGV]
    assert get.urls == [f"{BASE_URL}/"] * 3
    assert web.base_url == BASE_URL
    assert web.token == URL_NONCE


def test_registers_the_hub_with_the_server_origin_when_started(tmp_path: Path) -> None:
    hub = tmp_path / "perf-root" / "hub"
    hub.mkdir(parents=True)
    calls: list[tuple[str, dict[str, object]]] = []

    def post(url: object, **kwargs: object) -> httpx.Response:
        calls.append((str(url), kwargs))
        request = httpx.Request("POST", str(url))
        return httpx.Response(201, json={"id": "h1", "path": str(hub)}, request=request)

    register_hub(BASE_URL, hub, post=post)

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == f"{BASE_URL}/api/v1/hubs"
    assert kwargs.get("json") == {"path": str(hub)}
    headers = kwargs.get("headers")
    assert isinstance(headers, dict)
    assert {str(k).lower(): v for k, v in headers.items()}.get("origin") == BASE_URL


def test_lists_the_canonical_routes_and_restarts_when_probes_are_built() -> None:
    probes = route_probes()

    assert sorted(probe.path for probe in probes) == sorted(ROUTES)
    assert {probe.kind for probe in probes} == {"route"}
    assert sorted(ROUTE_PATHS) == sorted(ROUTES)
    assert sorted(RESTART_PATHS) == sorted(RESTARTS)


@pytest.mark.parametrize("status", [204, 302, 404, 500, 503])
def test_fails_the_suite_when_a_route_answers_any_status_but_ok(status: int) -> None:
    clock = FakeClock()
    get = FakeGet(clock, lambda url, _call: _response(url, status, {"title": "failed"}))

    with pytest.raises(SuiteError, match=re.escape("/api/v1/features")):
        measure_route(BASE_URL, _route("/api/v1/features"), runs=3, get=get, clock=clock)


def test_fails_the_suite_when_sessions_is_empty() -> None:
    clock = FakeClock()
    listed = FakeGet(clock, lambda url, _call: _response(url, 200, SESSIONS_PAGE))
    samples = measure_route(BASE_URL, _route("/api/v1/sessions"), runs=2, get=listed, clock=clock)
    assert len(samples) == 2
    empty = FakeGet(clock, lambda url, _call: _response(url, 200, EMPTY_PAGE))

    with pytest.raises(SuiteError, match=re.escape("/api/v1/sessions")):
        measure_route(BASE_URL, _route("/api/v1/sessions"), runs=2, get=empty, clock=clock)


def test_gives_two_rows_per_start_when_restarts_are_measured() -> None:
    clock = FakeClock()
    spawn = Spawner()
    get = FakeGet(clock, _healthy)
    peaks: list[int] = []
    # Read after GET / then after /api/v1/sessions, for each of the three starts.
    readings = iter([100.0, 150.0, 110.0, 160.0, 105.0, 155.0])

    def peak_rss(pid: int) -> float | None:
        peaks.append(pid)
        return next(readings)

    rows = restart_rows(
        ARGV,
        ENV,
        runs=3,
        spawn=spawn,
        get=get,
        clock=clock,
        sleep=clock.sleep,
        peak_rss=peak_rss,
    )

    assert len(spawn.calls) == 3
    assert sorted(row.path for row in rows) == sorted(RESTARTS)
    assert len(rows) == 2
    assert {row.kind for row in rows} == {"restart"}
    assert [len(row.samples_ms) for row in rows] == [3, 3]
    by_path = {row.path: row for row in rows}
    # Each fake request moves the clock 5 ms: GET / answers at 5 ms, the sessions page at 10 ms.
    assert by_path[RESTARTS[0]].samples_ms == pytest.approx([5.0, 5.0, 5.0])
    assert by_path[RESTARTS[1]].samples_ms == pytest.approx([10.0, 10.0, 10.0])
    assert by_path[RESTARTS[0]].rss_mb == 110.0
    assert by_path[RESTARTS[1]].rss_mb == 160.0
    assert peaks == [4000, 4000, 4001, 4001, 4002, 4002]
    assert set(peaks) <= {process.pid for process in spawn.processes}
    assert [signal.SIGINT in process.signals for process in spawn.processes] == [True] * 3


STATUS_WITH_HWM = (
    "Name:\thub\nVmPeak:\t  300000 kB\nVmSize:\t  290000 kB\n"
    "VmHWM:\t  176128 kB\nVmRSS:\t  150000 kB\nThreads:\t4\n"
)
STATUS_WITHOUT_HWM = "Name:\thub\nVmPeak:\t  300000 kB\nVmRSS:\t  150000 kB\nThreads:\t4\n"


@pytest.mark.parametrize(
    ("status_text", "expected"),
    [
        # /proc's "kB" is KiB: 176128 KiB is 176128 * 1024 bytes, 180.355072 MB.
        (STATUS_WITH_HWM, 180.355072),
        (STATUS_WITHOUT_HWM, None),
    ],
)
def test_reads_peak_rss_from_vmhwm_when_proc_status_is_given(
    tmp_path: Path, status_text: str, expected: object
) -> None:
    pid = 4242
    status = tmp_path / str(pid) / "status"
    status.parent.mkdir()
    status.write_text(status_text, "utf-8")

    assert peak_rss_mb(pid, proc=tmp_path) == expected


class SilentProcess(FakeProcess):
    """A ``hub web`` that prints nothing: its ``readline`` blocks until the test ends."""

    def __init__(self, pid: int, released: threading.Event) -> None:
        super().__init__(pid)
        self.released = released

        class Blocking(io.StringIO):
            def readline(self, size: int | None = -1) -> str:
                released.wait()
                return ""

        self.stdout = Blocking()


def test_fails_the_suite_when_hub_web_prints_no_url_line() -> None:
    clock = FakeClock()
    process = FakeProcess(4000)
    process.stdout = io.StringIO("Traceback (most recent call last):\n")
    get = FakeGet(clock, _healthy)

    with pytest.raises(SuiteError, match="no URL line"):
        start_web(
            ARGV, ENV, spawn=lambda *_a, **_k: process, get=get, clock=clock, sleep=clock.sleep
        )

    assert get.urls == []
    assert signal.SIGINT in process.signals


def test_fails_the_suite_when_hub_web_prints_nothing_in_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_probes, "START_SECONDS", 0.05)
    clock = FakeClock()
    released = threading.Event()
    process = SilentProcess(4000, released)
    try:
        with pytest.raises(SuiteError, match="no URL line within"):
            start_web(
                ARGV,
                ENV,
                spawn=lambda *_a, **_k: process,
                get=FakeGet(clock, _healthy),
                clock=clock,
                sleep=clock.sleep,
            )
    finally:
        released.set()

    assert signal.SIGINT in process.signals


def _refused(url: str, _call: int) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))


def test_fails_the_suite_when_hub_web_never_answers_before_the_deadline() -> None:
    clock = FakeClock()
    spawn = Spawner()
    get = FakeGet(clock, _refused)

    with pytest.raises(SuiteError, match=re.escape("hub web start → /: no 200 within")):
        start_web(ARGV, ENV, spawn=spawn, get=get, clock=clock, sleep=clock.sleep)

    assert clock.now >= 500.0 + web_probes.START_SECONDS
    assert signal.SIGINT in spawn.processes[0].signals


def test_caps_each_readiness_request_at_the_time_left_when_requests_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A start deadline shorter than one request's own timeout.
    monkeypatch.setattr(web_probes, "START_SECONDS", 30.0)
    clock = FakeClock()
    spawn = Spawner()
    timeouts: list[float] = []

    def hanging(url: object, *, timeout: float, **_: object) -> httpx.Response:
        # A request that hangs until its own timeout runs out.
        timeouts.append(timeout)
        clock.now += timeout
        raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", str(url)))

    with pytest.raises(SuiteError, match=re.escape("hub web start → /: no 200 within")):
        start_web(ARGV, ENV, spawn=spawn, get=hanging, clock=clock, sleep=clock.sleep)

    assert timeouts
    assert all(timeout <= 30.0 for timeout in timeouts)
    deadline = 500.0 + 30.0
    assert clock.now <= deadline + web_probes.POLL_SECONDS * 2


def test_fails_the_suite_when_hub_web_exits_before_answering() -> None:
    clock = FakeClock()
    process = FakeProcess(4000)
    process.returncode = 1
    get = FakeGet(clock, _refused)

    with pytest.raises(SuiteError, match="exited before answering"):
        start_web(
            ARGV, ENV, spawn=lambda *_a, **_k: process, get=get, clock=clock, sleep=clock.sleep
        )

    assert get.urls == [f"{BASE_URL}/"]
    assert clock.slept == []


def _timed_out(url: str, _call: int) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))


def test_fails_the_suite_when_a_route_request_times_out() -> None:
    clock = FakeClock()
    get = FakeGet(clock, _timed_out)

    with pytest.raises(SuiteError, match=re.escape("/api/v1/features: ReadTimeout")):
        measure_route(BASE_URL, _route("/api/v1/features"), runs=3, get=get, clock=clock)


def test_fails_the_suite_when_registering_the_hub_cannot_connect(tmp_path: Path) -> None:
    def post(url: object, **_: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", str(url)))

    with pytest.raises(SuiteError, match=re.escape("POST /api/v1/hubs: ConnectError")):
        register_hub(BASE_URL, tmp_path, post=post)
