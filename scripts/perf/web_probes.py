"""``make perf``'s ``hub web`` probes: start and readiness, hub registration, routes, restarts, RSS.

``hub web`` prints its URL line before uvicorn serves, so ``start_web`` takes the token from that
line and then polls ``GET /`` until it answers 200. ``register_hub`` posts the temp hub with the
server's own ``Origin``, as the registry write requires. ``measure_route`` sends one warm-up
request, then times ``runs`` more; any answer but 200, an empty ``/api/v1/sessions`` page (the
fixture always lists sessions, so an empty one means the server read the wrong database) or a
request that fails raises ``SuiteError`` naming the path. ``restart_rows`` starts ``hub web`` once
per run and gives two rows from each start (start to ``GET /``, start to the first
``/api/v1/sessions`` 200), each with the peak RSS from ``/proc/<pid>/status`` (``VmHWM``) read
right after that row's answer, then stops it with SIGINT.
Processes, requests, the clock and sleeps are injected, so the unit tests start nothing.
"""

import queue
import re
import signal
import subprocess
import threading
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
# Generous: on the 400k-event fixture the first /api/v1/sessions takes about 16 s and a start to
# it about 20 s; a slow machine must be reported as over budget, not as a failed suite.
START_SECONDS = 120.0
STOP_SECONDS = 15.0
REQUEST_SECONDS = 120.0
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
    """One restart row's samples; ``rss_mb`` is the highest peak seen when this row's endpoint
    answered, ``None`` when unknown."""

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
        line = _first_line(process.stdout, seconds=START_SECONDS)
        found = _URL_LINE.search(line)
        if found is None:
            raise SuiteError(f"hub web start: no URL line, got {line!r}")
        web = RunningWeb(base_url=found[1], token=found[2], process=process)
        _wait_for(web, "/", get=get, clock=clock, sleep=sleep, deadline=clock() + START_SECONDS)
    except BaseException:
        stop_web(process)
        raise
    return web


def _first_line(stream: IO[str] | None, *, seconds: float) -> str:
    """``stream``'s first line, read in a thread so a silent ``hub web`` cannot block the suite."""
    if stream is None:
        return ""
    lines: queue.Queue[str] = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    try:
        return lines.get(timeout=seconds)
    except queue.Empty:
        raise SuiteError(f"hub web start: no URL line within {seconds:.0f} s") from None


def _wait_for(
    web: RunningWeb, path: str, *, get: Get, clock: Clock, sleep: Sleep, deadline: float
) -> None:
    """Poll ``GET path`` until it answers 200; ``SuiteError`` on exit or past ``deadline``.

    Each request waits no longer than the time left, so a hanging one cannot outlast the deadline.
    """
    while True:
        timeout = min(REQUEST_SECONDS, max(deadline - clock(), POLL_SECONDS))
        try:
            if get(f"{web.base_url}{path}", timeout=timeout).status_code == 200:
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
    try:
        response = post(
            f"{base_url}/api/v1/hubs",
            json={"path": str(hub_dir)},
            headers={"Origin": base_url},
            timeout=REQUEST_SECONDS,
        )
    except httpx.HTTPError as error:
        raise SuiteError(f"POST /api/v1/hubs: {type(error).__name__}: {error}") from error
    if response.status_code != 201:
        raise SuiteError(f"POST /api/v1/hubs: answered {response.status_code}")


def route_probes() -> list[RouteProbe]:
    """The route rows, in table order."""
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
    _check(probe.path, _get(get, base_url, probe.path))
    samples = []
    for _ in range(runs):
        start = clock()
        response = _get(get, base_url, probe.path)
        elapsed = clock() - start
        _check(probe.path, response)
        samples.append(elapsed * 1000)
    return samples


def _get(get: Get, base_url: str, path: str) -> httpx.Response:
    """``GET path``; a timeout or a refused connection is a ``SuiteError`` naming the path."""
    try:
        return get(f"{base_url}{path}", timeout=REQUEST_SECONDS)
    except httpx.HTTPError as error:
        raise SuiteError(f"{path}: {type(error).__name__}: {error}") from error


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
    page_peaks: list[float] = []
    sessions_peaks: list[float] = []

    def sample_rss(pid: int, peaks: list[float]) -> None:
        peak = read_rss(pid)
        if peak is not None:
            peaks.append(peak)

    for _ in range(runs):
        start = clock()
        web = start_web(argv, env, spawn=spawn, get=get, clock=clock, sleep=sleep)
        try:
            to_page.append((clock() - start) * 1000)
            sample_rss(web.process.pid, page_peaks)
            deadline = start + START_SECONDS
            _wait_for(web, SESSIONS, get=get, clock=clock, sleep=sleep, deadline=deadline)
            to_sessions.append((clock() - start) * 1000)
            sample_rss(web.process.pid, sessions_peaks)
        finally:
            stop_web(web.process)
    return [
        RestartRow(RESTART, START_TO_PAGE, to_page, max(page_peaks, default=None)),
        RestartRow(RESTART, START_TO_SESSIONS, to_sessions, max(sessions_peaks, default=None)),
    ]


def peak_rss_mb(pid: int, *, proc: Path = Path("/proc")) -> float | None:
    """``pid``'s peak RSS in MB from ``VmHWM``; ``None`` when it cannot be read (off Linux).

    ``/proc`` writes "kB" but means KiB (1024 bytes).
    """
    try:
        text = (proc / str(pid) / "status").read_text("utf-8")
    except OSError:
        return None
    found = re.search(r"^VmHWM:\s+(\d+)\s+kB", text, re.MULTILINE)
    return int(found[1]) * 1024 / 1_000_000 if found else None
