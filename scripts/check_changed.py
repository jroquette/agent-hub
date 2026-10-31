"""``make check-changed``: the checks, and the fast tests of what a change set reaches.

The planner (``plan_change``) maps each changed path to the unit and contract tests it can break.
A package's code reaches the fast tests of every package that imports it, directly or through
others, in the ``agent_hub`` import graph; the repo's ``scripts`` are one more node there, tested
by the root ``tests/unit``. Other paths go through a table of rows (``_row``). A build file, an
absolute path, a path with a ``..`` part, a pack that does not exist or a path no row names makes
the plan full: every unit and contract test. The runner lands in a later commit.

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
  full plan from a build file alone leaves them out.
- A path is data: it never reaches an argv or a shell. A reason line shows it whole when it is
  printable and at most SHOWN_LIMIT characters long, else cut.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# A package ("core", "cli", and "scripts" for the repo's own scripts) mapped to the
# agent_hub packages its Python files name.
type Graph = Mapping[str, frozenset[str]]
# The arguments that follow "git", mapped to its stdout; None when git fails.
type Git = Callable[[Sequence[str]], str | None]
# One step's argv, mapped to its exit code and its output.
type Start = Callable[[Sequence[str]], tuple[int, str]]

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
# What only make check or CI tests (the e2e tests, the workflows, the image, git's own files,
# the import contracts), like the packages' integration tests: a change there runs the checks.
CHECKED_ELSEWHERE = ("tests/e2e/", ".github/", "docker/")
CHECKED_ELSEWHERE_FILES = frozenset(
    {"Dockerfile", "compose.yaml", ".gitattributes", ".gitignore", ".importlinter"}
)
# The most characters of a path that a reason line shows.
SHOWN_LIMIT = 200
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
    """What a change set needs: pytest targets and ignores, the extra steps, and why."""

    full: bool
    tests: tuple[str, ...]
    ignores: tuple[str, ...]
    openapi: bool
    web: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class _Row:
    """What one changed path adds to the plan; ``full`` asks for the full plan."""

    tests: frozenset[str] = frozenset()
    openapi: bool = False
    web: bool = False
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
        return _full_plan(tree, web=True, reasons=(unknown,))
    rows = [_row(path, graph, tree) for path in sorted(set(paths))]
    web = any(row.web for row in rows)
    reasons = tuple(row.reason for row in rows if row.reason is not None)
    if any(row.full for row in rows):
        return _full_plan(tree, web=web, reasons=reasons)
    # Only what exists reaches pytest, which exits 4 on a missing path.
    tests = frozenset[str]().union(*(row.tests for row in rows)) & tree.paths
    return Plan(
        full=False,
        tests=tuple(sorted(tests)),
        ignores=_ignores(tests, tree),
        openapi=any(row.openapi for row in rows),
        web=web,
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


def lanes(plan: Plan) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """The checks lane's steps and the tests lane's steps, each step an argv."""
    raise NotImplementedError


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str],
    start: Start,
    git: Git,
) -> int:
    """Print the plan, then run it unless ``--plan`` is given; returns the exit code."""
    raise NotImplementedError


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
        return _Row(tests=frozenset({PLAYGROUND_TEST} if reads else ()), web=True)
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


def _full_plan(tree: Tree, *, web: bool, reasons: tuple[str, ...]) -> Plan:
    """Every unit and contract test folder there is, and the OpenAPI check."""
    tests = tuple(sorted(path for path in tree.paths if FAST_DIR.fullmatch(path)))
    return Plan(full=True, tests=tests, ignores=(), openapi=True, web=web, reasons=reasons)


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
