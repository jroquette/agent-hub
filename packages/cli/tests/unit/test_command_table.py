import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer.main
from typer.models import DefaultPlaceholder

from agent_hub.cli import command_table
from agent_hub.cli.main import app

# The 18 commands and 7 groups of `hub --help` on v0.27.1, in their order (golden/hub_help.txt).
RECORDED_ORDER = [
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
    "web",
    "validate-output",
    "search",
    "mcp",
    "skill-usage",
    "workflow",
    "step",
    "env",
    "repo",
    "action",
    "scenario",
    "brain",
]
# The module each of those commands is defined in on v0.27.1 (its callback's or its Typer's).
COMMAND_MODULES = frozenset(
    f"agent_hub.cli.{name}"
    for name in (
        "collect",
        "generator",
        "sync_command",
        "doctor_command",
        "setup_command",
        "worktree_command",
        "brief_command",
        "agent_command",
        "next_command",
        "run_engine",
        "ship_command",
        "bench_command",
        "start_command",
        "web_command",
        "validate_output_command",
        "search_command",
        "mcp_command",
        "skill_usage_command",
        "workflow_command",
        "step_command",
        "env_command",
        "repo_command",
        "action_command",
        "scenario_command",
        "brain_command",
    )
)
# Help data the root group's listing and Typer's Rich help read from each command.
HELP_FIELDS = ("help", "short_help", "hidden", "rich_help_panel", "deprecated", "add_help_option")
# Run first in each child: names the command modules it has loaded so far.
LOADED_PRELUDE = (
    "import json, sys\n"
    f"COMMAND_MODULES = {sorted(COMMAND_MODULES)!r}\n"
    "def loaded_command_modules():\n"
    "    return [m for m in COMMAND_MODULES if m in sys.modules]\n"
)


def run_child(code: str, cwd: Path) -> Any:
    """Run ``code`` in a fresh interpreter and return the JSON of its last stdout line."""
    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code],
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "_TYPER_FORCE_DISABLE_TERMINAL": "1",
            "COLUMNS": "100",
        },
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def plain(value: object) -> object:
    return value.value if isinstance(value, DefaultPlaceholder) else value


def test_matches_loaded_command_help_when_table_is_read() -> None:
    group = typer.main.get_command(app)
    assert isinstance(group, typer.core.TyperGroup)
    with group.make_context("hub", ["--help"], resilient_parsing=True) as ctx:
        listed = dict(group.commands)
        assert list(listed) == RECORDED_ORDER

        loaded = {}
        for name in RECORDED_ORDER:
            resolved_name, command, _ = group.resolve_command(ctx, [name])
            assert resolved_name == name
            assert command is not None
            loaded[name] = command

    # Self-check: the listed commands come from the table, not from the loaded modules.
    assert [name for name in RECORDED_ORDER if listed[name] is loaded[name]] == []
    for field in HELP_FIELDS:
        table = {name: plain(getattr(listed[name], field)) for name in RECORDED_ORDER}
        real = {name: plain(getattr(loaded[name], field)) for name in RECORDED_ORDER}
        assert table == real, field


def test_builds_commands_with_root_exception_setting_when_loaded() -> None:
    # The commands loaded on demand take this value, as app.command would take the root app's.
    assert app.pretty_exceptions_short is command_table.PRETTY_EXCEPTIONS_SHORT


def test_lists_commands_in_recorded_order_when_help_built(tmp_path: Path) -> None:
    code = LOADED_PRELUDE + (
        "import typer.main\n"
        "from typer.testing import CliRunner\n"
        "from agent_hub.cli.main import app\n"
        "assert CliRunner().invoke(app, ['--help']).exit_code == 0\n"
        "group = typer.main.get_command(app)\n"
        "with group.make_context('hub', ['--help'], resilient_parsing=True) as ctx:\n"
        "    names = group.list_commands(ctx)\n"
        "print(json.dumps({'names': names, 'loaded': loaded_command_modules()}))\n"
    )

    seen = run_child(code, tmp_path)

    assert seen["names"] == RECORDED_ORDER
    # The help is built from the table: no command module is imported for it.
    assert seen["loaded"] == []


def test_imports_only_its_module_when_command_runs(tmp_path: Path) -> None:
    code = LOADED_PRELUDE + (
        "from typer.testing import CliRunner\n"
        "from agent_hub.cli.main import app\n"
        "result = CliRunner().invoke(app, ['repo', '--help'])\n"
        "assert result.exit_code == 0, result.output\n"
        "assert 'list' in result.output\n"
        "print(json.dumps(loaded_command_modules()))\n"
    )

    loaded = run_child(code, tmp_path)

    assert loaded == ["agent_hub.cli.repo_command"]


def test_loads_every_command_module_when_all_imported(tmp_path: Path) -> None:
    code = LOADED_PRELUDE + (
        "from agent_hub.cli import command_table\n"
        "command_table.import_all()\n"
        "print(json.dumps(loaded_command_modules()))\n"
    )

    loaded = run_child(code, tmp_path)

    assert len(COMMAND_MODULES) == 25
    assert loaded == sorted(COMMAND_MODULES)
