"""``make check-changed``: the checks, and the fast tests of what a change set reaches.

The planner (``plan_change``) maps each changed path to the unit and contract tests it can break.
A package's code reaches the fast tests of every package that imports it, directly or through
others, in the ``agent_hub`` import graph; the repo's ``scripts`` are one more node there, tested
by the root ``tests/unit``. Other paths go through a table of rows (``_row``). A build file, an
absolute path, a path with a ``..`` part, a pack that does not exist or a path no row names makes
the plan full: every unit and contract test.

The runner (``main``) prints the plan, and with ``--plan`` stops there. Otherwise it runs
``make web-install`` first when the plan has the web steps, then two lanes at once, each stopping
at its first failed step: the checks (``format``, ``lint``, ``typecheck``, ``layout`` and
``lockstep`` on the whole tree, then the web checks and the OpenAPI check when ``api`` is
reached) and the tests (pytest on the planned targets with ``-m "unit or contract"`` and no
coverage, then the web tests). The full web steps are ``make web-static`` and ``make web-test``;
the narrowed ones are the web typecheck, ``npm run lint:changed`` (ESLint and Prettier on the
changed files) and ``npm run test:related`` (the Vitest files that import them, without
coverage), both reading the changed files from a list file the run writes. When a step fails,
the other lane is stopped: its running step's process group is killed and its next steps never
start. Each lane's output is printed when the lane ends, a failed lane's last, and the last line
names the failed step: the Stop gate keeps only the end of the output. The exit code is 0, or 1
when a step failed.

Choices behind the plan:

- The graph comes from import statements alone, at any indent: ``import agent_hub.<name>``,
  ``from agent_hub.<name> ...`` and ``from agent_hub import <name>``. A name inside a string is
  no edge: ``api`` and ``scripts`` name ``agent_hub.cli`` in commands they start, and counting
  those would put ``api``'s slow tests in the plan of every ``cli`` change.
- The changed paths come from the arguments, else ``PATHS`` (split on whitespace), else
  ``HUB_CHANGED_FILES`` (one path a line), else git: what differs from the merge base with
  ``origin/main``, plus the untracked files. A variable with no non-blank entry counts as unset.
  git never fetches; without a merge base, or when git fails, the paths are unknown.
- The web steps run when a path under ``apps/web/`` changed, or when the paths are unknown; a
  full plan from a build file alone leaves them out. They are narrowed when every changed web
  path is a ``.ts`` or ``.tsx`` file under ``apps/web/src/`` (WEB_SOURCE), which Vitest's module
  graph can relate to its tests; Vitest itself runs every test file for a change to its setup
  file. Any other web path (a config, package.json, a stylesheet, a Playwright spec, the design
  tokens) or an unknown change set keeps the full web steps. The typecheck always covers the
  whole app, so a deleted or renamed source still fails where it is imported.
- A path is data: it never reaches an argv or a shell. The narrowed web steps read the changed
  files from a list file, one a line, relative to the web app. A reason line shows a path whole
  when it is printable and at most SHOWN_LIMIT characters long, else cut.
"""

import argparse
import contextlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

# A package ("core", "cli", and "scripts" for the repo's own scripts) mapped to the
# agent_hub packages its Python files name.
type Graph = Mapping[str, frozenset[str]]
# The arguments that follow "git", mapped to its stdout; None when git fails.
type Git = Callable[[Sequence[str]], str | None]
# One step's argv and the run's stop event, mapped to its exit code and its output. Once the
# event is set, a running step ends early (its exit code then says nothing).
type Start = Callable[[Sequence[str], threading.Event], tuple[int, str]]

REPO_ROOT = Path(__file__).resolve().parent.parent
# make runs the targets that follow one after the other (LANE=1) and stops at the first failure.
IN_ORDER = ("make", "--no-print-directory", "LANE=1")
CHECKS = ("format", "lint", "typecheck", "layout", "lockstep")
WEB_INSTALL = (*IN_ORDER, "web-install")
SCRIPTS = "scripts"
ROOT_UNIT = "tests/unit"
CORE_UNIT = "packages/core/tests/unit"
BUILTIN = "packages/core/src/agent_hub/core/workflows/builtin"
PACK_TESTS = f"{CORE_UNIT}/workflows/builtin"
# Core's tests that read the source files of every package, pack scripts included: a source
# change can break them with no import to show it.
SCAN_FILES = (
    f"{CORE_UNIT}/hub_config/test_model.py",
    f"{CORE_UNIT}/hub_config/test_conventions.py",
)
# The root unit tests that read the docs: the llms files, the flow catalog, the budgets' ADR.
DOCS_TESTS = (
    "tests/unit/scripts/test_build_llms_txt.py",
    "tests/unit/scripts/test_build_flow_catalog.py",
    "tests/unit/scripts/perf/test_budgets.py",
)
# The release pack's tests read README.md.
BUMP_TEST = f"{PACK_TESTS}/release/scripts/test_bump.py"
OPENAPI_JSON = "packages/api/openapi.json"
OPENAPI_TEST = "tests/unit/scripts/test_export_openapi.py"
# Reads the web app's routes.tsx and screens folder.
PLAYGROUND_TEST = "tests/unit/scripts/test_playground_export.py"
# The retro pack's tests read this integration golden.
RETRO_GOLDEN = "packages/generator/tests/integration/golden/retro_metrics/full.golden"
NAMED_FILES = (*SCAN_FILES, *DOCS_TESTS, BUMP_TEST, OPENAPI_TEST, PLAYGROUND_TEST)
# A file of one of these names, in any folder, changes how every test runs.
BUILD_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "conftest.py",
        "pytest.ini",
        "mypy.ini",
        "Makefile",
        ".python-version",
    }
)
LEVELS_PLUGIN = "scripts/pytest_levels.py"
LLMS_FILES = frozenset({"llms.txt", "llms-full.txt"})
WEB = "apps/web/"
# A web source the narrowed web steps can take: a .ts or .tsx file under src/, of plain
# characters (no space, no line break), so one line of the list file holds it.
WEB_SOURCE = re.compile(r"apps/web/src/[A-Za-z0-9_@./-]+\.tsx?")
# The narrowed web steps (apps/web/package.json): the typecheck of the whole app, then ESLint and
# Prettier on the changed files, and the Vitest files that import them; the last two read the
# list file named last.
WEB_RUN = ("npm", "--prefix", "apps/web", "run")
WEB_TYPECHECK = (*WEB_RUN, "typecheck")
WEB_LINT_CHANGED = (*WEB_RUN, "lint:changed", "--")
WEB_TEST_RELATED = (*WEB_RUN, "test:related", "--")
WEB_LIST_NAME = "web-files.txt"
# Each step runs under this guard (scripts/step_guard.py); how often a running step looks at the
# run's stop event.
STEP_GUARD = (sys.executable, "-m", "scripts.step_guard")
STOP_POLL_S = 0.2
# What only make check or CI tests (the e2e tests, the workflows, the image, git's own files,
# the import contracts), like the packages' integration tests: a change there runs the checks.
CHECKED_ELSEWHERE = ("tests/e2e/", ".github/", "docker/")
CHECKED_ELSEWHERE_FILES = frozenset(
    {"Dockerfile", "compose.yaml", ".gitattributes", ".gitignore", ".importlinter"}
)
# The most characters of a path that a reason line shows.
SHOWN_LIMIT = 200
# The most reason lines the printed plan holds, then one line counts the rest: HUB_CHANGED_FILES
# alone may name thousands of paths.
REASONS_SHOWN = 20
# The three import statements that name an agent_hub package, at any indent.
IMPORT = re.compile(
    r"^[ \t]*(?:import[ \t]+agent_hub\.(\w+)|from[ \t]+agent_hub\.(\w+)"
    r"|from[ \t]+agent_hub[ \t]+import[ \t]+(\w+))",
    re.MULTILINE,
)
# A package's code, or its test data, which other packages' tests read too.
SOURCE = re.compile(r"packages/([^/]+)/(src|tests/data)/.+")
FAST_TEST = re.compile(r"packages/([^/]+)/tests/(?:unit|contract)/.+")
INTEGRATION_TEST = re.compile(r"packages/[^/]+/tests/integration/.+")
FAST_DIR = re.compile(r"(?:packages/[^/]+/)?tests/(?:unit|contract)")
MERGE_BASE = ("merge-base", "HEAD", "origin/main")
UNTRACKED = ("ls-files", "--others", "--exclude-standard")


@dataclass(frozen=True, kw_only=True, slots=True)
class Tree:
    """What exists for the planner to name: test folders and files, and the built-in packs."""

    paths: frozenset[str]
    packs: frozenset[str]


@dataclass(frozen=True, kw_only=True, slots=True)
class Plan:
    """What a change set needs: pytest targets and ignores, the extra steps, and why.

    ``web_files`` are the changed web sources the narrowed web steps take; with ``web`` and no
    ``web_files``, the web steps run in full.
    """

    full: bool
    tests: tuple[str, ...]
    ignores: tuple[str, ...]
    openapi: bool
    web: bool
    reasons: tuple[str, ...]
    web_files: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class _Row:
    """What one changed path adds to the plan; ``full`` asks for the full plan, and
    ``web_file`` names a web source the narrowed web steps can take."""

    tests: frozenset[str] = frozenset()
    openapi: bool = False
    web: bool = False
    web_file: str | None = None
    full: bool = False
    reason: str | None = None


def import_graph(root: Path) -> Graph:
    """The packages under ``root`` and the ``agent_hub`` packages each one names."""
    folders = {folder.name: folder for folder in root.glob("packages/*/src/agent_hub/*/")}
    folders[SCRIPTS] = root / SCRIPTS
    return {name: _imports(folder) for name, folder in folders.items()}


def dependents(graph: Graph, name: str) -> frozenset[str]:
    """``name`` and every package that reaches it in ``graph``."""
    reached = {name}
    while more := {user for user, used in graph.items() if used & reached} - reached:
        reached |= more
    return frozenset(reached)


def read_tree(root: Path) -> Tree:
    """The test folders, test files and built-in packs that exist under ``root``."""
    candidates = [
        *root.glob("packages/*/tests/unit"),
        *root.glob("packages/*/tests/contract"),
        *root.glob(f"{PACK_TESTS}/*"),
        root / ROOT_UNIT,
        *(root / name for name in NAMED_FILES),
    ]
    return Tree(
        paths=frozenset(path.relative_to(root).as_posix() for path in candidates if path.exists()),
        packs=frozenset(folder.name for folder in root.glob(f"{BUILTIN}/*/")),
    )


def plan_change(paths: Sequence[str] | None, graph: Graph, tree: Tree) -> Plan:
    """The plan for ``paths``; None, an unknown change set, gets the full plan."""
    if paths is None:
        unknown = "full: the changed paths are unknown (no origin/main, or git failed)"
        return _full_plan(tree, web=True, web_files=(), reasons=(unknown,))
    rows = [_row(path, graph, tree) for path in sorted(set(paths))]
    web_rows = [row for row in rows if row.web]
    web_files = tuple(row.web_file for row in web_rows if row.web_file is not None)
    narrowed = web_files if len(web_files) == len(web_rows) else ()
    reasons = tuple(row.reason for row in rows if row.reason is not None)
    if any(row.full for row in rows):
        return _full_plan(tree, web=bool(web_rows), web_files=narrowed, reasons=reasons)
    # Only what exists reaches pytest, which exits 4 on a missing path.
    tests = frozenset[str]().union(*(row.tests for row in rows)) & tree.paths
    return Plan(
        full=False,
        tests=tuple(sorted(tests)),
        ignores=_ignores(tests, tree),
        openapi=any(row.openapi for row in rows),
        web=bool(web_rows),
        web_files=narrowed,
        reasons=reasons,
    )


def change_set(
    argv: Sequence[str], environ: Mapping[str, str], git: Git
) -> tuple[str, tuple[str, ...] | None]:
    """Where the changed paths come from, and the paths (None when they cannot be known)."""
    if argv:
        return "argv", tuple(argv)
    paths = environ.get("PATHS", "").split()
    if paths:
        return "PATHS", tuple(paths)
    lines = environ.get("HUB_CHANGED_FILES", "").splitlines()
    changed = [line for line in lines if line.strip()]
    if changed:
        return "HUB_CHANGED_FILES", tuple(changed)
    return "git", _git_paths(git)


def lanes(
    plan: Plan, *, web_list: str
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """The checks lane's steps and the tests lane's steps, each step an argv; ``web_list`` is
    the file the narrowed web steps read the changed files from."""
    full_web = plan.web and not plan.web_files
    checks: list[tuple[str, ...]] = [(*IN_ORDER, *CHECKS, *(("web-static",) if full_web else ()))]
    if plan.web_files:
        checks += [WEB_TYPECHECK, (*WEB_LINT_CHANGED, web_list)]
    if plan.openapi:
        checks.append((sys.executable, "-m", "scripts.export_openapi", "--check"))
    tests: list[tuple[str, ...]] = []
    # With no target, pytest would collect every test folder: no pytest step at all then. No
    # coverage either, so the data make coverage reads stays the gates'.
    if plan.tests:
        ignores = (f"--ignore={path}" for path in plan.ignores)
        marker = ("-m", "unit or contract")
        tests.append((sys.executable, "-m", "pytest", *marker, "-n", "auto", *plan.tests, *ignores))
    if full_web:
        tests.append((*IN_ORDER, "web-test"))
    if plan.web_files:
        tests.append((*WEB_TEST_RELATED, web_list))
    return tuple(checks), tuple(tests)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str],
    start: Start,
    git: Git,
) -> int:
    """Print the plan, then run it unless ``--plan`` is given; returns the exit code."""
    arguments = _parser().parse_args(argv)
    paths: list[str] = arguments.paths
    source, changed = change_set(paths, environ, git)
    plan = plan_change(changed, import_graph(REPO_ROOT), read_tree(REPO_ROOT))
    print(_described(source, changed, plan), flush=True)
    if arguments.plan:
        return 0
    return _run(plan, start)


# The planner's rows.


def _row(path: str, graph: Graph, tree: Tree) -> _Row:
    """What ``path`` adds to the plan: the first row that names it."""
    parts = path.split("/")
    if path.startswith("/") or ".." in parts:
        return _unknown(path)
    if parts[-1] in BUILD_FILES or path == LEVELS_PLUGIN:
        return _Row(full=True, reason=f"full: build file {_shown(path)}")
    if path.startswith((f"{BUILTIN}/", f"{PACK_TESTS}/")):
        return _pack_row(path, graph, tree)
    if parts[0] == "packages":
        return _package_row(path, graph)
    return _root_row(path)


def _pack_row(path: str, graph: Graph, tree: Tree) -> _Row:
    """A path in a built-in pack, or in one pack's tests."""
    if path.startswith(f"{PACK_TESTS}/"):
        pack = path.removeprefix(f"{PACK_TESTS}/").split("/")[0]
        return _Row(tests=frozenset({f"{PACK_TESTS}/{pack}"}))
    pack, _, rest = path.removeprefix(f"{BUILTIN}/").partition("/")
    if pack not in tree.packs:
        return _Row(full=True, reason=f"full: unknown pack in {_shown(path)}")
    pack_tests = f"{PACK_TESTS}/{pack}"
    if rest.startswith("scripts/"):
        # A pack's scripts import no agent_hub module; the generator seeds and reads the packs.
        return _Row(tests=frozenset({pack_tests, *_fast_dirs("generator"), *SCAN_FILES}))
    core = _source_row(graph, "core", scans=True)
    return _Row(tests=core.tests | {pack_tests}, openapi=core.openapi)


def _package_row(path: str, graph: Graph) -> _Row:
    """A path under packages/ outside the built-in packs."""
    if path == OPENAPI_JSON:
        return _Row(tests=frozenset({OPENAPI_TEST}), openapi=True)
    if path == RETRO_GOLDEN:
        return _Row(tests=frozenset({f"{PACK_TESTS}/retro"}))
    if (source := SOURCE.fullmatch(path)) and source[1] in graph:
        return _source_row(graph, source[1], scans=source[2] == "src")
    if test := FAST_TEST.fullmatch(path):
        return _Row(tests=frozenset(_fast_dirs(test[1])))
    if INTEGRATION_TEST.fullmatch(path):
        return _checked_elsewhere(path)
    return _unknown(path)


def _root_row(path: str) -> _Row:
    """A path outside packages/."""
    if path.startswith((f"{SCRIPTS}/", f"{ROOT_UNIT}/")):
        return _Row(tests=frozenset({ROOT_UNIT}))
    if _is_doc(path):
        return _Row(tests=frozenset({*DOCS_TESTS, *((BUMP_TEST,) if path == "README.md" else ())}))
    if path.startswith(WEB):
        reads = path == f"{WEB}src/routes.tsx" or path.startswith(f"{WEB}src/screens/")
        tests = frozenset({PLAYGROUND_TEST} if reads else ())
        if WEB_SOURCE.fullmatch(path):
            return _Row(tests=tests, web=True, web_file=path)
        why = f"only .ts and .tsx files under {WEB}src/ narrow them"
        return _Row(tests=tests, web=True, reason=f"{_shown(path)}: the full web steps ({why})")
    if "/" not in path and path.endswith(".log"):
        return _Row(reason=f"{_shown(path)}: a scratch log at the top, so the checks alone")
    if path.startswith(CHECKED_ELSEWHERE) or path in CHECKED_ELSEWHERE_FILES:
        return _checked_elsewhere(path)
    return _unknown(path)


def _source_row(graph: Graph, package: str, *, scans: bool) -> _Row:
    """A change to ``package``'s code or test data: the fast tests of every package it reaches."""
    reached = dependents(graph, package)
    tests = {folder for name in reached for folder in _fast_dirs(name)}
    return _Row(tests=frozenset({*tests, *(SCAN_FILES if scans else ())}), openapi="api" in reached)


def _fast_dirs(name: str) -> tuple[str, ...]:
    """The unit and contract test folders of a graph node; the scripts have the root ones."""
    if name == SCRIPTS:
        return (ROOT_UNIT,)
    return (f"packages/{name}/tests/unit", f"packages/{name}/tests/contract")


def _is_doc(path: str) -> bool:
    """A file under docs/, a Markdown file at the top, or one of the llms files."""
    at_top = "/" not in path
    return path.startswith("docs/") or path in LLMS_FILES or (at_top and path.endswith(".md"))


def _checked_elsewhere(path: str) -> _Row:
    return _Row(reason=f"{_shown(path)}: the checks alone; make check or CI tests it")


def _unknown(path: str) -> _Row:
    return _Row(full=True, reason=f"full: unknown path {_shown(path)}")


def _full_plan(
    tree: Tree, *, web: bool, web_files: tuple[str, ...], reasons: tuple[str, ...]
) -> Plan:
    """Every unit and contract test folder there is, and the OpenAPI check."""
    tests = tuple(sorted(path for path in tree.paths if FAST_DIR.fullmatch(path)))
    return Plan(
        full=True,
        tests=tests,
        ignores=(),
        openapi=True,
        web=web,
        web_files=web_files,
        reasons=reasons,
    )


def _ignores(tests: frozenset[str], tree: Tree) -> tuple[str, ...]:
    """The pack-script tests a plan with core's unit tests leaves out (they import no core code).

    pytest drops a target that lies under an ignored folder, so when the plan names some packs'
    tests, each other pack's folder is ignored instead of the folder that holds them all.
    """
    if CORE_UNIT not in tests:
        return ()
    prefix = f"{PACK_TESTS}/"
    named = {test.removeprefix(prefix).split("/")[0] for test in tests if test.startswith(prefix)}
    if not named:
        return (PACK_TESTS,)
    folders = (f"{prefix}{pack}" for pack in tree.packs - named)
    return tuple(sorted(folder for folder in folders if folder in tree.paths))


def _shown(path: str) -> str:
    """``path`` for a reason line: whole when printable and short, else cut with ``…``."""
    kept = path[:SHOWN_LIMIT]
    end = next((index for index, char in enumerate(kept) if not char.isprintable()), len(kept))
    return path if end == len(path) else f"{path[:end]}…"


# The runner.


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the checks, and the fast tests of what the changed paths reach."
    )
    parser.add_argument("--plan", action="store_true", help="print the plan and run nothing")
    parser.add_argument(
        "paths", nargs="*", help="the changed paths (default: PATHS, HUB_CHANGED_FILES, git)"
    )
    return parser


def _described(source: str, paths: Sequence[str] | None, plan: Plan) -> str:
    """The plan as lines: how many paths and from where, why, the pytest targets, the steps."""
    count = "unknown" if paths is None else str(len(set(paths)))
    lines = [
        f"check-changed: changed paths from {source}: {count}",
        f"  plan: {'full' if plan.full else 'narrowed'}",
        *_capped("reason", plan.reasons),
        *(f"  test: {target}" for target in plan.tests or ("none",)),
        *(f"  ignore: {path}" for path in plan.ignores),
        f"  openapi check: {'yes' if plan.openapi else 'no'}",
        f"  web steps: {_web_steps(plan)}",
        *_capped("web file", plan.web_files),
    ]
    return "\n".join(lines)


def _capped(label: str, items: Sequence[str]) -> list[str]:
    """One line per item up to REASONS_SHOWN, then one line that counts the rest."""
    hidden = len(items) - REASONS_SHOWN
    shown = [f"  {label}: {item}" for item in items[:REASONS_SHOWN]]
    return [*shown, *([f"  {label}: … and {hidden} more"] if hidden > 0 else [])]


def _web_steps(plan: Plan) -> str:
    if not plan.web:
        return "no"
    if not plan.web_files:
        return "full (make web-static, make web-test)"
    count = len(plan.web_files)
    files = f"{count} file{'s' if count > 1 else ''}"
    return f"narrowed: the typecheck, then ESLint, Prettier and related Vitest tests for {files}"


@dataclass(frozen=True, kw_only=True, slots=True)
class _LaneEnd:
    """A lane's output, and the step that failed or the one the stop ended (or never started)."""

    output: str
    failed: tuple[str, ...] | None = None
    stopped: tuple[str, ...] | None = None


def _run(plan: Plan, start: Start) -> int:
    """Run the plan's steps; 1 when one fails."""
    stop = threading.Event()
    if plan.web:
        # Before the lanes, which would otherwise both install at once.
        code, output = start(WEB_INSTALL, stop)
        _show(output)
        if code != 0:
            print(_failure(WEB_INSTALL))
            return 1
    with tempfile.TemporaryDirectory(prefix="check-changed-") as folder:
        web_list = Path(folder) / WEB_LIST_NAME
        web_list.write_text("".join(f"{path.removeprefix(WEB)}\n" for path in plan.web_files))
        failures = _run_lanes(lanes(plan, web_list=str(web_list)), start, stop)
    for output, _ in failures:
        _show(output)
    for _, failed in failures:
        print(_failure(failed))
    return 1 if failures else 0


def _run_lanes(
    steps: Sequence[Sequence[tuple[str, ...]]], start: Start, stop: threading.Event
) -> list[tuple[str, tuple[str, ...]]]:
    """Run each lane in a thread; the first failure stops the others. Prints each lane that
    passed or was stopped when it ends; returns the failed ones' output and failed step."""
    failures: list[tuple[str, tuple[str, ...]]] = []
    with ThreadPoolExecutor(max_workers=len(steps)) as pool:
        try:
            running = [pool.submit(_run_lane, lane, start, stop) for lane in steps]
            for done in as_completed(running):
                end = done.result()
                if end.failed is not None:
                    stop.set()
                    failures.append((end.output, end.failed))
                    continue
                _show(end.output)
                if end.stopped is not None:
                    print(f"check-changed: stopped, another lane failed: {shlex.join(end.stopped)}")
        except BaseException:
            # Ctrl-C reaches this thread only, and each step runs in a process group of its own:
            # stop them before the pool waits for its threads.
            stop.set()
            raise
    return failures


def _run_lane(steps: Sequence[tuple[str, ...]], start: Start, stop: threading.Event) -> _LaneEnd:
    """Run ``steps`` in order up to the first that fails, or until the run stops. The lanes
    start together: a lane's first step starts even when the other lane already failed (the
    stop then ends it at once), so what a lane runs never hangs on which thread came first."""
    outputs: list[str] = []
    for index, step in enumerate(steps):
        if index > 0 and stop.is_set():
            return _LaneEnd(output="".join(outputs), stopped=step)
        code, output = start(step, stop)
        outputs.append(output)
        if code != 0 and stop.is_set():
            return _LaneEnd(output="".join(outputs), stopped=step)
        if code != 0:
            return _LaneEnd(output="".join(outputs), failed=step)
    return _LaneEnd(output="".join(outputs))


def _show(output: str) -> None:
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)


def _failure(step: Sequence[str]) -> str:
    return f"check-changed: failed: {shlex.join(step)}"


# Reading the change set and the checkout.


def _git_paths(git: Git) -> tuple[str, ...] | None:
    """What differs from the merge base with origin/main, and the untracked files; None when
    there is no merge base or git fails."""
    base = (git(MERGE_BASE) or "").strip()
    if not base:
        return None
    changed = git(("diff", "--name-only", "--no-renames", base))
    untracked = git(UNTRACKED)
    if changed is None or untracked is None:
        return None
    return tuple(line for line in (*changed.splitlines(), *untracked.splitlines()) if line)


def _imports(folder: Path) -> frozenset[str]:
    """The agent_hub packages that the import statements in ``folder``'s Python files name."""
    return frozenset(
        name
        for path in folder.rglob("*.py")
        for match in IMPORT.finditer(path.read_text("utf-8", errors="replace"))
        for name in match.groups()
        if name is not None
    )


# The real steps and git, for a run from make or by hand.


def start_step(argv: Sequence[str], stop: threading.Event) -> tuple[int, str]:
    """Run one step from the checkout top, its stdout and stderr together, with no shell.

    The step runs under ``scripts.step_guard``, in a process group of its own, while this
    process holds a pipe to the guard open; closing it once ``stop`` is set (or this process
    ending, however it ends) makes the guard end the step and everything it started.
    """
    keep, alive = os.pipe()
    try:
        child = subprocess.Popen(
            [*STEP_GUARD, str(keep), *argv],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            pass_fds=(keep,),
        )
    except BaseException:
        os.close(alive)
        raise
    finally:
        os.close(keep)
    # The pipe is closed before the child is waited for, whatever ends the loop.
    with child, contextlib.ExitStack() as held:
        held.callback(os.close, alive)
        while True:
            try:
                output, _ = child.communicate(timeout=STOP_POLL_S)
            except subprocess.TimeoutExpired:
                if stop.is_set():
                    held.close()  # closes the pipe once; the guard then ends the step's group
                continue
            return child.returncode, output


def _run_git(args: Sequence[str]) -> str | None:
    """git's stdout for ``args`` in the checkout; None when git exits non-zero or cannot start."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


if __name__ == "__main__":
    sys.exit(main(environ=os.environ, start=start_step, git=_run_git))
