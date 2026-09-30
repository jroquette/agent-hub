from importlib.metadata import version

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
    for command in ("collect", "init", "sync", "doctor"):
        assert command in unstyle(result.stdout)


def test_shows_arguments_when_init_help_requested() -> None:
    result = CliRunner().invoke(app, ["init", "--help"])

    assert result.exit_code == 0
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
    # The defaults are shown, not eaten as markup; a wrapped cell reads as one line of words.
    words = " ".join(unstyle(result.stdout).replace("\N{BOX DRAWINGS LIGHT VERTICAL}", " ").split())
    assert "Author of commits and PRs [default: git user.name]." in words
