from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from agent_hub.cli.main import app


@pytest.mark.parametrize(
    "args",
    [
        ["sync"],
        ["doctor"],
    ],
    ids=["sync", "doctor"],
)
def test_exits_two_when_stub_command_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2
    assert "not implemented yet (Phase 1)" in result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        ["init", "demo", "--repos", "acme/a", "--tracker", "linear:DEM", "--unknown"],
        ["init", "demo", "--config", "hub.json"],
        ["init", "--repos", "acme/a", "--config", "hub.json"],
        ["init", "--dir", "hub"],
        ["init", "demo", "--tracker", "linear:DEM"],
        ["init", "demo", "--repos", "acme/a"],
    ],
    ids=[
        "unknown-option",
        "project-with-config",
        "flag-with-config",
        "neither-project-nor-config",
        "no-repos",
        "no-tracker",
    ],
)
def test_exits_two_when_init_usage_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, args: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2
    assert "Usage:" in result.stderr
    assert "not implemented yet" not in result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("command", "description"),
    [
        ("sync", "Reapply the hub templates without overwriting what the project customized."),
        ("doctor", "Check the hub's rules, links, dead references and instruction size."),
    ],
    ids=["sync", "doctor"],
)
def test_describes_command_when_help_requested(command: str, description: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"])

    assert result.exit_code == 0
    assert description in " ".join(unstyle(result.stdout).split())
