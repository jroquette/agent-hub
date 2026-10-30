import json
import os
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
import typer.core
from click import unstyle
from typer.testing import CliRunner

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.testing.repo_edit_cases import a_repos_document

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


def test_loads_no_web_or_store_module_when_main_imported(tmp_path: Path) -> None:
    code = (
        "import json, sys\n"
        "HEAVY = ('fastapi', 'sqlalchemy', 'alembic', 'agent_hub.api')\n"
        "def heavy():\n"
        "    return sorted(m for m in sys.modules if m in HEAVY or m.startswith(HEAVY_DOTTED))\n"
        "HEAVY_DOTTED = tuple(name + '.' for name in HEAVY)\n"
        "seen = {}\n"
        "import agent_hub.cli.main\n"
        "seen['import'] = heavy()\n"
        "from typer.testing import CliRunner\n"
        "for option in ('--version', '--help'):\n"
        "    result = CliRunner().invoke(agent_hub.cli.main.app, [option])\n"
        "    assert result.exit_code == 0, result.output\n"
        "    seen[option] = heavy()\n"
        "import fastapi\n"
        "seen['self-check'] = heavy()\n"
        "print(json.dumps(seen))\n"
    )

    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code],
        env=fixed_help_env(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.splitlines()[-1])
    # Self-check: the probe sees a heavy module once one is imported.
    assert "fastapi" in seen.pop("self-check")
    assert seen == {"import": [], "--version": [], "--help": []}


# What `hub repo list` and `hub env list` never use (AGH-607, AC-15): the workflow catalog and the
# modules that only reach for it.
CATALOG_CHAIN = (
    "agent_hub.core.workflows.catalog",
    "agent_hub.cli.run_children",
    "agent_hub.core.hub_files.plan_init",
    "agent_hub.core.doctor.snapshot",
)


@pytest.mark.parametrize(
    ("command", "document", "first_line"),
    [
        (
            "repo",
            a_repos_document,
            "demo-api (acme/demo-api, app, branch main): "
            "check_fast=make check-fast, check=make check",
        ),
        (
            "env",
            an_environments_document,
            "local (write, hub.json): docker compose stack on this machine",
        ),
    ],
    ids=["repo-list", "env-list"],
)
def test_loads_no_workflow_catalog_when_list_command_runs(
    tmp_path: Path, *, command: str, document: Callable[[], dict[str, Any]], first_line: str
) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    pinned = document()
    pinned["platform"]["version"] = version("agent-hub-cli")
    (hub / "hub.json").write_text(json.dumps(pinned, indent=2) + "\n")
    code = (
        "import importlib, json, sys\n"
        f"CHAIN = {CATALOG_CHAIN!r}\n"
        "def loaded():\n"
        "    return sorted(m for m in CHAIN if m in sys.modules)\n"
        "from typer.testing import CliRunner\n"
        "import agent_hub.cli.main\n"
        "def run(*args):\n"
        "    env = {'AGENT_HUB_ROOT': sys.argv[1]}\n"
        "    result = CliRunner().invoke(agent_hub.cli.main.app, list(args), env=env)\n"
        "    assert result.exit_code == 0, result.output\n"
        "    return result.stdout\n"
        "seen = {'before': loaded()}\n"
        "seen['output'] = run(sys.argv[2], 'list')\n"
        "seen['list'] = loaded()\n"
        "run('workflow', 'list')\n"
        "seen['self-check workflow list'] = loaded()\n"
        "for name in CHAIN:\n"
        "    importlib.import_module(name)\n"
        "seen['self-check import'] = loaded()\n"
        "print(json.dumps(seen))\n"
    )

    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code, str(hub), command],
        env=fixed_help_env(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.splitlines()[-1])
    # Self-check: the command really listed the hub, a command that needs the catalog loads it, and
    # the probe sees every name of the chain once it is imported.
    assert seen.pop("output").splitlines()[0] == first_line
    assert "agent_hub.core.workflows.catalog" in seen.pop("self-check workflow list")
    assert seen.pop("self-check import") == sorted(CATALOG_CHAIN)
    assert seen == {"before": [], "list": []}


def test_suggests_close_name_when_command_is_unknown() -> None:
    result = CliRunner().invoke(app, ["rpo"])

    assert result.exit_code == 2
    assert "No such command 'rpo'. Did you mean 'repo'?" in unstyle(result.output)


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
