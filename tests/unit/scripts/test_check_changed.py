"""``make check-changed`` (``scripts/check_changed.py``): the plan a change set gets, and the
steps a run starts.

Planner tests use the small graph and tree below, except those whose name ends in ``in_repo``:
they read this checkout's own packages and test folders. Runner tests plan from this checkout
too. git and every step are fakes: no process starts.
"""

import itertools
import re
import shlex
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts.check_changed import (
    Graph,
    Plan,
    Tree,
    change_set,
    import_graph,
    main,
    plan_change,
    read_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN = "packages/core/src/agent_hub/core/workflows/builtin"
PACK_TESTS = "packages/core/tests/unit/workflows/builtin"
SCAN_FILES = (
    "packages/core/tests/unit/hub_config/test_model.py",
    "packages/core/tests/unit/hub_config/test_conventions.py",
)
PLAYGROUND = "tests/unit/scripts/test_playground_export.py"
STORAGE_DB = "packages/storage/src/agent_hub/storage/db.py"
CORE_ERRORS = "packages/core/src/agent_hub/core/errors.py"
HUB_GIT_SOURCE = "packages/hub_git/src/agent_hub/hub_git/git_runner.py"
CLI_SOURCE = "packages/cli/src/agent_hub/cli/main.py"
MCP_SERVER_SOURCE = "packages/mcp_server/src/agent_hub/mcp_server/server.py"
FLAKY_SCRIPT = f"{BUILTIN}/flaky/scripts/repeat.py"
WEB_COMPONENT = "apps/web/src/components/Dialog.tsx"

# The fast test folders of the small tree: cli and mcp_server have no contract tests.
FAST_DIRS = (
    "packages/api/tests/contract",
    "packages/api/tests/unit",
    "packages/cli/tests/unit",
    "packages/core/tests/contract",
    "packages/core/tests/unit",
    "packages/generator/tests/contract",
    "packages/generator/tests/unit",
    "packages/hub_git/tests/contract",
    "packages/hub_git/tests/unit",
    "packages/mcp_server/tests/unit",
    "packages/storage/tests/contract",
    "packages/storage/tests/unit",
    "tests/unit",
)
TREE = Tree(
    paths=frozenset(
        {
            *FAST_DIRS,
            *SCAN_FILES,
            PLAYGROUND,
            PACK_TESTS,
            f"{PACK_TESTS}/flaky",
            f"{PACK_TESTS}/release",
        }
    ),
    packs=frozenset({"flaky", "issue-to-pr", "release"}),
)
# cli reaches hub_git only through mcp_server, and the repo's scripts reach storage only
# through api: a plan that follows direct imports alone misses them.
GRAPH: Graph = {
    "core": frozenset(),
    "generator": frozenset({"core"}),
    "storage": frozenset({"core"}),
    "hub_git": frozenset({"core"}),
    "mcp_server": frozenset({"core", "hub_git"}),
    "api": frozenset({"core", "generator", "storage"}),
    "cli": frozenset({"api", "core", "mcp_server", "storage"}),
    "scripts": frozenset({"api", "core"}),
}
# What a storage source change runs, in the small graph and in this checkout alike.
STORAGE_PLAN = (
    "packages/storage/tests/unit",
    "packages/storage/tests/contract",
    "packages/cli/tests/unit",
    "packages/api/tests/unit",
    "packages/api/tests/contract",
    "tests/unit",
    *SCAN_FILES,
)
HUB_GIT_PLAN = (
    "packages/hub_git/tests/unit",
    "packages/hub_git/tests/contract",
    "packages/mcp_server/tests/unit",
    "packages/cli/tests/unit",
    *SCAN_FILES,
)
FLAKY_PLAN = (
    f"{PACK_TESTS}/flaky",
    "packages/generator/tests/unit",
    "packages/generator/tests/contract",
    *SCAN_FILES,
)
# Every package's fast test folders in this checkout, and the root unit tests.
EVERY_FAST_DIR = (
    "packages/api/tests/contract",
    "packages/api/tests/unit",
    "packages/claude_sessions/tests/contract",
    "packages/claude_sessions/tests/unit",
    "packages/cli/tests/unit",
    "packages/collector/tests/unit",
    "packages/core/tests/contract",
    "packages/core/tests/unit",
    "packages/generator/tests/contract",
    "packages/generator/tests/unit",
    "packages/hub_git/tests/contract",
    "packages/hub_git/tests/unit",
    "packages/mcp_server/tests/unit",
    "packages/storage/tests/contract",
    "packages/storage/tests/unit",
    "packages/tracker_linear/tests/contract",
    "packages/tracker_linear/tests/unit",
    "tests/unit",
)
BASE = "4f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d"
MERGE_BASE = ("merge-base", "HEAD", "origin/main")
DIFF = ("diff", "--name-only", "--no-renames", BASE)
UNTRACKED = ("ls-files", "--others", "--exclude-standard")
GIT_PATHS = ("m.py", "n/o.py", "new.txt")
NETWORK_GIT = frozenset({"fetch", "pull", "ls-remote", "remote", "clone"})


@dataclass
class FakeGit:
    """git without a process: the scripted stdout of each argv, None (a failed git) otherwise."""

    answers: Mapping[tuple[str, ...], str | None]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str]) -> str | None:
        self.calls.append(tuple(argv))
        return self.answers.get(tuple(argv))


def _git_with_origin() -> FakeGit:
    return FakeGit({MERGE_BASE: f"{BASE}\n", DIFF: "m.py\nn/o.py\n", UNTRACKED: "new.txt\n"})


def _covers(targets: Sequence[str], path: str) -> bool:
    """Whether pytest given ``targets`` collects ``path``: one is the path or a folder above it."""
    return any(target in {".", path} or path.startswith(f"{target}/") for target in targets)


def _full_view(plan: Plan) -> tuple[bool, list[str], tuple[str, ...]]:
    """Whether ``plan`` is full, the small tree's fast folders it misses, and what it ignores."""
    return (
        plan.full,
        [folder for folder in FAST_DIRS if not _covers(plan.tests, folder)],
        plan.ignores,
    )


def _fast_dirs_on_disk() -> list[str]:
    found = [
        *REPO_ROOT.glob("packages/*/tests/unit"),
        *REPO_ROOT.glob("packages/*/tests/contract"),
        REPO_ROOT / "tests" / "unit",
    ]
    return [path.relative_to(REPO_ROOT).as_posix() for path in found if path.is_dir()]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(HUB_GIT_SOURCE, HUB_GIT_PLAN, id="hub-git"),
        pytest.param(STORAGE_DB, STORAGE_PLAN, id="storage"),
    ],
)
def test_runs_dependents_tests_when_package_source_changes(
    path: str, expected: tuple[str, ...]
) -> None:
    plan = plan_change([path], GRAPH, TREE)

    assert sorted(plan.tests) == sorted(expected)
    assert (plan.full, plan.ignores) == (False, ())


def test_runs_storage_dependents_when_storage_source_changes_in_repo() -> None:
    assert [target for target in STORAGE_PLAN if not (REPO_ROOT / target).exists()] == []
    assert not (REPO_ROOT / "packages/cli/tests/contract").exists()

    plan = plan_change([STORAGE_DB], import_graph(REPO_ROOT), read_tree(REPO_ROOT))

    assert sorted(plan.tests) == sorted(STORAGE_PLAN)
    assert (plan.full, plan.web, plan.ignores) == (False, False, ())


# api and the repo's scripts name agent_hub.cli only in the commands they start, which is no
# import; cli imports mcp_server only inside its functions, which is one.
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(CLI_SOURCE, ("packages/cli/tests/unit", *SCAN_FILES), id="cli"),
        pytest.param(
            MCP_SERVER_SOURCE,
            ("packages/mcp_server/tests/unit", "packages/cli/tests/unit", *SCAN_FILES),
            id="mcp-server",
        ),
    ],
)
def test_runs_only_importers_tests_when_cli_or_mcp_server_source_changes_in_repo(
    path: str, expected: tuple[str, ...]
) -> None:
    assert [target for target in expected if not (REPO_ROOT / target).exists()] == []

    plan = plan_change([path], import_graph(REPO_ROOT), read_tree(REPO_ROOT))

    assert sorted(plan.tests) == sorted(expected)
    assert (plan.full, plan.openapi, plan.web, plan.ignores) == (False, False, False, ())


def test_reads_each_import_form_when_graph_built(tmp_path: Path) -> None:
    # One package per import form, one of them inside a function; a name in a string is none.
    sources = {
        "alpha": "import agent_hub.beta\n",
        "beta": "from agent_hub import gamma\n",
        "gamma": "def load() -> None:\n    from agent_hub.delta import run\n",
        "delta": '"""Starts agent_hub.alpha."""\nCOMMAND = "python -m agent_hub.alpha"\n',
    }
    for name, text in sources.items():
        folder = tmp_path / "packages" / name / "src" / "agent_hub" / name
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(text, "utf-8")
    (tmp_path / "scripts").mkdir()

    graph = import_graph(tmp_path)

    assert graph == {
        "alpha": frozenset({"beta"}),
        "beta": frozenset({"gamma"}),
        "gamma": frozenset({"delta"}),
        "delta": frozenset(),
        "scripts": frozenset(),
    }


@pytest.mark.parametrize(
    ("path", "missing"),
    [
        pytest.param(
            "packages/cli/src/agent_hub/cli/main.py", "packages/cli/tests/contract", id="cli"
        ),
        pytest.param(
            f"{BUILTIN}/issue-to-pr/scripts/open_pr.py",
            f"{PACK_TESTS}/issue-to-pr",
            id="pack-without-tests",
        ),
    ],
)
def test_lists_only_existing_dirs_when_package_has_no_contract_tests(
    path: str, missing: str
) -> None:
    assert missing not in TREE.paths
    assert "issue-to-pr" in TREE.packs

    plan = plan_change([path], GRAPH, TREE)

    assert (plan.full, bool(plan.tests)) == (False, True)
    assert sorted(set(plan.tests) - TREE.paths) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(CORE_ERRORS, id="source"),
        pytest.param("packages/core/tests/data/scenarios/sample.yaml", id="test-data"),
    ],
)
def test_skips_pack_tests_when_core_source_changes(path: str) -> None:
    assert f"{PACK_TESTS}/flaky" in TREE.paths

    plan = plan_change([path], GRAPH, TREE)

    assert (plan.full, plan.ignores) == (False, (PACK_TESTS,))
    assert "packages/core/tests/unit" in plan.tests
    assert [target for target in plan.tests if _covers((PACK_TESTS,), target)] == []


def test_runs_every_package_when_core_source_changes_in_repo() -> None:
    assert sorted(_fast_dirs_on_disk()) == sorted(EVERY_FAST_DIR)

    plan = plan_change([CORE_ERRORS], import_graph(REPO_ROOT), read_tree(REPO_ROOT))

    assert plan.full is False
    assert [folder for folder in EVERY_FAST_DIR if folder not in plan.tests] == []
    assert [target for target in plan.tests if not _covers(EVERY_FAST_DIR, target)] == []


def test_runs_pack_and_generator_tests_when_pack_script_changes_in_repo() -> None:
    assert [target for target in FLAKY_PLAN if not (REPO_ROOT / target).exists()] == []

    plan = plan_change([FLAKY_SCRIPT], import_graph(REPO_ROOT), read_tree(REPO_ROOT))

    assert sorted(plan.tests) == sorted(FLAKY_PLAN)
    assert (plan.full, plan.ignores) == (False, ())


def test_runs_web_steps_and_no_package_tests_when_only_web_changes_in_repo() -> None:
    plan = plan_change(
        [WEB_COMPONENT, "apps/web/package.json"], import_graph(REPO_ROOT), read_tree(REPO_ROOT)
    )

    assert (plan.full, plan.web, plan.tests) == (False, True, ())


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("apps/web/src/routes.tsx", (PLAYGROUND,), id="routes"),
        pytest.param("apps/web/src/screens/health/index.tsx", (PLAYGROUND,), id="screens"),
        pytest.param(WEB_COMPONENT, (), id="component"),
    ],
)
def test_runs_playground_test_when_routes_or_screens_change(
    path: str, expected: tuple[str, ...]
) -> None:
    assert PLAYGROUND in TREE.paths

    plan = plan_change([path], GRAPH, TREE)

    assert plan.tests == expected


@pytest.mark.parametrize(
    "path",
    [
        STORAGE_DB,
        "docs/TESTING.md",
        "scripts/seed_demo.py",
        ".github/workflows/ci.yml",
        "check.log",
        "uv.lock",
    ],
)
def test_runs_no_web_step_when_no_web_path_changes(path: str) -> None:
    plan = plan_change([path], GRAPH, TREE)

    assert plan.web is False


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "packages/storage/pyproject.toml",
        "uv.lock",
        "conftest.py",
        "tests/unit/conftest.py",
        "packages/storage/tests/unit/conftest.py",
        "pytest.ini",
        "mypy.ini",
        "Makefile",
        ".python-version",
        "scripts/pytest_levels.py",
    ],
)
def test_plans_full_when_build_file_changes(path: str) -> None:
    plan = plan_change([path], GRAPH, TREE)

    assert _full_view(plan) == (True, [], ())


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("notes/todo.txt", id="no-row"),
        pytest.param("packages/storage/README.md", id="package-readme"),
        pytest.param(f"/{STORAGE_DB}", id="absolute"),
        pytest.param("packages/storage/src/../../cli/src/agent_hub/cli/main.py", id="dot-dot"),
        pytest.param("../agent-hub-hub/hub.json", id="outside"),
    ],
)
def test_plans_full_when_path_is_unknown(path: str) -> None:
    plan = plan_change([path], GRAPH, TREE)

    assert _full_view(plan) == (True, [], ())
    assert [reason for reason in plan.reasons if path in reason] != []


# The most characters of a path that a reason line shows.
SHOWN_CHARACTERS = 200


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        pytest.param("n" * SHOWN_CHARACTERS, "n" * SHOWN_CHARACTERS, id="at-limit"),
        pytest.param("n" * (SHOWN_CHARACTERS + 1), f"{'n' * SHOWN_CHARACTERS}…", id="long"),
        pytest.param("notes/\x1b[2J.txt", "notes/…", id="escape"),
    ],
)
def test_cuts_path_in_reason_when_path_is_long_or_unprintable(path: str, shown: str) -> None:
    plan = plan_change([path], GRAPH, TREE)

    assert plan.reasons == (f"full: unknown path {shown}",)


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(f"{BUILTIN}/no-such-pack/scripts/run.py", id="script"),
        pytest.param(f"{BUILTIN}/no-such-pack/no-such-pack.yaml", id="definition"),
    ],
)
def test_plans_full_when_pack_is_unknown(path: str) -> None:
    assert "no-such-pack" not in TREE.packs

    plan = plan_change([path], GRAPH, TREE)

    assert _full_view(plan) == (True, [], ())
    assert [reason for reason in plan.reasons if "no-such-pack" in reason] != []


def test_runs_checks_only_when_root_log_changes() -> None:
    root_log = plan_change(["check.log"], GRAPH, TREE)
    nested_log = plan_change(["packages/cli/x.log"], GRAPH, TREE)

    assert (root_log.full, root_log.tests, root_log.web) == (False, (), False)
    assert [reason for reason in root_log.reasons if "check.log" in reason] != []
    assert nested_log.full is True


@pytest.mark.parametrize(
    ("present", "deleted", "expected"),
    [
        pytest.param(
            HUB_GIT_SOURCE,
            "packages/hub_git/src/agent_hub/hub_git/retired.py",
            HUB_GIT_PLAN,
            id="source",
        ),
        pytest.param(
            "packages/storage/tests/unit/test_db.py",
            "packages/storage/tests/unit/test_retired.py",
            ("packages/storage/tests/unit", "packages/storage/tests/contract"),
            id="unit-test",
        ),
    ],
)
def test_plans_deleted_path_like_present_one_when_planned(
    present: str, deleted: str, expected: tuple[str, ...]
) -> None:
    assert (REPO_ROOT / present).is_file()
    assert not (REPO_ROOT / deleted).exists()

    plans = [plan_change([path], GRAPH, TREE) for path in (present, deleted)]

    assert [sorted(plan.tests) for plan in plans] == [sorted(expected), sorted(expected)]
    assert [plan.full for plan in plans] == [False, False]


@dataclass(frozen=True)
class SourceCase:
    argv: tuple[str, ...]
    environ: Mapping[str, str]
    source: str
    paths: tuple[str, ...]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            SourceCase(
                ("a.py", "b/c.py"),
                {"PATHS": "p.py", "HUB_CHANGED_FILES": "h.py"},
                "argv",
                ("a.py", "b/c.py"),
            ),
            id="arguments",
        ),
        pytest.param(
            SourceCase(
                (),
                {"PATHS": " p.py\tq/r.py\n s.md ", "HUB_CHANGED_FILES": "h.py"},
                "PATHS",
                ("p.py", "q/r.py", "s.md"),
            ),
            id="paths-variable",
        ),
        pytest.param(
            SourceCase(
                (),
                {"PATHS": "  ", "HUB_CHANGED_FILES": "h.py\n\nd/e f.py\n"},
                "HUB_CHANGED_FILES",
                ("d/e f.py", "h.py"),
            ),
            id="changed-files",
        ),
        pytest.param(
            SourceCase((), {"HUB_CHANGED_FILES": ""}, "git", GIT_PATHS), id="empty-changed-files"
        ),
        pytest.param(
            SourceCase((), {"HUB_CHANGED_FILES": "\n \n"}, "git", GIT_PATHS),
            id="blank-changed-files",
        ),
        pytest.param(SourceCase((), {}, "git", GIT_PATHS), id="git"),
    ],
)
def test_reads_paths_in_precedence_when_sources_given(case: SourceCase) -> None:
    git = _git_with_origin()

    source, paths = change_set(case.argv, case.environ, git)

    assert (source, sorted(paths or ())) == (case.source, sorted(case.paths)), git.calls


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({UNTRACKED: "new.txt\n"}, id="no-origin-main"),
        pytest.param({MERGE_BASE: f"{BASE}\n", UNTRACKED: "new.txt\n"}, id="diff-fails"),
        pytest.param({MERGE_BASE: f"{BASE}\n", DIFF: "m.py\n"}, id="untracked-fails"),
    ],
)
def test_plans_full_when_origin_main_missing(
    answers: Mapping[tuple[str, ...], str | None],
) -> None:
    git = FakeGit(answers)

    source, paths = change_set([], {}, git)
    plan = plan_change(paths, GRAPH, TREE)

    assert MERGE_BASE in git.calls
    assert (source, paths) == ("git", None)
    assert _full_view(plan) == (True, [], ())
    assert plan.web is True


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({MERGE_BASE: f"{BASE}\n", DIFF: "m.py\n", UNTRACKED: ""}, id="origin-main"),
        pytest.param({UNTRACKED: ""}, id="no-origin-main"),
    ],
)
def test_never_fetches_when_paths_come_from_git(
    answers: Mapping[tuple[str, ...], str | None],
) -> None:
    git = FakeGit(answers)

    change_set([], {}, git)

    assert MERGE_BASE in git.calls
    assert [call for call in git.calls if NETWORK_GIT.intersection(call)] == []


MAKEFILE = REPO_ROOT / "Makefile"
CHECKS = frozenset({"format", "lint", "typecheck", "layout", "lockstep"})
WEB_STEPS = frozenset({"web-install", "web-static", "web-test"})
HOSTILE = "$(touch x).py;rm -rf y"
NO_STEP = "no-such-step"
FAILED_OUTPUT = "output of the step that failed"
PASSED_OUTPUT = "output of the step that passed"
# How the output's last line starts when a step failed; the failed step's argv follows.
FAILED_LINE = "check-changed: failed: "
LANE_WAIT_S = 2.0


@dataclass
class FakeStart:
    """Starts no process: records each step's argv and fails the steps that name ``failing``."""

    failing: str = NO_STEP
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        call = tuple(argv)
        self.calls.append(call)
        return (1, f"{self.failing} failed\n") if _names(call, self.failing) else (0, "")


@dataclass
class LaneStart:
    """Fails the step naming ``failing`` at once; the step naming ``waiter`` passes after it."""

    failing: str
    waiter: str
    failed: threading.Event = field(default_factory=threading.Event)

    def __call__(self, argv: Sequence[str]) -> tuple[int, str]:
        if _names(argv, self.failing):
            self.failed.set()
            return 1, f"{FAILED_OUTPUT}\n"
        if _names(argv, self.waiter):
            self.failed.wait(LANE_WAIT_S)
            # Lets the failed lane end first, so printing lanes as they end shows up.
            time.sleep(0.1)
            return 0, f"{PASSED_OUTPUT}\n"
        return 0, ""


def _names(call: Sequence[str], word: str) -> bool:
    """Whether a step's argv holds ``word``, alone or as the file name of a program."""
    return any(arg == word or Path(arg).name == word for arg in call)


def _make_words(calls: Sequence[Sequence[str]]) -> set[str]:
    """Every argument the steps give to make."""
    return {arg for call in calls if Path(call[0]).name == "make" for arg in call[1:]}


def _is_pytest(call: Sequence[str]) -> bool:
    return _names(call, "pytest")


def _pytest_view(call: Sequence[str]) -> tuple[list[str], list[str], frozenset[str]]:
    """A pytest step's marker expressions, coverage options and test paths."""
    markers = [value for option, value in itertools.pairwise(call) if option == "-m"]
    return (
        [marker for marker in markers if marker != "pytest"],
        [arg for arg in call if arg.startswith("--cov")],
        frozenset(arg for arg in call if arg.startswith(("packages/", "tests/"))),
    )


def _recipe(makefile: str, target: str) -> str:
    """The recipe of ``target``'s rule, continuations joined; empty when no rule names it."""
    lines = makefile.replace("\\\n", " ").splitlines()
    rule = re.compile(rf"{re.escape(target)}[ \t]*:(?![=:])")
    starts = [index for index, line in enumerate(lines) if rule.match(line)]
    if not starts:
        return ""
    body = lines[starts[0] + 1 :]
    return "\n".join(itertools.takewhile(lambda line: line.startswith("\t"), body))


@dataclass(frozen=True)
class RunCase:
    path: str
    tests: tuple[str, ...]
    openapi: bool
    web: bool
    ignores: tuple[str, ...] = ()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(RunCase(STORAGE_DB, STORAGE_PLAN, openapi=True, web=False), id="storage"),
        pytest.param(RunCase(FLAKY_SCRIPT, FLAKY_PLAN, openapi=False, web=False), id="pack"),
        pytest.param(RunCase(WEB_COMPONENT, (), openapi=False, web=True), id="web"),
        pytest.param(
            RunCase(
                CORE_ERRORS,
                (*EVERY_FAST_DIR, *SCAN_FILES),
                openapi=True,
                web=False,
                ignores=(PACK_TESTS,),
            ),
            id="core",
        ),
    ],
)
def test_runs_checks_on_whole_tree_when_plan_runs(case: RunCase) -> None:
    start = FakeStart()

    code = main([case.path], environ={}, start=start, git=FakeGit({}))

    openapi = [call for call in start.calls if _names(call, "scripts.export_openapi")]
    tests = [_pytest_view(call) for call in start.calls if _is_pytest(call)]
    ignores = [arg for call in start.calls if _is_pytest(call) for arg in call if "ignore" in arg]
    assert code == 0
    assert _make_words(start.calls) >= CHECKS
    assert [call for call in start.calls if any(case.path in arg for arg in call)] == []
    assert [call for call in openapi if "--check" in call] == openapi
    assert bool(openapi) is case.openapi
    assert tests == ([(["unit or contract"], [], frozenset(case.tests))] if case.tests else [])
    assert _make_words(start.calls) & WEB_STEPS == (WEB_STEPS if case.web else set())
    assert _names(start.calls[0], "web-install") is case.web
    assert ignores == [f"--ignore={path}" for path in case.ignores]


@pytest.mark.parametrize(
    ("path", "failing"),
    [
        pytest.param(STORAGE_DB, NO_STEP, id="none"),
        pytest.param(STORAGE_DB, "lint", id="checks"),
        pytest.param(STORAGE_DB, "scripts.export_openapi", id="openapi"),
        pytest.param(STORAGE_DB, "pytest", id="tests"),
        pytest.param(WEB_COMPONENT, "web-install", id="web-install"),
        pytest.param(WEB_COMPONENT, "web-test", id="web-test"),
    ],
)
def test_exits_non_zero_when_a_step_fails(
    path: str, failing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    start = FakeStart(failing=failing)

    code = main([path], environ={}, start=start, git=FakeGit({}))

    fails = failing != NO_STEP
    last = capsys.readouterr().out.splitlines()[-1]
    assert any(_names(call, failing) for call in start.calls) is fails
    assert (code != 0) is fails
    assert last.startswith(FAILED_LINE) is fails
    assert _names(shlex.split(last.removeprefix(FAILED_LINE)), failing) is fails


@pytest.mark.parametrize(
    ("failing", "waiter"),
    [
        pytest.param("lint", "pytest", id="checks-lane"),
        pytest.param("pytest", "lint", id="tests-lane"),
    ],
)
def test_prints_failed_lane_last_when_lanes_end(
    failing: str, waiter: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([FLAKY_SCRIPT], environ={}, start=LaneStart(failing, waiter), git=FakeGit({}))

    out = capsys.readouterr().out
    assert (code != 0, PASSED_OUTPUT in out, FAILED_OUTPUT in out) == (True, True, True)
    assert out.rindex(PASSED_OUTPUT) < out.index(FAILED_OUTPUT)


def test_prints_plan_and_runs_nothing_when_plan_flag_given(
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = FakeStart()

    code = main(["--plan", STORAGE_DB], environ={}, start=start, git=FakeGit({}))

    out = capsys.readouterr().out
    assert (code, start.calls) == (0, [])
    assert [target for target in STORAGE_PLAN if target not in out] == []


# The most reason lines the printed plan holds; one more line counts the rest.
REASONS_SHOWN = 20


@pytest.mark.parametrize(
    ("count", "tail"),
    [
        pytest.param(REASONS_SHOWN, [], id="at-cap"),
        pytest.param(REASONS_SHOWN + 1, ["  reason: … and 1 more"], id="over-cap"),
    ],
)
def test_prints_capped_reasons_when_many_paths_unknown(
    count: int, tail: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    paths = [f"notes/{index:02}.txt" for index in range(count)]

    main(["--plan", *paths], environ={}, start=FakeStart(), git=FakeGit({}))

    out = capsys.readouterr().out
    reasons = [line for line in out.splitlines() if line.startswith("  reason: ")]
    shown = [f"  reason: full: unknown path {path}" for path in paths[:REASONS_SHOWN]]
    assert len([path for path in paths if path in out]) == REASONS_SHOWN
    assert reasons == [*shown, *tail]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(".github/workflows/ci.yml", id="workflow"),
        pytest.param("check.log", id="scratch-log"),
    ],
)
def test_starts_no_pytest_when_plan_has_no_tests(path: str) -> None:
    start = FakeStart()

    code = main([path], environ={}, start=start, git=FakeGit({}))

    assert code == 0
    assert _make_words(start.calls) >= CHECKS
    assert [call for call in start.calls if _is_pytest(call)] == []


@pytest.mark.parametrize(
    ("argv", "environ"),
    [
        pytest.param([HOSTILE], {}, id="argument"),
        pytest.param([], {"HUB_CHANGED_FILES": HOSTILE}, id="changed-files"),
    ],
)
def test_passes_paths_as_data_when_runner_starts_steps(
    argv: list[str], environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    start = FakeStart()

    main(argv, environ=environ, start=start, git=FakeGit({}))

    assert _make_words(start.calls) >= CHECKS
    assert [arg for call in start.calls for arg in call if "touch" in arg] == []
    assert HOSTILE in capsys.readouterr().out


def test_keeps_paths_out_of_recipe_when_makefile_read() -> None:
    recipe = _recipe(MAKEFILE.read_text("utf-8"), "check-changed")

    assert "scripts.check_changed" in recipe
    assert "PATHS" not in recipe


DOCS_TESTS = (
    "tests/unit/scripts/test_build_llms_txt.py",
    "tests/unit/scripts/test_build_flow_catalog.py",
    "tests/unit/scripts/perf/test_budgets.py",
)
BUMP_TEST = f"{PACK_TESTS}/release/scripts/test_bump.py"
OPENAPI_TEST = "tests/unit/scripts/test_export_openapi.py"
RETRO_TESTS = f"{PACK_TESTS}/retro"
# The small tree, plus the test files and the retro pack that the rows below name.
ROW_TREE = Tree(
    paths=TREE.paths | {*DOCS_TESTS, BUMP_TEST, OPENAPI_TEST, RETRO_TESTS},
    packs=TREE.packs | {"retro"},
)


@dataclass(frozen=True)
class RowCase:
    path: str
    tests: tuple[str, ...] = ()
    ignores: tuple[str, ...] = ()
    openapi: bool = False
    reason: bool = False


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(RowCase("docs/TESTING.md", DOCS_TESTS), id="docs"),
        pytest.param(RowCase("docs/adr/0053-budgets.md", DOCS_TESTS), id="adr"),
        pytest.param(RowCase("CHANGELOG.md", DOCS_TESTS), id="root-markdown"),
        pytest.param(RowCase("README.md", (*DOCS_TESTS, BUMP_TEST)), id="readme"),
        pytest.param(RowCase("llms.txt", DOCS_TESTS), id="llms"),
        pytest.param(RowCase("llms-full.txt", DOCS_TESTS), id="llms-full"),
        pytest.param(
            RowCase("packages/api/openapi.json", (OPENAPI_TEST,), openapi=True), id="openapi"
        ),
        pytest.param(RowCase("scripts/seed_demo.py", ("tests/unit",)), id="script"),
        pytest.param(RowCase("scripts/perf/budgets.json", ("tests/unit",)), id="script-data"),
        pytest.param(
            RowCase("tests/unit/scripts/test_seed_demo.py", ("tests/unit",)), id="root-unit-test"
        ),
        pytest.param(
            RowCase("packages/storage/tests/integration/test_event_queries.py", reason=True),
            id="integration-test",
        ),
        pytest.param(
            RowCase(
                "packages/generator/tests/integration/golden/retro_metrics/full.golden",
                (RETRO_TESTS,),
            ),
            id="retro-golden",
        ),
        # A core change, plus that pack's tests: the other packs' folders are ignored one by
        # one, since pytest drops a target that lies under an ignored folder.
        pytest.param(
            RowCase(
                f"{BUILTIN}/flaky/flaky.yaml",
                (*FAST_DIRS, *SCAN_FILES, f"{PACK_TESTS}/flaky"),
                ignores=(f"{PACK_TESTS}/release", RETRO_TESTS),
                openapi=True,
            ),
            id="pack-definition",
        ),
        pytest.param(RowCase("tests/e2e/test_demo_seed.py", reason=True), id="e2e-test"),
        pytest.param(RowCase("Dockerfile", reason=True), id="dockerfile"),
        pytest.param(RowCase("compose.yaml", reason=True), id="compose"),
        pytest.param(RowCase("docker/no-build-ca.pem", reason=True), id="docker"),
        pytest.param(RowCase(".gitattributes", reason=True), id="gitattributes"),
        pytest.param(RowCase(".gitignore", reason=True), id="gitignore"),
        pytest.param(RowCase(".importlinter", reason=True), id="importlinter"),
    ],
)
def test_plans_table_row_when_path_matches_it(case: RowCase) -> None:
    plan = plan_change([case.path], GRAPH, ROW_TREE)

    assert (plan.full, plan.web) == (False, False)
    assert sorted(plan.tests) == sorted(case.tests)
    assert (plan.ignores, plan.openapi) == (case.ignores, case.openapi)
    assert any(case.path in reason for reason in plan.reasons) is case.reason
