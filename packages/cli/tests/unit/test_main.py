from importlib.metadata import version

from typer.testing import CliRunner

from agent_hub.cli.main import app


def test_prints_version_when_version_option_given() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == version("agent-hub-cli")
