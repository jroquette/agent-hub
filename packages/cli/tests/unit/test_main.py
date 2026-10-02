from importlib.metadata import version

import pytest
import typer.core
from click import unstyle
from typer.testing import CliRunner

from agent_hub.cli.main import app


def test_prints_version_when_version_option_given() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == version("agent-hub-cli")


def test_lists_commands_when_help_requested() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "collect",
        "init",
        "sync",
        "doctor",
        "worktree",
        "brief",
        "agent",
        "next",
        "run",
        "bench",
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
