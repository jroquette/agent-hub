"""``hub run``: one issue from the tracker to a PR through the ``TrackerClient`` port (AC-27.14 on).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``: team ``DEM``,
repos ``demo-api`` and ``demo-web``, default branch ``trunk``, branch prefix ``jdoe/``).

This module re-expresses hub ``tests/test_agent_runner.py`` at hub commit ``300559b``, the old
runner script's tests, against the command; the full matrix of cases lives here.
``TestUsage`` replaces its usage checks (``--repo`` outside ``hub.json``, an issue without the
team's prefix): each refusal is a usage error, exit 2, before any tracker call or child process.
"""

import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
# What a refused run must never reach: the tracker, or any child process.
GUARDED = ("resolve_tracker_client", "run_child", "stream_child")


class Spy:
    """Every guarded call any ``agent_hub.cli`` module makes: ``(name, argv or None)``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def guard(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def spy(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args[0] if args and name != GUARDED[0] else None))
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


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub run" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


SHAPE = "issue must look like DEM-<n> (e.g. DEM-1)"


class TestUsage:
    def test_lists_options_with_defaults_when_help_requested(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "run", "--help")

        assert result.exit_code == 0
        words = " ".join(unstyle(result.stdout).replace(BOX_CHARACTERS[0], " ").split())
        for text in (
            "ISSUE",
            "--repo",
            "--live",
            "--max-turns",
            "[default: 40]",
            "--budget",
            "[default: 3",
            "--model",
            "[default: sonnet]",
            "--from",
            "implement|verify",
            "[default: implement]",
            "--effort",
            "low|medium|high",
            "[default: medium]",
        ):
            assert text in words, text

    @pytest.mark.parametrize("issue", ["dem-1", "OPS-1", "DEM-0", "DEM-1x", "DEM-"])
    def test_refuses_issue_when_shape_wrong(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy, *, issue: str
    ) -> None:
        result = run_command(demo_workspace.hub, "run", issue, "--repo", "demo-api")

        assert_refused(result, SHAPE)
        assert spy.calls == []

    def test_refuses_repo_when_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy
    ) -> None:
        result = run_command(demo_workspace.hub, "run", "DEM-1", "--repo", "nope")

        assert_refused(result, "unknown repo in --repo: nope; use one of: demo-api demo-web")
        assert spy.calls == []

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ((), "Missing argument 'ISSUE'."),
            (("--repo", "demo-api"), "Missing argument 'ISSUE'."),
            (("DEM-1",), "Missing option '--repo'."),
        ],
        ids=["nothing", "no-issue", "no-repo"],
    )
    def test_refuses_when_issue_or_repo_missing(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        arguments: tuple[str, ...],
        message: str,
    ) -> None:
        result = run_command(demo_workspace.hub, "run", *arguments)

        assert_refused(result, message)
        assert spy.calls == []

    @pytest.mark.parametrize(
        ("option", "value", "message"),
        [
            ("--max-turns", "0", "Invalid value for '--max-turns': 0 is not in the range x>=1."),
            (
                "--budget",
                "0",
                BUDGET := "Invalid value for '--budget': use a number of USD above 0",
            ),
            ("--budget", "-1", BUDGET),
            ("--budget", "inf", BUDGET),
            ("--budget", "nan", BUDGET),
            (
                "--model",
                "m" * 65,
                MODEL := "Invalid value for '--model': use 1 to 64 of A-Z a-z 0-9 . _ -",
            ),
            ("--model", "son net", MODEL),
            ("--model", "", MODEL),
            (
                "--from",
                "plan",
                "Invalid value for '--from': 'plan' is not one of 'implement', 'verify'.",
            ),
            (
                "--effort",
                "huge",
                "Invalid value for '--effort': 'huge' is not one of 'low', 'medium', 'high'.",
            ),
        ],
        ids=[
            "turns-zero",
            "budget-zero",
            "budget-negative",
            "budget-inf",
            "budget-nan",
            "model-long",
            "model-space",
            "model-empty",
            "from-plan",
            "effort-huge",
        ],
    )
    def test_refuses_option_when_value_invalid(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        spy: Spy,
        *,
        option: str,
        value: str,
        message: str,
    ) -> None:
        result = run_command(
            demo_workspace.hub, "run", "DEM-1", "--repo", "demo-api", option, value
        )

        assert_refused(result, message)
        assert spy.calls == []

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, run_command: CommandRunner, spy: Spy
    ) -> None:
        result = run_command(demo_workspace.ws, "run", "DEM-1", "--repo", "demo-api")

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{demo_workspace.ws}: not a hub: no hub.json in this folder"
            " (hub run runs in the hub folder or through ./hub)\n"
        )
        assert spy.calls == []
