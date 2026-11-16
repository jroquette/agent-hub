"""Typer's private click (``typer._click``), reached through one module of the cli.

Typer exports no public module for these names; this test fails first when a typer release
moves or renames one, and the scan keeps every other cli module off the private path.
"""

from pathlib import Path

import typer
import typer.core

from agent_hub.cli import vendored_click
from agent_hub.cli.vendored_click import ClickException, Command, Context, ParameterSource

PRIVATE_MODULE = "typer._click"


def test_exports_each_vendored_name_when_imported() -> None:
    assert sorted(vendored_click.__all__) == [
        "ClickException",
        "Command",
        "Context",
        "ParameterSource",
    ]
    assert issubclass(typer.Context, Context)
    assert issubclass(typer.core.TyperCommand, Command)
    assert issubclass(typer.BadParameter, ClickException)
    assert ParameterSource.DEFAULT.name == "DEFAULT"
    assert ParameterSource.COMMANDLINE.name == "COMMANDLINE"


def test_imports_private_click_only_in_vendored_module_when_cli_sources_scanned() -> None:
    sources = Path(vendored_click.__file__).parent

    importers = sorted(
        path.relative_to(sources).as_posix()
        for path in sources.rglob("*.py")
        if PRIVATE_MODULE in path.read_text(encoding="utf-8")
    )

    assert importers == ["vendored_click.py"]
