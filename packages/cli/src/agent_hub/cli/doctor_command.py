"""``hub doctor``: check a hub against the rules of this release, read-only.

The pipeline of the AGH-11 spec, in the current folder (its real path, taken once, no walk-up):
an ``--only`` id that is no rule at all is a usage error (exit 2) before anything is read; no
``hub.json`` entry in the folder (a dangling link counts as one) exits 2 saying it is not a hub.
Then ``hub.json`` is read once into its config, or why it cannot be used: on a failed config
only ``config.schema`` and ``platform.version`` run, and no other file is read. Otherwise the
selection (``doctor.rules``, ``modules`` and ``--only``; a refusal exits 2, a note goes to
stderr), then ``hub.lock`` when a selected rule reads it, and the hub's files the selected
rules need (the lock's managed paths among them), read without following links (git runs only
when a rule reads the listing), and the release's base hooks block when a rule reads it (built
from the installed generator, never by a render). The findings go to stdout as lines and
totals, or as one JSON object with ``--json``; the exit is 1 when one is an error, else 0.
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
from agent_hub.core.doctor.lock_rules import lock_paths, lock_state
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import (
    Selection,
    UsageProblem,
    count_findings,
    run_rules,
    select_rules,
)
from agent_hub.core.doctor.snapshot import (
    ConfigFailure,
    DoctorSnapshot,
    HubFiles,
    LockState,
    hub_paths,
)
from agent_hub.core.hub_config.doctor_rules import RULE_IDS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.generator.built_json import base_hooks_block
from agent_hub.generator.doctor_tree import read_doctor_tree
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_root_entry

# The reads the hub listing serves: the listing itself, and the file sets that come from it.
LISTING_READS: Final = frozenset({Read.HUB_LISTING, Read.INSTRUCTION_FILES, Read.PLUGIN_FILES})
# A usage error, an unknown or unrunnable ``--only`` id, or a folder that is not a hub.
NOT_A_HUB_EXIT: Final = 2
NOT_A_HUB: Final = (
    "not a hub: no hub.json in this folder (hub doctor runs in the hub folder, never a parent)"
)
# At least one finding is an error.
FINDINGS_FAILED: Final = 1
# A failed config reads no file: only the config rules run, and they read hub.json alone.
_NO_FILES: Final = HubFiles(entries={}, listed=(), problem=None, paths_read=True)


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
    snapshot = DoctorSnapshot(
        config=config, running_version=running, hub=_NO_FILES, lock=None, base_hooks=None
    )
    if not isinstance(config, ConfigFailure):
        snapshot = _hub_snapshot(root, config=config, running=running, selection=selection)
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


def _hub_snapshot(
    root: str, *, config: HubConfig, running: str, selection: Selection
) -> DoctorSnapshot:
    """The lock, the files and the base hooks block the selected rules read.

    The files are the fixed paths, the lock's managed paths when a rule reads them, and the
    listing when one needs it or a file set that comes from it.
    """
    reads = {read for rule in selection.rules for read in rule.reads}
    lock = _lock_or_none(root) if Read.LOCK_PATHS in reads else None
    by_path = sorted({*hub_paths(config), *lock_paths(lock)})
    hub = read_doctor_tree(Path(root), by_path=by_path, listing=not LISTING_READS.isdisjoint(reads))
    base_hooks = base_hooks_block() if Read.BASE_HOOKS in reads else None
    return DoctorSnapshot(
        config=config, running_version=running, hub=hub, lock=lock, base_hooks=base_hooks
    )


def _lock_or_none(root: str) -> LockState | None:
    """``hub.lock`` as found, never through a link; ``None`` when it cannot be read.

    An unreadable lock is not an absent one: ``hub.lock`` is a fixed path, so the tree read
    fails on it too and the run reports that problem instead of "not adopted".
    """
    try:
        return lock_state(read_root_entry(Path(root), HUB_LOCK_PATH))
    except GeneratorError:
        return None
