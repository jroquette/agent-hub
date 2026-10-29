import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest
import typer.core
from click import unstyle
from typer.testing import CliRunner

from agent_hub.cli.main import app

HELP_GOLDEN = Path(__file__).parent / "golden" / "hub_help.txt"
# Typer reads the terminal variables once, at import, so the help runs in a child whose
# environment is built from scratch: no colour (no GITHUB_ACTIONS, FORCE_COLOR, PY_COLORS, NO_COLOR,
# TERM), a fixed width, and Rich still drawing its panels.
HELP_ARGV = (sys.executable, "-c", "from agent_hub.cli.main import app; app(prog_name='hub')")


def fixed_help_env() -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "_TYPER_FORCE_DISABLE_TERMINAL": "1",
        "TERMINAL_WIDTH": "100",
        "COLUMNS": "100",
    }


def golden_update_mode() -> bool:
    """Whether ``GOLDEN_UPDATE=1`` asks to rewrite the golden; fails the test when ``CI`` is set."""
    if os.environ.get("GOLDEN_UPDATE") != "1":
        return False
    if os.environ.get("CI"):
        pytest.fail(
            "GOLDEN_UPDATE=1 is refused when CI is set: goldens are regenerated locally, "
            "reviewed and committed"
        )
    return True


def test_prints_version_when_version_option_given() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == version("agent-hub-cli")


def test_prints_recorded_help_when_help_requested(tmp_path: Path) -> None:
    """The golden was written from v0.27.1 (``GOLDEN_UPDATE=1``): the same 18 commands and 7 groups,
    same order, same help text, byte for byte."""
    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [*HELP_ARGV, "--help"],
        env=fixed_help_env(),
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stderr == b""
    if golden_update_mode():
        HELP_GOLDEN.parent.mkdir(exist_ok=True)
        HELP_GOLDEN.write_bytes(result.stdout)
    # Self-check: the child drew Rich's panels and no colour code.
    assert "\N{BOX DRAWINGS LIGHT ARC DOWN AND RIGHT}".encode() in result.stdout
    assert b"\x1b[" not in result.stdout
    assert result.stdout == HELP_GOLDEN.read_bytes()


def test_lists_commands_when_help_requested() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "collect",
        "init",
        "sync",
        "doctor",
        "setup",
        "worktree",
        "brief",
        "agent",
        "next",
        "run",
        "ship",
        "bench",
        "start",
        "validate-output",
        "search",
        "mcp",
        "skill-usage",
    ):
        assert command in unstyle(result.stdout)


@pytest.mark.parametrize("use_rich", [True, False], ids=["rich", "plain"])
def test_shows_arguments_when_init_help_requested(
    monkeypatch: pytest.MonkeyPatch, *, use_rich: bool
) -> None:
    # TYPER_USE_RICH is read once at import, so the plain case sets what it would have set.
    monkeypatch.setattr(typer.core, "HAS_RICH", use_rich)

    result = CliRunner().invoke(app, ["init", "--help"], env={"COLUMNS": "120"})

    assert result.exit_code == 0
    # Self-check: the patch took effect, so both renderings are really tested.
    assert ("\N{BOX DRAWINGS LIGHT VERTICAL}" in result.stdout) is use_rich
    # Under CI (GITHUB_ACTIONS) Typer colours the help, splitting option names with ANSI codes.
    for name in (
        "PROJECT",
        "--repos",
        "--tracker",
        "--branch-prefix",
        "--author-name",
        "--author-email",
        "--hub-repo",
        "--config",
        "--dir",
    ):
        assert name in unstyle(result.stdout)
    # The defaults are shown, not eaten as markup (Click puts a described default in parentheses);
    # a wrapped cell reads as one line of words.
    words = " ".join(unstyle(result.stdout).replace("\N{BOX DRAWINGS LIGHT VERTICAL}", " ").split())
    for shown in (
        "Author of commits and PRs. [default: (git user.name)]",
        "Author's email. [default: (git user.email)]",
        "GitHub owner/name of the hub. [default: (the hub folder's GitHub origin)]",
        "Folder to write the hub in. [default: (the current folder)]",
    ):
        assert shown in words
