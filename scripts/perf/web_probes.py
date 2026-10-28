"""``make perf``'s ``hub web`` probes: start and readiness, hub registration, routes, restarts, RSS.

``hub web`` prints its URL line before uvicorn serves, so ``start_web`` takes the token from that
line and then polls ``GET /`` until it answers 200. ``register_hub`` posts the temp hub with the
server's own ``Origin``, as the registry write requires. ``measure_route`` sends one warm-up
request, then times ``runs`` more; any answer but 200, or an empty ``/api/v1/sessions`` page
(spec AC-7), raises ``SuiteError`` naming the path. ``restart_rows`` starts ``hub web`` once per run
and gives two rows from each start (start to ``GET /``, start to the first ``/api/v1/sessions``
200), with the peak RSS from ``/proc/<pid>/status`` (``VmHWM``), then stops it with SIGINT.
Processes, requests, the clock and sleeps are injected, so the unit tests start nothing.
"""

import re
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

import httpx

from scripts.perf.fixture import FEATURE_SLUG
from scripts.perf.process_probes import SuiteError as SuiteError

ROUTE = "route"
RESTART = "restart"
SESSIONS = "/api/v1/sessions"
ROUTE_PATHS = (
    SESSIONS,
    f"{SESSIONS}?issue=AGH-7",
    "/api/v1/features",
    f"/api/v1/features/perf/{FEATURE_SLUG}",
    "/api/v1/projects/perf/skills",
    "/api/v1/search?q=make",
    "/api/v1/live-sessions",
)
START_TO_PAGE = "hub web start → GET /"
START_TO_SESSIONS = "hub web start → /api/v1/sessions"
RESTART_PATHS = (START_TO_PAGE, START_TO_SESSIONS)
START_SECONDS = 30.0
STOP_SECONDS = 15.0
REQUEST_SECONDS = 30.0
POLL_SECONDS = 0.05
_URL_LINE = re.compile(r"(http://[^/\s]+)/\?token=(\S+)")

Get = Callable[..., httpx.Response]
Clock = Callable[[], float]
Sleep = Callable[[float], None]


class Process(Protocol):
    """What the suite uses of a ``subprocess.Popen`` (text mode)."""

    @property
    def pid(self) -> int: ...

    @property
    def stdout(self) -> IO[str] | None: ...

    def poll(self) -> int | None: ...

    def send_signal(self, sig: int) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[..., Process]


@dataclass(frozen=True)
class RunningWeb:
    """A started ``hub web``: its base URL (no trailing slash), session token and process."""

    base_url: str
    token: str
    process: Process


@dataclass(frozen=True)
class RouteProbe:
    kind: str
    path: str


@dataclass(frozen=True)
class RestartRow:
    """One restart row's samples; ``rss_mb`` is the highest peak seen, ``None`` when unknown."""

    kind: str
    path: str
    samples_ms: list[float]
    rss_mb: float | None


def start_web(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    spawn: Spawn = subprocess.Popen,
    get: Get = httpx.get,
    clock: Clock = time.perf_counter,
    sleep: Sleep = time.sleep,
) -> RunningWeb:
    """Start ``hub web`` and return once ``GET /`` answers 200 (``START_SECONDS`` at most)."""
    process = spawn(list(argv), env=dict(env), stdout=subprocess.PIPE, text=True)
    try:
        line = process.stdout.readline() if process.stdout is not None else ""
        found = _URL_LINE.search(line)
        if found is None:
            raise SuiteError(f"hub web start: no URL line, got {line!r}")
        web = RunningWeb(base_url=found[1], token=found[2], process=process)
        _wait_for(web, "/", get=get, clock=clock, sleep=sleep, deadline=clock() + START_SECONDS)
    except BaseException:
        stop_web(process)
        raise
    return web


def _wait_for(
    web: RunningWeb, path: str, *, get: Get, clock: Clock, sleep: Sleep, deadline: float
) -> None:
    """Poll ``GET path`` until it answers 200; ``SuiteError`` on exit or past ``deadline``."""
    while True:
        try:
            if get(f"{web.base_url}{path}", timeout=REQUEST_SECONDS).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if web.process.poll() is not None:
            raise SuiteError(f"hub web start → {path}: hub web exited before answering")
        if clock() >= deadline:
            raise SuiteError(f"hub web start → {path}: no 200 within {START_SECONDS:.0f} s")
        sleep(POLL_SECONDS)


def stop_web(process: Process) -> None:
    """SIGINT, as Ctrl+C stops it; killed when it is still up after ``STOP_SECONDS``."""
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=STOP_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def register_hub(base_url: str, hub_dir: Path, *, post: Get = httpx.post) -> None:
    """``POST /api/v1/hubs`` with the server's own ``Origin``; ``SuiteError`` unless 201."""
    response = post(
        f"{base_url}/api/v1/hubs",
        json={"path": str(hub_dir)},
        headers={"Origin": base_url},
        timeout=REQUEST_SECONDS,
    )
    if response.status_code != 201:
        raise SuiteError(f"POST /api/v1/hubs: answered {response.status_code}")


def route_probes() -> list[RouteProbe]:
    """The route rows, in the plan's order."""
    return [RouteProbe(ROUTE, path) for path in ROUTE_PATHS]


def measure_route(
    base_url: str,
    probe: RouteProbe,
    *,
    runs: int,
    get: Get = httpx.get,
    clock: Clock = time.perf_counter,
) -> list[float]:
    """One warm-up ``GET``, then ``runs`` timed ones; each duration in ms."""
    _check(probe.path, get(f"{base_url}{probe.path}", timeout=REQUEST_SECONDS))
    samples = []
    for _ in range(runs):
        start = clock()
        response = get(f"{base_url}{probe.path}", timeout=REQUEST_SECONDS)
        elapsed = clock() - start
        _check(probe.path, response)
        samples.append(elapsed * 1000)
    return samples


def _check(path: str, response: httpx.Response) -> None:
    if response.status_code != 200:
        raise SuiteError(f"{path}: answered {response.status_code}")
    if path == SESSIONS:
        body: Any = response.json()
        if not (isinstance(body, dict) and isinstance(body.get("items"), list) and body["items"]):
            raise SuiteError(f"{path}: listed no session")


def restart_rows(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    runs: int,
    spawn: Spawn = subprocess.Popen,
    get: Get = httpx.get,
    clock: Clock = time.perf_counter,
    sleep: Sleep = time.sleep,
    peak_rss: Callable[[int], float | None] | None = None,
) -> list[RestartRow]:
    """Start ``hub web`` ``runs`` times; two rows, each with one sample per start."""
    read_rss = peak_rss if peak_rss is not None else peak_rss_mb
    to_page: list[float] = []
    to_sessions: list[float] = []
    peaks: list[float] = []
    for _ in range(runs):
        start = clock()
        web = start_web(argv, env, spawn=spawn, get=get, clock=clock, sleep=sleep)
        try:
            to_page.append((clock() - start) * 1000)
            deadline = start + START_SECONDS
            _wait_for(web, SESSIONS, get=get, clock=clock, sleep=sleep, deadline=deadline)
            to_sessions.append((clock() - start) * 1000)
            peak = read_rss(web.process.pid)
            if peak is not None:
                peaks.append(peak)
        finally:
            stop_web(web.process)
    rss = max(peaks) if peaks else None
    return [
        RestartRow(RESTART, START_TO_PAGE, to_page, rss),
        RestartRow(RESTART, START_TO_SESSIONS, to_sessions, rss),
    ]


def peak_rss_mb(pid: int, *, proc: Path = Path("/proc")) -> float | None:
    """``pid``'s peak RSS in MiB from ``VmHWM``; ``None`` when it cannot be read (off Linux)."""
    try:
        text = (proc / str(pid) / "status").read_text("utf-8")
    except OSError:
        return None
    found = re.search(r"^VmHWM:\s+(\d+)\s+kB", text, re.MULTILINE)
    return int(found[1]) / 1024 if found else None
