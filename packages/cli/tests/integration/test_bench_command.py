"""``hub bench``: the configuration benchmark, ported from the hub's script (AC-17.14 to AC-17.16).

This module re-expresses hub ``scripts/bench.py`` at hub commit ``5b56604`` and its
characterization (``tests/characterization/test_bench.py``) against the command; every port
difference of the plan is asserted here. ``TestUsage`` runs in process in a copy of the ``DEMO``
hub (``demo_hub``), with ``bench`` selected where a test needs it: each refusal is a usage error,
exit 2, or a reader failure, exit 1, before any child process. The other tests run in the hub
suite's bench workspace (``bench_workspace``: ``ws/hub`` selecting ``bench``, repo ``ws/api``)
with a fake ``claude`` on ``PATH``.
"""

import contextlib
import datetime
import fcntl
import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import bench_command
from agent_hub.core.bench.bench_cases import MAX_CASES

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
# What a refused run must never reach: any child process.
GUARDED = ("run_child", "stream_child")
EFFORT_VARIABLE = "BENCH_EFFORT"


class Spy:
    """Every guarded call any ``agent_hub.cli`` module makes: ``(name, argv)``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def guard(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def spy(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args[0] if args else None))
            return real(*args, **kwargs)

        return spy


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Spy]:
    """Wrap every guarded name in every loaded ``agent_hub.cli`` module (each import holds its own
    reference), so a call from any module is seen."""
    import agent_hub.cli.main  # noqa: F401 - loads every command module before patching

    seen = Spy()
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("agent_hub.cli"):
            continue
        for name in GUARDED:
            real = getattr(module, name, None)
            if callable(real):
                monkeypatch.setattr(module, name, seen.guard(name, real))
    yield seen


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    # A usage message stays on one line of Rich's box.
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.delenv(EFFORT_VARIABLE, raising=False)


@pytest.fixture
def bench_hub(demo_hub: Path) -> Path:
    """The ``DEMO`` hub with ``modules.bench`` selected."""
    document = json.loads((demo_hub / "hub.json").read_text())
    document["modules"] = {"bench": {}}
    (demo_hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    return demo_hub


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub bench" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


BUDGET = "Invalid value for '--budget': use a number of USD above 0, at most 1000"
PER_RUN = "Invalid value for '--per-run': use a number of USD above 0"
ARMS = "Invalid value for '--arms': use with, without or both, comma-separated, each once"
CASES = (
    "Invalid value for '--cases':"
    " use case ids (1 to 64 of A-Z a-z 0-9 . _ -), comma-separated, each once"
)
LABEL = (
    "Invalid value for '--label':"
    " use 1 to 64 of A-Z a-z 0-9 . _ -, not . or .., not starting with -"
)


class TestUsage:
    def test_lists_options_with_defaults_when_help_requested(
        self, tmp_path: Path, run_command: CommandRunner
    ) -> None:
        result = run_command(tmp_path, "bench", "--help")

        assert result.exit_code == 0
        words = " ".join(unstyle(result.stdout).replace(BOX_CHARACTERS[0], " ").split())
        for text in (
            "--validate",
            "--runs",
            "[default: 3]",
            "--arms",
            "[default: with,without]",
            "--cases",
            "[default: (all)]",
            "--budget",
            "[default: 15.0]",
            "--per-run",
            "[default: 2.0]",
            "--parallel",
            "[default: 3]",
            "--label",
            "[default: (bench-%Y%m%d-%H%M)]",
            "--trace",
            "BENCH_EFFORT",
            "low, medium (default) or high",
        ):
            assert text in words, text

    def test_exits_two_when_bench_not_selected(
        self, demo_hub: Path, run_command: CommandRunner, spy: Spy
    ) -> None:
        (demo_hub / "brain" / "workflow" / "bench").mkdir(parents=True)
        (demo_hub / "brain" / "workflow" / "bench" / "tasks.json").write_text("not json\n")

        result = run_command(demo_hub, "bench", "--validate")

        assert_refused(result, "module bench is not selected")
        assert spy.calls == []

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            (("--validate", "--runs", "2"), "--validate takes no run option: --runs"),
            (("--validate", "--trace"), "--validate takes no run option: --trace"),
            (
                ("--label", "x", "--validate", "--arms", "with"),
                "--validate takes no run option: --arms, --label",
            ),
            (("--runs", "0"), "Invalid value for '--runs': 0 is not in the range 1<=x<=100."),
            (("--runs", "101"), "Invalid value for '--runs': 101 is not in the range 1<=x<=100."),
            (
                ("--parallel", "0"),
                "Invalid value for '--parallel': 0 is not in the range 1<=x<=16.",
            ),
            (
                ("--parallel", "17"),
                "Invalid value for '--parallel': 17 is not in the range 1<=x<=16.",
            ),
            (("--budget", "0"), BUDGET),
            (("--budget", "-1"), BUDGET),
            (("--budget", "inf"), BUDGET),
            (("--budget", "nan"), BUDGET),
            (("--budget", "1000.01"), BUDGET),
            (("--per-run", "0"), PER_RUN),
            (("--per-run", "inf"), PER_RUN),
            (("--arms", "with,maybe"), ARMS),
            (("--arms", "with,with"), ARMS),
            (("--arms", ""), ARMS),
            (("--cases", "T1,,T2"), CASES),
            (("--cases", "T 1"), CASES),
            (("--cases", ",".join(f"T{n}" for n in range(201))), CASES),
            (("--label", "../x"), LABEL),
            (("--label", ""), LABEL),
            (("--label", "x" * 65), LABEL),
            (("--cases", "T1,T2,T1"), CASES),
            (("--label", "."), LABEL),
            (("--label", ".."), LABEL),
            (("--label=-x",), LABEL),
            (("--per-run", "15.01"), "--per-run 15.01 is above --budget 15.0"),
            (("--budget", "1", "--per-run", "2"), "--per-run 2.0 is above --budget 1.0"),
        ],
        ids=[
            "validate-runs",
            "validate-trace",
            "validate-two",
            "runs-zero",
            "runs-over",
            "parallel-zero",
            "parallel-over",
            "budget-zero",
            "budget-negative",
            "budget-inf",
            "budget-nan",
            "budget-over",
            "per-run-zero",
            "per-run-inf",
            "arms-unknown",
            "arms-repeated",
            "arms-empty",
            "cases-empty-id",
            "cases-space",
            "cases-too-many",
            "label-path",
            "label-empty",
            "label-long",
            "cases-repeated",
            "label-dot",
            "label-dot-dot",
            "label-dash",
            "per-run-over-default-budget",
            "per-run-over-budget",
        ],
    )
    def test_refuses_option_when_value_invalid(
        self,
        bench_hub: Path,
        run_command: CommandRunner,
        spy: Spy,
        *,
        arguments: tuple[str, ...],
        message: str,
    ) -> None:
        result = run_command(bench_hub, "bench", *arguments)

        assert_refused(result, message)
        assert spy.calls == []

    def test_accepts_options_when_values_at_bounds(
        self, bench_hub: Path, run_command: CommandRunner, spy: Spy
    ) -> None:
        cases = ",".join(f"T{n}" for n in range(MAX_CASES))

        result = run_command(
            bench_hub,
            "bench",
            *("--runs", str(bench_command.MAX_RUNS)),
            *("--parallel", str(bench_command.MAX_PARALLEL)),
            *("--budget", str(bench_command.MAX_BUDGET_USD)),
            *("--per-run", str(bench_command.MAX_BUDGET_USD)),
            *("--label", "x" * 64),
            *("--cases", cases),
        )

        # Past every check: the hub has no cases, so the run starts no child.
        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout == NO_CASES_TO_RUN
        assert spy.calls == []
        assert (bench_command.MAX_RUNS, bench_command.MAX_PARALLEL) == (100, 16)
        assert (bench_command.MAX_BUDGET_USD, MAX_CASES) == (1000, 200)

    @pytest.mark.parametrize("effort", ["huge", "HIGH", " low"])
    def test_refuses_effort_when_variable_unknown(
        self, bench_hub: Path, run_command: CommandRunner, spy: Spy, *, effort: str
    ) -> None:
        result = run_command(bench_hub, "bench", env={EFFORT_VARIABLE: effort})

        assert_refused(result, "BENCH_EFFORT must be low, medium or high")
        assert spy.calls == []

    def test_exits_two_when_not_a_hub(
        self, tmp_path: Path, run_command: CommandRunner, spy: Spy
    ) -> None:
        folder = tmp_path / "elsewhere"
        folder.mkdir()

        result = run_command(folder, "bench")

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{folder}: not a hub: no hub.json in this folder"
            " (hub bench runs in the hub folder or through ./hub)\n"
        )
        assert spy.calls == []

    def test_prints_reader_lines_when_hub_json_invalid(
        self, bench_hub: Path, run_command: CommandRunner, spy: Spy
    ) -> None:
        (bench_hub / "hub.json").write_bytes(b"{}\n")

        result = run_command(bench_hub, "bench", "--validate")

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines
        assert all(line.startswith("hub.json: ") for line in lines), lines
        assert spy.calls == []


def run_tool(name: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``name`` as a child of the command would, found on the bench workspace's ``PATH``."""
    found = shutil.which(name, path=os.environ["PATH"])
    assert found is not None, f"{name} is not on the bench workspace's PATH"
    return subprocess.run(  # noqa: S603 - a fake or linked tool of the workspace's bin, absolute
        [found, *args], cwd=cwd, env=dict(os.environ), capture_output=True, text=True, check=False
    )


class TestBenchWorkspace:
    def test_runs_fakes_from_path_when_workspace_built(
        self, bench_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = bench_workspace
        reply = workspace.result(0.5, 7, "success")
        workspace.answer(
            [
                {"argv_has": ["--never"], "stdout": "first rule\n"},
                # The without rule first: the with value is a substring of its value.
                {"env_has": workspace.otel("T1", "without"), "stdout": reply, "rc": 3},
                {"env_has": workspace.otel("T1", "with"), "write": {"new/fix.txt": "fixed\n"}},
                {"env_has": workspace.otel("T1", "with"), "stdout": "shadowed\n"},
            ]
        )
        attributes = "repo=api,bench_case=T1,bench_arm=with"
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", attributes)
        wrote = run_tool("claude", "-p", "Add the fix", cwd=workspace.api)
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", attributes + "out")
        replied = run_tool("claude", "-p", "x", cwd=workspace.hub)
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES")
        unmatched = run_tool("claude", "-p", "y", cwd=workspace.hub)

        assert (wrote.returncode, wrote.stdout) == (0, "")
        assert (workspace.api / "new" / "fix.txt").read_text() == "fixed\n"
        assert (replied.returncode, json.loads(replied.stdout)) == (
            3,
            {"total_cost_usd": 0.5, "num_turns": 7, "subtype": "success"},
        )
        assert (unmatched.returncode, unmatched.stdout) == (1, "")
        calls = workspace.claude_calls()
        assert [(call["argv"], call["cwd"]) for call in calls] == [
            (["-p", "Add the fix"], str(workspace.api)),
            (["-p", "x"], str(workspace.hub)),
            (["-p", "y"], str(workspace.hub)),
        ]
        assert calls[0]["values"] == {"OTEL_RESOURCE_ATTRIBUTES": attributes}
        assert "PATH" in calls[0]["env"]
        assert calls[2]["values"] == {}
        # The repo: the hub suite's commits on trunk, other agent config on origin/main.
        merge = workspace.sha("trunk~2")
        assert workspace.case() == {
            "id": "T1",
            "repo": "api",
            "merge": merge,
            "prompt": "Add the fix",
            "hidden_tests": ["t/__main__.py", "a/__main__.py", "t/__main__.py"],
            "test_cmd": ["python3"],
            "setup_cmd": "echo ready > setup.txt",
            "env": {"CHECK_MODE": 1},
        }
        assert workspace.git(workspace.api, "log", "--format=%s", "trunk") == (
            "more docs\ndocs\nadd the fix\nstale checks\nbase\ninit"
        )
        assert workspace.git(workspace.api, "show", "origin/main:AGENTS.md") == "M"
        assert workspace.git(workspace.api, "show", "trunk:AGENTS.md") == "t"
        assert workspace.git(workspace.api, "branch", "--format=%(refname:short)") == "trunk"
        assert workspace.git(workspace.api, "status", "--porcelain") == "?? new/"
        stale = workspace.git(workspace.api, "show", f"{merge}^:t/__main__.py")
        assert stale == 'print("stale check")'
        checked = run_tool("python3", "a/__main__.py", cwd=workspace.api)
        assert checked.returncode == 0, checked.stderr
        assert checked.stdout == "a fix present mode=- cfg=tttt staged=0 args:\n"
        # The hub: model-valid, bench selected, committed with its cases.
        workspace.write_cases([workspace.case()])
        document = json.loads((workspace.hub / "hub.json").read_text())
        assert document["modules"] == {"bench": {}}
        assert [repo["dir"] for repo in document["repos"]] == ["api"]
        assert workspace.git(workspace.hub, "status", "--porcelain") == ""
        assert json.loads((workspace.hub / "brain/workflow/bench/tasks.json").read_text()) == [
            workspace.case()
        ]
        assert {path.name for path in workspace.bin.iterdir()} == {
            "claude",
            "git",
            "bash",
            "python3",
        }


# The hub goldens' stdout (validate_ok, validate_mismatch): each case at its merge's parent, then
# at its merge; the check's last line, then the error (none), each after a space.
_ARGS = "args: a/__main__.py t/__main__.py "
OK_LINES = (
    f"T1 parent pass=False OK t fix missing mode=1 setup cfg=tttt staged=2 {_ARGS}\n"
    f"T1 merge  pass=True OK t fix present mode=1 setup cfg=tttt staged=0 {_ARGS}\n"
)
MISMATCH_LINES = (
    f"T1 parent pass=True MISMATCH t fix present mode=1 setup cfg=tttt staged=0 {_ARGS}\n"
    f"T1 merge  pass=True OK t fix present mode=1 setup cfg=tttt staged=0 {_ARGS}\n"
    f"T2 parent pass=False OK t fix missing mode=1 fail=a setup cfg=tttt staged=2 {_ARGS}\n"
    f"T2 merge  pass=False MISMATCH t fix present mode=1 fail=a setup cfg=tttt staged=0 {_ARGS}\n"
    f"T3 parent pass=False OK t fix missing mode=1 fail=t setup cfg=tttt staged=2 {_ARGS}\n"
    f"T3 merge  pass=False MISMATCH t fix present mode=1 fail=t setup cfg=tttt staged=0 {_ARGS}\n"
)
NOTHING = "no bench cases in brain/workflow/bench/tasks.json: nothing to validate\n"
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "LINEAR_API_KEY")


def validate(workspace: Workspace, run_command: CommandRunner) -> Result:
    """``hub bench --validate`` in the workspace's hub."""
    return run_command(workspace.hub, "bench", "--validate")


def bench_folder(workspace: Workspace) -> Path:
    return workspace.ws / "_bench"


def assert_checkout_untouched(workspace: Workspace) -> None:
    """No worktree left under the bench folder or in api's list; api's own checkout as built."""
    worktrees = bench_folder(workspace) / "wt"
    assert not worktrees.exists() or list(worktrees.iterdir()) == []
    listed = workspace.git(workspace.api, "worktree", "list", "--porcelain")
    assert [line for line in listed.splitlines() if line.startswith("worktree ")] == [
        f"worktree {workspace.api}"
    ]
    assert workspace.git(workspace.api, "status", "--porcelain") == ""
    assert workspace.git(workspace.api, "rev-parse", "--abbrev-ref", "HEAD") == "trunk"
    # The workspace's bench lock is released.
    assert not lock_path(workspace).exists()


def lock_path(workspace: Workspace) -> Path:
    return bench_folder(workspace) / "bench.lock"


class TestValidate:
    def test_prints_ok_per_case_and_label_when_graders_match(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = bench_workspace
        for name in TOKENS:
            # Synthetic, built from fragments: never a real token.
            monkeypatch.setenv(name, "gh" + "p_" + "x" * 36)
        # The setup command logs its environment's names where the test reads them after the run
        # (only the workspace's bin is on PATH: no env tool).
        setup = (
            "echo ready > setup.txt;"
            ' python3 -c \'import os; print("\\n".join(os.environ))\' > "$HOME/setup.env"'
        )
        excluded = workspace.case(id="T0", repo="gone", excluded=True)
        workspace.write_cases([workspace.case(setup_cmd=setup), excluded])

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        # mode=1: the case env reached the grader.
        assert result.stdout == OK_LINES
        # --validate costs no model token: claude never runs.
        assert workspace.claude_calls() == []
        names = set((workspace.home / "setup.env").read_text().split())
        assert "PATH" in names
        assert names.isdisjoint(TOKENS)
        assert "CHECK_MODE" not in names
        assert_checkout_untouched(workspace)

    def test_exits_one_when_grade_mismatches(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        # T1: the parent already passes. T2/T3: at the merge, only the hidden run (T2) or only
        # the related run (T3) passes; both runs must pass.
        workspace.write_cases(
            [
                workspace.case("trunk"),
                workspace.case(id="T2", env={"CHECK_MODE": 1, "CHECK_FAIL_DIR": "a"}),
                workspace.case(id="T3", env={"CHECK_MODE": 1, "CHECK_FAIL_DIR": "t"}),
            ]
        )

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stderr) == (1, ""), result.output
        assert result.stdout == MISMATCH_LINES
        assert workspace.claude_calls() == []
        assert_checkout_untouched(workspace)

    @pytest.mark.parametrize("cases", [None, [], "excluded"], ids=["absent", "empty", "excluded"])
    def test_prints_nothing_to_validate_when_no_cases(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, cases: object
    ) -> None:
        workspace = bench_workspace
        if cases == "excluded":
            workspace.write_cases([workspace.case(excluded=True)])
        elif cases is not None:
            workspace.write_cases(cases)

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout, result.stderr) == (0, NOTHING, "")
        assert not bench_folder(workspace).exists()
        assert workspace.claude_calls() == []

    def test_prints_script_line_when_case_repo_unknown(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases(
            [
                {"id": "T1", "repo": "zz"},
                {"id": "T2", "repo": "nope"},
                {"id": "T3", "repo": "zz"},
                {"id": "T4"},
                {"id": "T5", "repo": "api"},
                {"id": "T6", "repo": "gone", "excluded": True},
            ]
        )

        result = validate(workspace, run_command)

        # The golden's line (validate_unknown_repo), with this hub's one repo; only that line.
        assert (result.exit_code, result.stdout) == (1, "")
        assert result.stderr == (
            "ERROR bench: case repo(s) ['None', 'nope', 'zz'] not in hub.json repos ['api']\n"
        )
        assert not bench_folder(workspace).exists()

    def test_refuses_cases_when_shape_invalid(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases(
            [
                workspace.case(merge="--upload-pack=x"),
                workspace.case(id="T2"),
                # Excluded cases are shape-checked too (E16).
                workspace.case(id="T3", hidden_tests=["."], excluded=True),
                workspace.case(id="t2"),
            ]
        )

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout) == (1, "")
        path = "brain/workflow/bench/tasks.json"
        assert result.stderr.splitlines() == [
            f"{path}: [0].merge: must be a commit sha: 7 to 40 characters among 0-9 and a-f",
            f'{path}: [2].hidden_tests: "." is not a literal relative path in the repo'
            " (no empty, `.`, `..` or `.git` segment in any case, no leading `/`, `-` or `:`,"
            " no `*`, `?`, `[`, `\\`, control, format or surrogate character,"
            " 1 to 1024 characters)",
            f'{path}: [3].id: duplicate id "t2"',
        ]
        assert not bench_folder(workspace).exists()

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            (b'[{"id": "T1", "id": "T2"}]', 'the key "id" appears more than once'),
            (b"[NaN]", "NaN is not a JSON number"),
            (b'{"id": "T1"}', "the top level must be a list of cases"),
            (b"[" + b" " * (1 << 20) + b"]", "larger than 1048576 bytes"),
        ],
        ids=["repeated-key", "nan", "not-a-list", "too-large"],
    )
    def test_refuses_cases_when_json_not_strict(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        *,
        content: bytes,
        message: str,
    ) -> None:
        workspace = bench_workspace
        tasks = workspace.hub / "brain" / "workflow" / "bench" / "tasks.json"
        tasks.parent.mkdir(parents=True, exist_ok=True)
        tasks.write_bytes(content)

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout) == (1, "")
        lines = result.stderr.splitlines()
        assert len(lines) == 1, lines
        assert lines[0].startswith("brain/workflow/bench/tasks.json: ")
        assert message in lines[0]
        assert not bench_folder(workspace).exists()

    def test_refuses_cases_when_tasks_not_regular_file(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        cases = workspace.hub / "cases.json"
        cases.write_text(json.dumps([workspace.case()]))
        tasks = workspace.hub / "brain" / "workflow" / "bench" / "tasks.json"
        tasks.parent.mkdir(parents=True, exist_ok=True)
        tasks.symlink_to(cases)

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout) == (1, "")
        assert result.stderr == (
            "brain/workflow/bench/tasks.json:"
            " not read as a regular file (links are never followed)\n"
        )
        assert not bench_folder(workspace).exists()

    @pytest.mark.parametrize("leftover_kind", ["folder", "worktree", "symlink"])
    def test_removes_leftover_dir_when_worktree_path_taken(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, leftover_kind: str
    ) -> None:
        workspace = bench_workspace
        leftover = bench_folder(workspace) / "wt" / "validate-T1-parent"
        outside = workspace.base / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("kept\n")
        if leftover_kind == "folder":
            leftover.mkdir(parents=True)
            (leftover / "junk.txt").write_text("old\n")
        elif leftover_kind == "worktree":
            # Still a registered worktree of api: git must forget it, not only its folder go.
            workspace.git(
                workspace.api, "worktree", "add", "-q", "--detach", str(leftover), "trunk"
            )
        else:
            leftover.parent.mkdir(parents=True)
            leftover.symlink_to(outside, target_is_directory=True)
        workspace.write_cases([workspace.case()])

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout, result.stderr) == (0, OK_LINES, "")
        assert_checkout_untouched(workspace)
        # A link is removed, never followed.
        assert [path.name for path in outside.iterdir()] == ["keep.txt"]

    @pytest.mark.parametrize(
        ("fields", "reason"),
        [
            ({"test_cmd": ["./no-such-grader"]}, "./no-such-grader could not run: "),
            ({"test_cmd": ["no-such-grader"]}, "no-such-grader is not on PATH"),
            ({"setup_cmd": "echo broken >&2; exit 3"}, "setup_cmd: broken"),
            ({"merge": "0" * 40}, "git worktree add failed: fatal: "),
        ],
        ids=["grader-launch", "grader-missing", "setup", "worktree-add"],
    )
    def test_reports_case_failure_when_step_fails(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        *,
        fields: dict[str, Any],
        reason: str,
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case(**fields), workspace.case(id="T2")])

        result = validate(workspace, run_command)

        # Each label of the broken case fails on stderr; the next case is still graded.
        assert result.exit_code == 1, result.output
        assert result.stdout == OK_LINES.replace("T1 ", "T2 ")
        lines = result.stderr.splitlines()
        assert len(lines) == 2, lines
        assert lines[0].startswith(f"hub bench: T1 parent: {reason}"), lines
        assert lines[1].startswith(f"hub bench: T1 merge: {reason}"), lines
        assert_checkout_untouched(workspace)

    def test_removes_worktree_when_interrupted(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        real = bench_steps.run_child

        def interrupt_grader(argv: list[str], **kwargs: Any) -> Any:
            if argv[0].endswith("python3"):
                raise KeyboardInterrupt
            return real(argv, **kwargs)

        monkeypatch.setattr(bench_steps, "run_child", interrupt_grader)

        result = validate(workspace, run_command)

        # Typer's exit on Ctrl-C: 128 + SIGINT.
        assert result.exit_code == 130, result.output
        assert result.stdout == ""
        assert (bench_folder(workspace) / "wt").is_dir()
        assert_checkout_untouched(workspace)


# A run's clock: the label default and each record's ``ts`` (local time), as the hub goldens'.
INSTANT = datetime.datetime(2026, 1, 15, 10, 30)  # noqa: DTZ001 - the script's local time
DEFAULT_LABEL = "bench-20260115-1030"
TS = "2026-01-15T10:30:00"
NO_CASES_TO_RUN = (
    "no bench cases to run (brain/workflow/bench/tasks.json is empty or --cases matched none)\n"
)
TABLE_HEADER = "| case | arm | pass | pass^k | cost | avg s |\n|---|---|---|---|---|---|\n"
# The grader's lines in a run: the overlay put origin/main's agent config (M) over the parent's.
_RUN_WORDS = "mode=1 setup cfg=MMMM staged=2 args:"


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's clock at the goldens' instant; every session lasts 0 s."""
    from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this fixture patches

    monkeypatch.setattr(bench_command, "now", lambda: INSTANT)
    monkeypatch.setattr(bench_steps, "monotonic", lambda: 0.0)


def bench_run(
    workspace: Workspace,
    run_command: CommandRunner,
    *args: str,
    root: Path | None = None,
    env: dict[str, str] | None = None,
) -> Result:
    """``hub bench <args>`` in the workspace's hub (or ``root``)."""
    return run_command(root or workspace.hub, "bench", *args, env=env)


def results(workspace: Workspace) -> Path:
    return bench_folder(workspace) / "results"


def settings_path(workspace: Workspace, worktree: str) -> str:
    return str(results(workspace) / f".settings-{worktree}.json")


def agent_part(
    cost: float, turns: int | None, subtype: str | None, *, rc: int = 0, error: str = ""
) -> dict[str, Any]:
    return {
        "agent_rc": rc,
        "cost": cost,
        "turns": turns,
        "secs": 0,
        "subtype": subtype,
        "agent_error": error,
    }


def grade_part(*, fixed: bool) -> dict[str, Any]:
    state = "fix present" if fixed else "fix missing"
    return {
        "pass": fixed,
        "hidden_rc": 0 if fixed else 1,
        "related_rc": 0 if fixed else 1,
        "hidden_tail": f"t {state} {_RUN_WORDS} a/__main__.py t/__main__.py",
        "related_tail": f"a {state} {_RUN_WORDS} t",
    }


def record_line(
    case: str, arm: str, run: int, *, agent: dict[str, Any], grade: dict[str, Any], label: str
) -> str:
    """A record as the script printed it: its fields in the script's order."""
    record = {"label": label, "case": case, "arm": arm, "run": run, "model": "claude-sonnet-5"}
    return json.dumps(record | agent | grade | {"ts": TS})


def sandbox_line(workspace: Workspace, worktree: str, *, enabled: bool, effort: str) -> str:
    """The golden's settings file, with the plugin ``hub-workflow@demo`` (Q-5, E2)."""
    path = str(bench_folder(workspace) / "wt" / worktree)
    settings = {
        "sandbox": {
            "enabled": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": True,
            "network": {"allowedDomains": ["127.0.0.1", "localhost"], "allowLocalBinding": True},
            "filesystem": {
                "allowWrite": [path, "/private/tmp", "/private/var/folders"],
                "denyWrite": [f"{path}/.git"],
            },
        },
        "enabledPlugins": {"hub-workflow@demo": enabled, "engineering@synced": False},
        "effortLevel": effort,
    }
    return json.dumps(settings)


def claude_argv(workspace: Workspace, worktree: str, *, prompt: str, per_run: str) -> list[str]:
    """The golden's argv of a session, without the program."""
    return [
        *("-p", prompt, "--model", "claude-sonnet-5", "--output-format", "json"),
        *("--permission-mode", "acceptEdits", "--setting-sources", "user"),
        *("--settings", settings_path(workspace, worktree), "--max-budget-usd", per_run),
        *("--max-turns", "60", "--strict-mcp-config", "--no-session-persistence"),
    ]


def wt_path(workspace: Workspace, worktree: str) -> str:
    return str(bench_folder(workspace) / "wt" / worktree)


# A child that logs its tool name and its environment's names (and CHECK_MODE), then, given a
# program, becomes it.
_LOG_ENV = """import json, os, sys
with open(os.environ["HOME"] + "/children.jsonl", "a", encoding="utf-8") as file:
    file.write(json.dumps({"tool": sys.argv[1], "env": sorted(os.environ),
                           "mode": os.environ.get("CHECK_MODE")}) + "\\n")
if len(sys.argv) > 2 and sys.argv[1] == "git":
    os.execv(sys.argv[2], [sys.argv[2], *sys.argv[3:]])
"""


def logged_children(workspace: Workspace) -> list[dict[str, Any]]:
    path = workspace.home / "children.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.usefixtures("frozen")
class TestRun:
    def test_records_one_line_per_run_when_run(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # The golden run_two_arms: 12 jobs, T2 before T1 and without before with; the summary
        # sorts both. T1-with-r2 and -r3 write no fix. Costs 0.25/0.5: the 12th job starts at
        # spent 4.00 + 1.00 == --budget 5.0.
        workspace = bench_workspace
        workspace.write_cases(
            [
                workspace.case(id="T2", prompt="Add the fix again"),
                workspace.case(id="T3"),
                workspace.case(),
                workspace.case(id="T0", repo="gone", excluded=True),
            ]
        )
        reply = workspace.result
        rules: list[dict[str, Any]] = [
            {"env_has": workspace.otel(case, "without"), "stdout": reply(0.25, 3, "success")}
            for case in ("T2", "T1")
        ]
        rules += [
            {
                "argv_has": [settings_path(workspace, f"L1-T1-with-r{run}")],
                "env_has": workspace.otel("T1", "with"),
                "stdout": reply(0.5, 60, "error_max_turns"),
            }
            for run in (2, 3)
        ]
        rules += [
            {
                "env_has": workspace.otel(case, "with"),
                "write": {"fix.txt": "fixed\n"},
                "stdout": reply(0.5, 7, "success"),
            }
            for case in ("T2", "T1")
        ]
        workspace.answer(rules)

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "3", "--arms", "without,with", "--cases", "T1,T2", "--parallel", "1"),
            *("--label", "L1", "--per-run", "1.0", "--budget", "5.0"),
        )

        jobs = [
            (case, arm, run)
            for run in (1, 2, 3)
            for case in ("T2", "T1")
            for arm in ("without", "with")
        ]

        def line(case: str, arm: str, run: int) -> str:
            if arm == "without":
                agent, fixed = agent_part(0.25, 3, "success"), False
            elif case == "T1" and run > 1:
                agent, fixed = agent_part(0.5, 60, "error_max_turns"), False
            else:
                agent, fixed = agent_part(0.5, 7, "success"), True
            return record_line(
                case, arm, run, agent=agent, grade=grade_part(fixed=fixed), label="L1"
            )

        lines = [line(*job) for job in jobs]
        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout.startswith("".join(f"{text}\n" for text in lines))
        assert (results(workspace) / "L1.jsonl").read_text() == "".join(
            f"{text}\n" for text in lines
        )
        calls = workspace.claude_calls()
        assert [(call["cwd"], call["argv"]) for call in calls] == [
            (
                wt_path(workspace, f"L1-{case}-{arm}-r{run}"),
                claude_argv(
                    workspace,
                    f"L1-{case}-{arm}-r{run}",
                    prompt="Add the fix again" if case == "T2" else "Add the fix",
                    per_run="1.0",
                ),
            )
            for case, arm, run in jobs
        ]
        assert_checkout_untouched(workspace)

    def test_prints_summary_when_runs_end(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # AC-17.16: two runs, two at a time; both arms in each wave, with before without.
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        reply = workspace.result
        workspace.answer(
            [
                {"env_has": workspace.otel("T1", "without"), "stdout": reply(0.25, 3, "success")},
                {
                    "env_has": workspace.otel("T1", "with"),
                    "write": {"fix.txt": "fixed\n"},
                    "stdout": reply(0.5, 7, "success"),
                },
            ]
        )

        result = bench_run(
            workspace, run_command, "--runs", "2", "--parallel", "2", "--per-run", "1"
        )

        lines = [
            record_line(
                "T1",
                arm,
                run,
                agent=agent_part(0.5, 7, "success")
                if arm == "with"
                else agent_part(0.25, 3, "success"),
                grade=grade_part(fixed=arm == "with"),
                label=DEFAULT_LABEL,
            )
            for run in (1, 2)
            for arm in ("with", "without")
        ]
        records = "".join(f"{text}\n" for text in lines)
        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout == (
            f"{records}\nruns: 4, spent $1.50\n\n{TABLE_HEADER}"
            "| T1 | with | 2/2 | yes | $1.00 | 0 |\n"
            "| T1 | without | 0/2 | no | $0.50 | 0 |\n"
            "\n"
            "- **with**: pass@1 100%, pass^k 1/1, cost $1.00\n"
            "- **without**: pass@1 0%, pass^k 0/1, cost $0.50\n"
        )
        assert (results(workspace) / f"{DEFAULT_LABEL}.jsonl").read_text() == records
        assert_checkout_untouched(workspace)

    def test_enables_plugin_only_in_with_arm_when_run(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        # The marketplace file the script read is ignored: the plugin is the project's (Q-5).
        (workspace.hub / ".claude-plugin").mkdir(exist_ok=True)
        (workspace.hub / ".claude-plugin" / "marketplace.json").write_text('{"name": "market"}\n')

        result = bench_run(workspace, run_command, "--runs", "1", "--label", "L1")

        assert result.exit_code == 0, result.output
        written = {
            path.name: path.read_text()
            for path in results(workspace).iterdir()
            if path.name.startswith(".settings-")
        }
        assert written == {
            f".settings-L1-T1-{arm}-r1.json": sandbox_line(
                workspace, f"L1-T1-{arm}-r1", enabled=arm == "with", effort="medium"
            )
            for arm in ("with", "without")
        }

    def test_records_error_tail_when_claude_fails(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # The golden run_claude_error: agent_error keeps the last 300 of 301 characters,
        # hidden_tail the first 200 of a 201-character last line. Port difference: the failed
        # session left no cost, so it counts at its --per-run 0.135 (the script counted 0.0).
        # Money as floats: 0.135 + 0.165 = 0.30, and 0.30 + 0.135 > 0.3 stops the third job.
        workspace = bench_workspace
        tail = "T" + "-" * 198 + "|X"
        workspace.write_cases([workspace.case(env={"CHECK_MODE": 1, "CHECK_TAIL": tail})])
        stderr = "HEAD" + "." * 292 + "boom\n"
        workspace.answer(
            [
                {
                    "env_has": workspace.otel("T1", "without"),
                    "stdout": workspace.result(0.165, 2, "success"),
                },
                {
                    "env_has": workspace.otel("T1", "with"),
                    "stdout": "not json\n",
                    "stderr": stderr,
                    "rc": 1,
                },
            ]
        )

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "2", "--parallel", "1", "--per-run", "0.135", "--budget", "0.3"),
            env={EFFORT_VARIABLE: "high"},
        )

        grade = {
            "pass": False,
            "hidden_rc": 1,
            "related_rc": 1,
            "hidden_tail": tail[:200],
            "related_tail": tail[:200],
        }
        lines = [
            record_line(
                "T1",
                "with",
                1,
                agent=agent_part(0.135, None, None, rc=1, error=stderr[-300:]),
                grade=grade,
                label=DEFAULT_LABEL,
            ),
            record_line(
                "T1",
                "without",
                1,
                agent=agent_part(0.165, 2, "success"),
                grade=grade,
                label=DEFAULT_LABEL,
            ),
        ]
        records = "".join(f"{text}\n" for text in lines)
        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout == (
            f"{records}STOP: budget cap (spent $0.30, next wave up to $0.14)\n"
            f"\nruns: 2, spent $0.30\n\n{TABLE_HEADER}"
            "| T1 | with | 0/1 | no | $0.14 | 0 |\n"
            "| T1 | without | 0/1 | no | $0.17 | 0 |\n"
            "\n"
            "- **with**: pass@1 0%, pass^k 0/1, cost $0.14\n"
            "- **without**: pass@1 0%, pass^k 0/1, cost $0.17\n"
        )
        assert (results(workspace) / f"{DEFAULT_LABEL}.jsonl").read_text() == records
        for arm in ("with", "without"):
            name = f"{DEFAULT_LABEL}-T1-{arm}-r1"
            written = (results(workspace) / f".settings-{name}.json").read_text()
            assert written == sandbox_line(workspace, name, enabled=arm == "with", effort="high")
        assert [call["argv"] for call in workspace.claude_calls()] == [
            claude_argv(
                workspace, f"{DEFAULT_LABEL}-T1-{arm}-r1", prompt="Add the fix", per_run="0.135"
            )
            for arm in ("with", "without")
        ]
        assert_checkout_untouched(workspace)

    def test_stops_at_budget_cap_when_next_wave_too_costly(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # The first wave fits (0 + 2 x 1.0 <= 3); after 1.50 spent, the next (1.50 + 2.00) does not.
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        workspace.answer([{"stdout": workspace.result(0.75, 4, "success")}])

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "3", "--parallel", "2", "--per-run", "1", "--budget", "3"),
        )

        assert result.exit_code == 0, result.output
        stop = "STOP: budget cap (spent $1.50, next wave up to $2.00)\n"
        assert stop in result.stdout
        assert result.stdout.index(stop) > result.stdout.rindex('"ts": ')
        assert "\nruns: 2, spent $1.50\n" in result.stdout
        assert len(workspace.claude_calls()) == 2
        written = (results(workspace) / f"{DEFAULT_LABEL}.jsonl").read_text().splitlines()
        assert [(json.loads(text)["arm"], json.loads(text)["run"]) for text in written] == [
            ("with", 1),
            ("without", 1),
        ]

    def test_prints_no_cases_line_when_cases_match_none(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])

        # A substring match would pick T1.
        result = bench_run(workspace, run_command, "--cases", "T10")

        assert (result.exit_code, result.stdout, result.stderr) == (0, NO_CASES_TO_RUN, "")
        assert not bench_folder(workspace).exists()
        assert workspace.claude_calls() == []

    def test_writes_results_to_main_checkout_when_run_from_hub_worktree(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # The golden run_budget_stop_from_hub_worktree (E1, with --budget 3: --per-run 2.0 must
        # fit the budget): the worktree holds the cases and a hub.json with api; the main
        # checkout, changed after, holds neither. Two jobs at the default --parallel 3.
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        worktree = workspace.hub / ".claude" / "worktrees" / "x"
        workspace.git(workspace.hub, "worktree", "add", "-q", "-b", "x", str(worktree))
        document = json.loads((workspace.hub / "hub.json").read_text())
        document["repos"] = [
            {"dir": "web", "github": "acme/web", "check_fast": "true", "check": "true"}
        ]
        (workspace.hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
        workspace.write_cases([])

        result = bench_run(workspace, run_command, "--runs", "1", "--budget", "3", root=worktree)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout == (
            "STOP: budget cap (spent $0.00, next wave up to $4.00)\n"
            f"\nruns: 0, spent $0.00\n\n{TABLE_HEADER}\n"
        )
        assert [path.name for path in bench_folder(workspace).iterdir()] == ["results"]
        assert list(results(workspace).iterdir()) == []
        assert not (worktree.parent / "_bench").exists()
        assert workspace.claude_calls() == []

    def test_runs_children_without_tokens_when_run(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace = bench_workspace
        logger = workspace.base / "fakes" / "log_env.py"
        logger.write_text(_LOG_ENV)
        workspace.write_cases(
            [
                workspace.case(
                    setup_cmd=f"python3 {logger} setup",
                    test_cmd=["python3", str(logger), "grader"],
                )
            ]
        )
        real_git = os.path.realpath(workspace.bin / "git")
        (workspace.bin / "git").unlink()
        (workspace.bin / "git").write_text(
            f'#!/bin/sh\nexec {sys.executable} {logger} git {real_git} "$@"\n'
        )
        (workspace.bin / "git").chmod(0o755)
        workspace.answer([{"stdout": workspace.result(0.1, 1, "success")}])
        for name in TOKENS:
            # Synthetic, built from fragments: never a real token.
            monkeypatch.setenv(name, "gh" + "p_" + "x" * 36)

        result = bench_run(workspace, run_command, "--runs", "1", "--arms", "with")

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        children = logged_children(workspace)
        tools = {child["tool"] for child in children}
        assert tools == {"git", "setup", "grader"}
        for child in children:
            assert set(child["env"]).isdisjoint(TOKENS), child["tool"]
            # The case env reaches the test command only (E17).
            assert child["mode"] == ("1" if child["tool"] == "grader" else None), child["tool"]
        (session,) = workspace.claude_calls()
        assert set(session["env"]).isdisjoint(TOKENS)
        assert "CHECK_MODE" not in session["env"]
        assert session["values"] == workspace.otel("T1", "with")

    @pytest.mark.parametrize("trace", [True, False], ids=["trace", "no-trace"])
    def test_keeps_trace_only_when_trace_given(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, trace: bool
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        # Over 1 MiB: only the trace's tail is read, and its last result event is the record's.
        padding = json.dumps({"type": "assistant", "text": "a" * (1 << 20)})
        result_event = {"type": "result", "total_cost_usd": 0.5, "num_turns": 7}
        stream = "\n".join(
            [
                json.dumps({"type": "result", "total_cost_usd": 9.0}),
                padding,
                json.dumps(result_event | {"subtype": "success"}),
                json.dumps({"type": "system"}),
                "",
            ]
        )
        workspace.answer(
            [
                {"argv_has": ["stream-json"], "stdout": stream},
                {"stdout": workspace.result(0.25, 3, "success")},
            ]
        )
        arguments = ("--runs", "1", "--arms", "with", "--label", "L1")

        result = bench_run(workspace, run_command, *arguments, *(["--trace"] if trace else []))

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        (call,) = workspace.claude_calls()
        traces = results(workspace) / "traces"
        record = json.loads((results(workspace) / "L1.jsonl").read_text())
        if trace:
            assert call["argv"][4:7] == ["--output-format", "stream-json", "--verbose"]
            assert "--no-session-persistence" not in call["argv"]
            assert [path.name for path in traces.iterdir()] == ["L1-T1-with-r1.jsonl"]
            assert (traces / "L1-T1-with-r1.jsonl").read_text() == stream
            assert (record["cost"], record["turns"], record["subtype"]) == (0.5, 7, "success")
        else:
            assert call["argv"][4:6] == ["--output-format", "json"]
            assert call["argv"][-1] == "--no-session-persistence"
            assert not traces.exists()
            assert (record["cost"], record["turns"], record["subtype"]) == (0.25, 3, "success")

    @pytest.mark.parametrize("effort", ["low", "high", ""])
    def test_writes_effort_when_variable_set(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, effort: str
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "1", "--arms", "without", "--label", "L1"),
            env={EFFORT_VARIABLE: effort},
        )

        assert result.exit_code == 0, result.output
        written = (results(workspace) / ".settings-L1-T1-without-r1.json").read_text()
        assert written == sandbox_line(
            workspace, "L1-T1-without-r1", enabled=False, effort=effort or "medium"
        )

    def test_uses_step_timeouts_when_children_run(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        real = bench_steps.run_child
        seen: set[tuple[str, float | None, bool | None]] = set()

        def spy(argv: list[str], **kwargs: Any) -> Any:
            seen.add((Path(argv[0]).name, kwargs["timeout"], kwargs["own_session"]))
            return real(argv, **kwargs)

        monkeypatch.setattr(bench_steps, "run_child", spy)

        result = bench_run(workspace, run_command, "--runs", "1", "--arms", "with")

        assert result.exit_code == 0, result.output
        # git in the caller's process group; what runs the case's code or the session in its
        # own, so a timeout kills everything it started.
        assert seen == {
            ("git", 1_800, False),
            ("bash", 600, True),
            ("claude", 1_800, True),
            ("python3", 1_800, True),
        }
        assert (bench_steps.AGENT_TIMEOUT, bench_steps.GRADER_TIMEOUT) == (1_800, 1_800)
        assert (bench_steps.GIT_TIMEOUT, bench_steps.SETUP_TIMEOUT) == (1_800, 600)
        assert bench_steps.OUTPUT_LIMIT == 1_048_576

    @pytest.mark.parametrize(
        ("broken", "reason"),
        [("missing", "claude is not on PATH"), ("no-interpreter", "claude could not run: ")],
    )
    def test_reports_run_failure_when_session_cannot_start(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        *,
        broken: str,
        reason: str,
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        claude = workspace.bin / "claude"
        if broken == "missing":
            claude.unlink()
        else:
            # Found on PATH, but the kernel cannot start it: an OSError at launch.
            claude.write_text("#!/no/such/interpreter\n")

        result = bench_run(workspace, run_command, "--runs", "1", "--label", "L1")

        # Each job fails alone, with no record; the run ends with its summary, exit 1.
        assert result.exit_code == 1, result.output
        assert result.stdout == f"\nruns: 0, spent $0.00\n\n{TABLE_HEADER}\n"
        lines = result.stderr.splitlines()
        assert [line.split(": ", 2)[:2] for line in lines] == [
            ["hub bench", "L1-T1-with-r1"],
            ["hub bench", "L1-T1-without-r1"],
        ]
        assert all(line.split(": ", 2)[2].startswith(reason) for line in lines), lines
        assert not (results(workspace) / "L1.jsonl").exists()
        assert workspace.claude_calls() == []
        assert_checkout_untouched(workspace)

    @pytest.mark.parametrize("step", ["checkout", "reset"])
    def test_reports_run_failure_when_overlay_fails(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
        *,
        step: str,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        real = bench_steps.run_child

        def failing_overlay(argv: list[str], **kwargs: Any) -> Any:
            if step in argv and (step == "reset" or "origin/main" in argv):
                return bench_steps.ChildResult(128, b"", b"fatal: overlay broke\n")
            return real(argv, **kwargs)

        monkeypatch.setattr(bench_steps, "run_child", failing_overlay)

        result = bench_run(workspace, run_command, "--runs", "1", "--label", "L1")

        # Never a session on the old config: each job fails alone, with no record.
        assert result.exit_code == 1, result.output
        assert result.stdout == f"\nruns: 0, spent $0.00\n\n{TABLE_HEADER}\n"
        assert result.stderr.splitlines() == [
            f"hub bench: L1-T1-{arm}-r1: overlay {step} failed: fatal: overlay broke"
            for arm in ("with", "without")
        ]
        assert workspace.claude_calls() == []
        assert not (results(workspace) / "L1.jsonl").exists()
        assert_checkout_untouched(workspace)

    def test_refuses_trace_when_path_is_symlink(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        workspace.answer([{"stdout": "secret stream\n"}])
        target = workspace.base / "elsewhere.txt"
        target.write_text("untouched\n")
        traces = results(workspace) / "traces"
        traces.mkdir(parents=True)
        (traces / "L1-T1-with-r1.jsonl").symlink_to(target)

        result = bench_run(
            workspace, run_command, *("--runs", "1", "--arms", "with", "--label", "L1", "--trace")
        )

        assert result.exit_code == 1, result.output
        assert result.stderr == (
            f"hub bench: L1-T1-with-r1: {traces / 'L1-T1-with-r1.jsonl'}:"
            " not opened: links are never followed\n"
        )
        assert target.read_text() == "untouched\n"
        assert workspace.claude_calls() == []
        assert_checkout_untouched(workspace)

    @pytest.mark.parametrize("trace", [True, False], ids=["trace", "no-trace"])
    def test_writes_private_files_when_run(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, trace: bool
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        workspace.answer([{"stdout": workspace.result(0.1, 1, "success")}])
        arguments = ("--runs", "1", "--arms", "with", "--label", "L1")

        result = bench_run(workspace, run_command, *arguments, *(["--trace"] if trace else []))

        assert result.exit_code == 0, result.output
        written = [
            results(workspace) / "L1.jsonl",
            results(workspace) / ".settings-L1-T1-with-r1.json",
        ]
        if trace:
            written.append(results(workspace) / "traces" / "L1-T1-with-r1.jsonl")
        assert {path.name: stat.S_IMODE(path.stat().st_mode) for path in written} == {
            path.name: 0o600 for path in written
        }

    @pytest.mark.parametrize("name", ["L1.jsonl", ".settings-L1-T1-with-r1.json"])
    def test_refuses_result_file_when_path_is_symlink(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, name: str
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        workspace.answer([{"stdout": workspace.result(0.1, 1, "success")}])
        target = workspace.base / "elsewhere.txt"
        target.write_text("untouched\n")
        results(workspace).mkdir(parents=True)
        (results(workspace) / name).symlink_to(target)

        result = bench_run(workspace, run_command, "--runs", "1", "--arms", "with", "--label", "L1")

        assert result.exit_code == 1, result.output
        assert result.stderr.splitlines()[-1].endswith(
            f"{results(workspace) / name}: not opened: links are never followed"
        )
        assert target.read_text() == "untouched\n"
        assert_checkout_untouched(workspace)

    def test_counts_failed_session_at_cap_when_no_result(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # A session that fails with no result event spent an unknown amount: up to its cap.
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        workspace.answer([{"stdout": "not json\n", "stderr": "crashed\n", "rc": 1}])

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "3", "--arms", "with", "--parallel", "1"),
            *("--per-run", "1", "--budget", "2", "--label", "L1"),
        )

        assert result.exit_code == 0, result.output
        written = (results(workspace) / "L1.jsonl").read_text().splitlines()
        assert [json.loads(text)["cost"] for text in written] == [1.0, 1.0]
        assert "STOP: budget cap (spent $2.00, next wave up to $1.00)\n" in result.stdout
        assert "\nruns: 2, spent $2.00\n" in result.stdout
        assert len(workspace.claude_calls()) == 2

    def test_counts_session_at_cap_when_timed_out(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        (workspace.bin / "claude").write_text(
            "#!/bin/sh\nexec python3 -c 'import time; time.sleep(60)'\n"
        )
        monkeypatch.setattr(bench_steps, "AGENT_TIMEOUT", 0.5)

        result = bench_run(
            workspace,
            run_command,
            *("--runs", "2", "--arms", "with", "--parallel", "1"),
            *("--per-run", "1", "--budget", "1.5", "--label", "L1"),
        )

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        timed_out = {"agent_rc": "timeout", "cost": 1.0, "secs": 0}
        record = json.dumps(
            {"label": "L1", "case": "T1", "arm": "with", "run": 1, "model": "claude-sonnet-5"}
            | timed_out
            | grade_part(fixed=False)
            | {"ts": TS}
        )
        assert (results(workspace) / "L1.jsonl").read_text() == f"{record}\n"
        assert result.stdout.startswith(
            f"{record}\nSTOP: budget cap (spent $1.00, next wave up to $1.00)\n"
        )
        assert_checkout_untouched(workspace)

    def test_keeps_record_with_grade_error_when_grader_cannot_start(
        self, bench_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case(test_cmd=["no-such-grader"])])
        workspace.answer([{"stdout": workspace.result(0.25, 3, "success")}])

        result = bench_run(workspace, run_command, "--runs", "1", "--arms", "with", "--label", "L1")

        assert result.exit_code == 1, result.output
        assert result.stderr == "hub bench: L1-T1-with-r1: no-such-grader is not on PATH\n"
        record = json.dumps(
            {"label": "L1", "case": "T1", "arm": "with", "run": 1, "model": "claude-sonnet-5"}
            | agent_part(0.25, 3, "success")
            | {"pass": False, "error": "grade: no-such-grader is not on PATH", "ts": TS}
        )
        assert (results(workspace) / "L1.jsonl").read_text() == f"{record}\n"
        assert "\nruns: 1, spent $0.25\n" in result.stdout
        assert_checkout_untouched(workspace)


# A grandchild a step leaves behind: it holds an exclusive lock on argv[1] until it dies, then
# appends its pid to argv[1] + ".pid" (a second one can only start once the first is gone).
SLEEPER = """import fcntl, os, sys, time
lock = open(sys.argv[1], "w")
fcntl.flock(lock, fcntl.LOCK_EX)
with open(sys.argv[1] + ".pid", "a") as pids:
    pids.write(f"{os.getpid()}\\n")
time.sleep(60)
"""
PROBE_DEADLINE = 5.0


def sleeper_command(workspace: Workspace) -> tuple[str, Path]:
    """A shell command that starts the sleeper in the background and waits; its lock file."""
    script = workspace.base / "sleeper.py"
    script.write_text(SLEEPER)
    lock = workspace.base / "sleeper.lock"
    return f"python3 {shlex.quote(str(script))} {shlex.quote(str(lock))} & wait", lock


def is_lock_free_within(lock: Path, deadline: float) -> bool:
    end = time.monotonic() + deadline
    with lock.open("r+") as file:
        while True:
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.01)
            else:
                return True


@contextlib.contextmanager
def sleepers_killed(lock: Path) -> Iterator[None]:
    """Kill any sleeper still alive after the block, whatever the block asserted."""
    try:
        yield
    finally:
        pids = Path(f"{lock}.pid")
        for pid in pids.read_text().split() if pids.exists() else ():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid), signal.SIGKILL)


def finished_pid() -> int:
    """The pid of a process that has ended (and been reaped)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603 - this interpreter
    child.wait()
    return child.pid


class TestIsolation:
    @pytest.mark.parametrize("step", ["setup", "grader"])
    def test_kills_process_group_when_step_times_out(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
        *,
        step: str,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        command, lock = sleeper_command(workspace)
        if step == "setup":
            monkeypatch.setattr(bench_steps, "SETUP_TIMEOUT", 1.0)
            broken = workspace.case(setup_cmd=command)
        else:
            monkeypatch.setattr(bench_steps, "GRADER_TIMEOUT", 1.0)
            broken = workspace.case(test_cmd=["bash", "-c", command, "grader"])
        workspace.write_cases([broken, workspace.case(id="T2")])

        with sleepers_killed(lock):
            result = validate(workspace, run_command)

            assert result.exit_code == 1, result.output
            assert result.stderr == (
                "hub bench: T1 parent: bash timed out after 1 s\n"
                "hub bench: T1 merge: bash timed out after 1 s\n"
            )
            # The next case still runs.
            assert result.stdout == OK_LINES.replace("T1 ", "T2 ")
            # The merge's sleeper started only once the parent's had died, and it died too.
            assert len(Path(f"{lock}.pid").read_text().split()) == 2
            assert is_lock_free_within(lock, PROBE_DEADLINE), "a sleeper is still alive"
        assert_checkout_untouched(workspace)

    def test_kills_sessions_when_run_interrupted(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        command, lock = sleeper_command(workspace)
        # Bounds the test should the kill fail: the run would end at this timeout.
        monkeypatch.setattr(bench_steps, "SETUP_TIMEOUT", 30.0)
        # T1 ends only once T2's setup has started its sleeper; T1's record then interrupts.
        waiter = f"while [ ! -s {shlex.quote(str(lock))}.pid ]; do :; done; echo ready > setup.txt"
        workspace.write_cases(
            [workspace.case(setup_cmd=waiter), workspace.case(id="T2", setup_cmd=command)]
        )

        def interrupt(*args: Any) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(bench_steps, "_append_record", interrupt)

        with sleepers_killed(lock):
            started = time.monotonic()
            result = bench_run(
                workspace, run_command, "--runs", "1", "--arms", "with", "--parallel", "2"
            )

            assert result.exit_code == 130, result.output
            assert time.monotonic() - started < 30.0
            assert is_lock_free_within(lock, PROBE_DEADLINE), "the sleeper is still alive"
        assert_checkout_untouched(workspace)

    @pytest.mark.parametrize("mode", ["validate", "run"])
    def test_refuses_bench_when_workspace_locked(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, mode: str
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        lock = lock_path(workspace)
        lock.parent.mkdir()
        # This test's own process: alive while the command runs.
        lock.write_text(f"{os.getpid()}\n")
        arguments = ("--validate",) if mode == "validate" else ("--runs", "1")

        result = bench_run(workspace, run_command, *arguments)

        assert (result.exit_code, result.stdout) == (1, "")
        assert result.stderr == (
            f"hub bench: another hub bench (pid {os.getpid()}) is running in this workspace;"
            f" wait for it to end (lock {lock})\n"
        )
        assert lock.read_text() == f"{os.getpid()}\n"
        assert not (bench_folder(workspace) / "wt").exists()
        assert not (bench_folder(workspace) / "results").exists()
        assert workspace.claude_calls() == []

    @pytest.mark.parametrize("content", ["stale", "no-pid"])
    def test_refuses_bench_when_lock_left_behind(
        self, bench_workspace: Workspace, run_command: CommandRunner, *, content: str
    ) -> None:
        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        lock = lock_path(workspace)
        lock.parent.mkdir()
        pid = finished_pid()
        lock.write_text(f"{pid}\n" if content == "stale" else "x\n")

        result = validate(workspace, run_command)

        # Never removed by the command: two of them could each take the other's for stale.
        assert (result.exit_code, result.stdout) == (1, "")
        held = f"pid {pid}, which is not running" if content == "stale" else "no pid in it"
        assert result.stderr == (
            f"hub bench: the lock {lock} was left behind ({held}):"
            " delete it if no hub bench is running in this workspace\n"
        )
        assert lock.exists()
        assert not (bench_folder(workspace) / "wt").exists()

    def test_takes_lock_with_own_pid_when_bench_runs(
        self,
        bench_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_hub.cli import bench_steps  # noqa: PLC0415 - the module this test patches

        workspace = bench_workspace
        workspace.write_cases([workspace.case()])
        seen: list[str] = []
        real = bench_steps.run_child

        def spy(argv: list[str], **kwargs: Any) -> Any:
            seen.append(lock_path(workspace).read_text())
            return real(argv, **kwargs)

        monkeypatch.setattr(bench_steps, "run_child", spy)

        result = validate(workspace, run_command)

        assert (result.exit_code, result.stdout) == (0, OK_LINES)
        assert set(seen) == {f"{os.getpid()}\n"}
        assert_checkout_untouched(workspace)
