"""``hub bench``: the configuration benchmark, ported from the hub's script (AC-17.14 to AC-17.16).

This module re-expresses hub ``scripts/bench.py`` at hub commit ``5b56604`` and its
characterization (``tests/characterization/test_bench.py``) against the command; every port
difference of the plan is asserted here. ``TestUsage`` runs in process in a copy of the ``DEMO``
hub (``demo_hub``), with ``bench`` selected where a test needs it: each refusal is a usage error,
exit 2, or a reader failure, exit 1, before any child process. The other tests run in the hub
suite's bench workspace (``bench_workspace``: ``ws/hub`` selecting ``bench``, repo ``ws/api``)
with a fake ``claude`` on ``PATH``.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import bench_command
from agent_hub.cli.command_exits import NOT_IMPLEMENTED, NOT_IMPLEMENTED_EXIT_CODE
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

        # Past every check: the command reaches the stub the next tasks replace.
        assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE, result.output
        assert result.stdout == ""
        assert result.stderr == f"{NOT_IMPLEMENTED}\n"
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
