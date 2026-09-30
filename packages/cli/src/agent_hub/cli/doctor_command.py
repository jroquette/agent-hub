"""``hub doctor``: check a hub against the rules of this release, read-only.

The pipeline of the AGH-11 spec, in the current folder (its real path, taken once, no walk-up):
an ``--only`` id that is no rule at all is a usage error (exit 2) before anything is read; no
``hub.json`` entry in the folder (a dangling link counts as one) exits 2 saying it is not a hub.
Then ``hub.json`` is read once into its config, or why it cannot be used: on a failed config
only ``config.schema`` and ``platform.version`` run, and no other file is read. Otherwise the
selection (``doctor.rules``, ``modules`` and ``--only``; a refusal exits 2, a note goes to
stderr), then the hub's files the selected rules need, read without following links (git runs
only when a rule reads the listing). The findings go to stdout as lines and totals, or as one
JSON object with ``--json``; the exit is 1 when one is an error, else 0.
"""

import os
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import root_or_exit
from agent_hub.cli.doctor_report import report_json, report_lines
from agent_hub.cli.hub_config_reader import DISTRIBUTION, FILE_LABEL, read_hub_bytes
from agent_hub.cli.init_report import shown_path
from agent_hub.core.doctor.config_rules import config_state
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import (
    Selection,
    UsageProblem,
    count_findings,
    run_rules,
    select_rules,
)
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, HubFiles, hub_paths
from agent_hub.core.hub_config.doctor_rules import RULE_IDS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.doctor_tree import read_doctor_tree

# A usage error, an unknown or unrunnable ``--only`` id, or a folder that is not a hub.
NOT_A_HUB_EXIT: Final = 2
NOT_A_HUB: Final = (
    "not a hub: no hub.json in this folder (hub doctor runs in the hub folder, never a parent)"
)
# At least one finding is an error.
FINDINGS_FAILED: Final = 1
# A failed config reads no file: only the config rules run, and they read hub.json alone.
_NO_FILES: Final = HubFiles(entries={}, listed=(), problem=None)


def doctor(
    context: typer.Context,
    *,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only", metavar="RULE", help="Run only this rule (and config.schema); repeatable."
        ),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print one JSON object instead of lines.")
    ] = False,
) -> None:
    """Check the hub's rules, links, dead references and instruction size."""
    wanted = tuple(only or ())
    unknown = [rule_id for rule_id in wanted if rule_id not in RULE_IDS]
    if unknown:
        context.fail(f"unknown rule in --only: {shown_path(unknown[0])}")
    root = root_or_exit(None)
    _hub_or_exit(root)
    running = version(DISTRIBUTION)
    config = config_state(read_hub_bytes(Path(root, FILE_LABEL)), running_version=running)
    selection = select_rules(REGISTRY, config=config, only=wanted)
    if isinstance(selection, UsageProblem):
        context.fail(selection.message)
    for note in selection.notes:
        typer.echo(note, err=True)
    hub = _NO_FILES if isinstance(config, ConfigFailure) else _hub_files(root, config, selection)
    # No rule of this commit reads the lock.
    snapshot = DoctorSnapshot(config=config, running_version=running, hub=hub, lock=None)
    findings = run_rules(selection, snapshot)
    if as_json:
        typer.echo(report_json(findings), nl=False)
    else:
        for line in report_lines(findings):
            typer.echo(line)
    if count_findings(findings).has_errors:
        raise typer.Exit(FINDINGS_FAILED)


def _hub_or_exit(root: str) -> None:
    """Exit 2 unless the root holds a ``hub.json`` entry; any other look is left to the reader.

    Only an absent entry means "not a hub" (spec Q-25): a dangling link, a folder or an entry
    that cannot be looked at is a ``config.schema`` finding the reader names.
    """
    try:
        os.lstat(os.path.join(root, FILE_LABEL))
    except FileNotFoundError:
        typer.echo(f"{shown_path(root)}: {NOT_A_HUB}", err=True)
        raise typer.Exit(NOT_A_HUB_EXIT) from None
    except OSError:
        return


def _hub_files(root: str, config: HubConfig, selection: Selection) -> HubFiles:
    """The files the selected rules read: the fixed paths, and the listing when one needs it."""
    listing = any(Read.HUB_LISTING in rule.reads for rule in selection.rules)
    return read_doctor_tree(Path(root), by_path=hub_paths(config), listing=listing)
