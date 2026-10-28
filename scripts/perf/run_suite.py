"""``make perf``'s entry point: ``python -m scripts.perf.run_suite``.

``Settings.from_env`` reads the knobs (``PERF_EVENTS``, ``PERF_RUNS``, ``PERF_RESTART_RUNS``,
``PERF_STRICT``, ``PERF_REBUILD``, ``PERF_OUT``, ``PERF_BUDGETS``, ``PERF_CACHE``). ``run`` loads
the budgets, runs the phases one after the other over one ``Suite`` (the temp root and what the
earlier phases made), judges every row against its budget, prints the table, writes ``perf.json``
and returns the report's exit code. The real phases are ``prepare`` (fixture, copy, tool bin,
temp hub), ``process_rows`` (CLI and hooks), ``web_rows`` (start ``hub web``, register the hub,
routes, pages, stop) and ``restart_rows``. When a phase fails, the rows measured before it are
still printed and written, then the failure goes on. ``main`` maps any failure of the suite itself
(``SuiteError``, a bad budgets file, a bad knob, any other error) to exit 2 with one line, so exit
1 always means a row over its budget.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from agent_hub.core.testing.loopback import closed_url
from scripts.perf import fixture
from scripts.perf.budgets import Budget, BudgetFileError, load_budgets
from scripts.perf.environment import (
    PerfRoot,
    child_env,
    create_hub,
    make_tool_bin,
    transcript_path,
    web_argv,
)
from scripts.perf.pages import PAGE_PATHS, chromium_executable, page_env, page_rows
from scripts.perf.process_probes import SuiteError, cli_probes, hook_probes, measure
from scripts.perf.report import (
    PASSED,
    SKIPPED,
    Row,
    exit_code,
    status_of,
    summarize,
    table_text,
    write_rows,
)
from scripts.perf.web_probes import (
    measure_route,
    register_hub,
    route_probes,
    start_web,
    stop_web,
)
from scripts.perf.web_probes import (
    restart_rows as measure_restarts,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "apps" / "web"
DEFAULT_RUNS = 10
DEFAULT_RESTART_RUNS = 3
OUTPUT_TAIL = 2_000
_ON = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """The suite's knobs, each from its ``PERF_*`` variable or the plan's default."""

    events: int
    runs: int
    restart_runs: int
    strict: bool
    rebuild: bool
    out: Path
    budgets: Path
    cache: Path

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Settings:
        def number(name: str, default: int) -> int:
            return int(environ.get(name) or default)

        def flag(name: str) -> bool:
            return environ.get(name, "").strip().lower() in _ON

        def path(name: str, default: Path) -> Path:
            value = environ.get(name)
            return Path(value) if value else default

        return cls(
            events=number("PERF_EVENTS", fixture.DEFAULT_EVENTS),
            runs=number("PERF_RUNS", DEFAULT_RUNS),
            restart_runs=number("PERF_RESTART_RUNS", DEFAULT_RESTART_RUNS),
            strict=flag("PERF_STRICT"),
            rebuild=flag("PERF_REBUILD"),
            out=path("PERF_OUT", REPO_ROOT / "perf.json"),
            budgets=path("PERF_BUDGETS", REPO_ROOT / "scripts" / "perf" / "budgets.json"),
            cache=path("PERF_CACHE", REPO_ROOT / ".perf"),
        )


@dataclass
class Suite:
    """What the phases share: the settings, the temp root, and what ``prepare`` made."""

    settings: Settings
    root: Path
    commit: str = "unknown"
    hub_bin: Path = field(default_factory=Path)
    hub_dir: Path = field(default_factory=Path)
    db: Path = field(default_factory=Path)
    env: dict[str, str] = field(default_factory=dict)

    def row(
        self,
        kind: str,
        path: str,
        samples: Sequence[float],
        *,
        api_calls: int | None = None,
        rss_mb: float | None = None,
        reason: str | None = None,
    ) -> Row:
        """A row not yet judged against its budget; no samples means skipped with ``reason``."""
        summary = summarize(samples) if samples else None
        return Row(
            kind=kind,
            path=path,
            runs=len(samples),
            median_ms=summary.median_ms if summary else None,
            p95_ms=summary.p95_ms if summary else None,
            budget=None,
            status=PASSED if summary else SKIPPED,
            reason=None if summary else reason,
            api_calls=api_calls,
            rss_mb=rss_mb,
            events=self.settings.events,
            seed=fixture.SEED,
            commit=self.commit,
            machine={"platform": sys.platform, "cpus": os.cpu_count() or 0},
        )


type Phase = Callable[[Suite], Sequence[Row]]


def _judged(rows: Sequence[Row], budgets: Mapping[tuple[str, str], Budget]) -> list[Row]:
    judged = []
    for row in rows:
        budget = budgets.get((row.kind, row.path))
        judged.append(replace(row, budget=budget, status=status_of(row, budget)))
    return judged


def run(settings: Settings, phases: Sequence[Phase]) -> int:
    """Run ``phases`` in order, then print, write and judge the rows; the report's exit code."""
    budgets = load_budgets(settings.budgets)
    rows: list[Row] = []
    try:
        with PerfRoot() as root:
            suite = Suite(settings=settings, root=root.path)
            for phase in phases:
                rows.extend(phase(suite))
    except BaseException:
        if rows:
            _report(settings, rows, budgets)
        raise
    return _report(settings, rows, budgets)


def _report(
    settings: Settings, rows: Sequence[Row], budgets: Mapping[tuple[str, str], Budget]
) -> int:
    """Judge ``rows``, print the table, write ``perf.json``; the report's exit code."""
    judged = _judged(rows, budgets)
    sys.stdout.write(table_text(judged))
    settings.out.parent.mkdir(parents=True, exist_ok=True)
    write_rows(settings.out, judged)
    print(f"wrote {len(judged)} rows to {settings.out}")
    return exit_code(judged, strict=settings.strict)


def _completed(
    argv: Sequence[str],
    *,
    cwd: Path | str | None,
    env: Mapping[str, str] | None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` to the end; ``SuiteError`` with the output's tail when it exits non-zero."""
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        env=None if env is None else dict(env),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr)[-OUTPUT_TAIL:]
        raise SuiteError(f"{' '.join(argv)}: exited {completed.returncode}\n{output}")
    return completed


def _setup_runner(
    argv: Sequence[str], cwd: Path | str | None = None, env: Mapping[str, str] | None = None
) -> object:
    return _completed(argv, cwd=cwd, env=env)


def _tool(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        raise SuiteError(f"{name} not found on PATH")
    return Path(found)


def _commit() -> str:
    try:
        completed = _completed(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, env=None)
    except SuiteError, OSError:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def prepare(suite: Suite) -> list[Row]:
    """The fixture (cached), its copy, the tool bin, the child env and the temp hub."""
    settings = suite.settings
    print(f"perf: fixture of {settings.events} events in {settings.cache}", flush=True)
    cached = fixture.ensure(
        settings.cache, events=settings.events, seed=fixture.SEED, rebuild=settings.rebuild
    )
    suite.commit = _commit()
    suite.db = suite.root / "perf.db"
    shutil.copyfile(cached, suite.db)
    suite.hub_bin = Path(sys.executable).parent / "hub"
    tool_bin = make_tool_bin(
        suite.root,
        hub_bin=suite.hub_bin,
        git=_tool("git"),
        python3=_tool("python3"),
        sh=_tool("sh"),
    )
    suite.env = child_env(suite.root, db=suite.db, tool_bin=tool_bin, sensor_url=closed_url())
    suite.hub_dir = create_hub(suite.root, runner=_setup_runner, env=suite.env)
    return []


def process_rows(suite: Suite) -> list[Row]:
    """The CLI and hook rows, each command run in the temp hub with the child env."""

    def runner(argv: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return _completed(argv, cwd=suite.hub_dir, env=suite.env, stdin=stdin)

    print("perf: CLI and hooks", flush=True)
    probes = [
        *cli_probes(suite.hub_bin, suite.hub_dir),
        *hook_probes(suite.hub_dir, transcript_path(suite.env)),
    ]
    runs = suite.settings.runs
    return [
        suite.row(probe.kind, probe.path, measure(probe, runs=runs, runner=runner, clock=_clock))
        for probe in probes
    ]


def _clock() -> float:
    return time.perf_counter()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


def _web_argv(suite: Suite) -> list[str]:
    return web_argv(suite.hub_bin, port=_free_port(), db=suite.db)


def web_rows(suite: Suite) -> list[Row]:
    """Start ``hub web``, register the hub, then the route and page rows; stop it."""
    print("perf: hub web routes and pages", flush=True)
    web = start_web(_web_argv(suite), suite.env)
    try:
        register_hub(web.base_url, suite.hub_dir)
        rows = [
            suite.row(
                probe.kind,
                probe.path,
                measure_route(web.base_url, probe, runs=suite.settings.runs),
            )
            for probe in route_probes()
        ]
        rows.extend(_page_rows(suite, url=web.base_url, token=web.token))
    finally:
        stop_web(web.process)
    return rows


def _page_rows(suite: Suite, *, url: str, token: str) -> list[Row]:
    chromium = chromium_executable(os.environ, web_dir=WEB_DIR)
    npm = shutil.which("npm")
    node = shutil.which("node")
    env: Mapping[str, str] = suite.env
    if chromium is not None and node is not None:
        configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        browsers = Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"
        env = page_env(
            suite.env,
            node_dir=Path(node).parent,
            browsers=browsers,
            chromium=chromium,
            url=url,
            token=token,
        )
    found = page_rows(
        env,
        npm=npm if node is not None else None,
        chromium=chromium,
        web_dir=WEB_DIR,
        pages=PAGE_PATHS,
        runs=suite.settings.runs,
        results=suite.root / "pages.jsonl",
        runner=_setup_runner,
    )
    return [
        suite.row(
            page.kind, page.path, page.samples_ms, api_calls=page.api_calls, reason=page.reason
        )
        for page in found
    ]


def restart_rows(suite: Suite) -> list[Row]:
    """Start ``hub web`` ``PERF_RESTART_RUNS`` times: start to first HTML, to first sessions."""
    print("perf: hub web restarts", flush=True)
    found = measure_restarts(_web_argv(suite), suite.env, runs=suite.settings.restart_runs)
    return [suite.row(item.kind, item.path, item.samples_ms, rss_mb=item.rss_mb) for item in found]


PHASES: Sequence[Phase] = (prepare, process_rows, web_rows, restart_rows)


def main(environ: Mapping[str, str]) -> int:
    """``make perf``: 0, 1 when ``PERF_STRICT`` is on and a row is over, 2 when the suite fails."""
    try:
        return run(Settings.from_env(environ), PHASES)
    except (SuiteError, BudgetFileError) as error:
        print(f"make perf: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 -- exit 1 is kept for a row over its budget
        print(f"make perf: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(os.environ))
