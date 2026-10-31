"""``make check-changed`` (``scripts/check_changed.py``): the plan a change set gets.

Planner tests use the small graph and tree below, except those whose name ends in ``in_repo``:
they read this checkout's own packages and test folders. git is a fake: no process starts.
"""

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
