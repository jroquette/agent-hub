from importlib.metadata import version

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
        assert command in result.stdout


def test_shows_arguments_when_init_help_requested() -> None:
    result = CliRunner().invoke(app, ["init", "--help"])

    assert result.exit_code == 0
    for name in ("PROJECT", "--repos", "--tracker"):
        assert name in result.stdout
