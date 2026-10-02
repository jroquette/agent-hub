"""``hub run``: one tracker issue to a PR, every tracker read and write through the port.

The hub is ``AGENT_HUB_ROOT`` or the cwd; run from a worktree of the hub repo, its main checkout
is the hub (its ``hub.json``, Q-23). Usage problems exit 2 before any tracker call or child
process: an option out of range, an issue not shaped ``<team>-<n>``, a ``--repo`` that is not a
repo ``dir`` of ``hub.json``, a folder that is not a hub (D15).
"""

import math
import os
import re
import shutil
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import fail, not_implemented
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit, main_checkout
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.tracker.tracker_client import ISSUE_ID_PATTERN

COMMAND: Final = "run"
DEFAULT_MAX_TURNS: Final = 40
DEFAULT_BUDGET_USD: Final = 3.0
DEFAULT_MODEL: Final = "sonnet"
MODEL_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")
_PREFIX: Final = f"hub {COMMAND}"


class RunStart(StrEnum):
    """Where a run starts: the implementing session, or the gate on the commits already made."""

    IMPLEMENT = "implement"
    VERIFY = "verify"


class Effort(StrEnum):
    """The implementing session's ``effortLevel``."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _budget(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        msg = "use a number of USD above 0"
        raise typer.BadParameter(msg)
    return value


def _model(value: str) -> str:
    if not MODEL_PATTERN.fullmatch(value):
        msg = "use 1 to 64 of A-Z a-z 0-9 . _ -"
        raise typer.BadParameter(msg)
    return value


def run(
    context: typer.Context,
    issue: Annotated[
        str, typer.Argument(metavar="ISSUE", help="The tracker issue, <team>-<n> (DEM-1).")
    ],
    *,
    repo: Annotated[
        str,
        typer.Option("--repo", metavar="REPO", help="The repo to change (its dir in hub.json)."),
    ],
    live: Annotated[
        bool, typer.Option("--live", help="Run it; without it, print what would run.")
    ] = False,
    max_turns: Annotated[
        int, typer.Option("--max-turns", min=1, help="Turns of the implementing session.")
    ] = DEFAULT_MAX_TURNS,
    budget: Annotated[
        float,
        typer.Option("--budget", callback=_budget, help="USD cap of the implementing session."),
    ] = DEFAULT_BUDGET_USD,
    model: Annotated[
        str, typer.Option("--model", callback=_model, help="Model of the implementing session.")
    ] = DEFAULT_MODEL,
    start: Annotated[
        RunStart,
        typer.Option("--from", help="verify: gate, PR and report on the commits already made."),
    ] = RunStart.IMPLEMENT,
    effort: Annotated[
        Effort, typer.Option("--effort", help="effortLevel of the implementing session.")
    ] = Effort.MEDIUM,
) -> None:
    """Take one tracker issue to a PR: worktree, implementing session, gate, PR, report."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = _hub_checkout(root)
    config = load_hub_config_or_exit(hub / FILE_LABEL)
    _refuse_usage(context, config, issue=issue, repo=repo)
    not_implemented()


def _hub_checkout(root: Path) -> Path:
    """The hub's main checkout; git runs only when ``root`` is a worktree (its ``.git`` a file)."""
    if not os.path.isfile(root / ".git"):
        return root
    git = shutil.which("git")
    if git is None:
        fail(f"{_PREFIX}: git is not on PATH; install git")
    try:
        return main_checkout(root, git=os.path.abspath(git), environ=os.environ)
    except OSError as error:
        fail(f"{_PREFIX}: git could not run: {error.strerror or error}")


def _refuse_usage(context: typer.Context, config: HubConfig, *, issue: str, repo: str) -> None:
    team = config.tracker.team
    if not (ISSUE_ID_PATTERN.fullmatch(issue) and issue.startswith(f"{team}-")):
        context.fail(f"issue must look like {team}-<n> (e.g. {team}-1)")
    dirs = [entry.dir for entry in config.repos]
    if repo not in dirs:
        context.fail(f"unknown repo in --repo: {shown_path(repo)}; use one of: {' '.join(dirs)}")
