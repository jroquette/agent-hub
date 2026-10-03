"""``hub doctor``: check a hub against the rules of this release, read-only.

The pipeline of the AGH-11 spec, in the current folder (its real path, taken once, no walk-up):
an ``--only`` id that is no rule at all is a usage error (exit 2) before anything is read; no
``hub.json`` entry in the folder (a dangling link counts as one) exits 2 saying it is not a hub.
Then ``hub.json`` is read once into its config, or why it cannot be used, and the developer's
``hub.local.json`` from the hub's main checkout (``local_home``): on a failed config only
``config.schema`` and ``platform.version`` run, and no other file is read. Otherwise the
selection (``doctor.rules``, ``modules`` and ``--only``; a refusal exits 2, a note goes to
stderr), then ``hub.lock`` when a selected rule reads it, and the hub's files the selected
rules need (the lock's managed paths among them), read without following links (git runs only
when a rule reads the listing), the release's base hooks block when a rule reads it (built
from the installed generator, never by a render), each repo checkout at ``../<dir>`` when a
rule reads the repos (its real path, taken once; inside it nothing is followed), and the
developer's branch prefix when a rule reads it and the local file is valid (``git config`` runs
in the main checkout only when no file sets the prefix). The findings
go to stdout as lines and totals, or as one JSON object with ``--json``; the exit is 1 when one
is an error, else 0.
"""

import os
import stat
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import root_or_exit
from agent_hub.cli.doctor_report import report_json, report_lines
from agent_hub.cli.effective_config import git_identity_reader
from agent_hub.cli.hub_config_reader import (
    DISTRIBUTION,
    FILE_LABEL,
    read_hub_bytes,
    read_local_json,
)
from agent_hub.cli.hub_root import local_home
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.doctor.config_rules import config_state
from agent_hub.core.doctor.finding import LISTING_READS, Read
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
    RepoFiles,
    hub_paths,
)
from agent_hub.core.hub_config.doctor_rules import RULE_IDS
from agent_hub.core.hub_config.effective_identity import (
    IdentityValues,
    Sourced,
    resolve_branch_prefix,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.generator.built_json import base_hooks_block
from agent_hub.generator.doctor_tree import read_checkout, read_doctor_tree
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_root_entry

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
    # No token reaches git, which only looks for the main checkout.
    home = local_home(Path(root), environ=without(os.environ, SESSION_HIDDEN))
    local = read_local_json(home / LOCAL_FILE)
    selection = select_rules(REGISTRY, config=config, only=wanted)
    if isinstance(selection, UsageProblem):
        context.fail(selection.message)
    for note in selection.notes:
        typer.echo(note, err=True)
    snapshot = DoctorSnapshot(
        config=config,
        running_version=running,
        hub=_NO_FILES,
        lock=None,
        base_hooks=None,
        repos=(),
        local=local,
    )
    if not isinstance(config, ConfigFailure):
        snapshot = _hub_snapshot(
            root, config=config, running=running, selection=selection, local=local, home=home
        )
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
    root: str,
    *,
    config: HubConfig,
    running: str,
    selection: Selection,
    local: LocalConfig | tuple[ConfigProblem, ...],
    home: Path,
) -> DoctorSnapshot:
    """The lock, the files, the base hooks block, the repo checkouts and the developer's branch
    prefix the selected rules read.

    The files are the fixed paths, the lock's managed paths when a rule reads them, and the
    listing when one needs it or a file set that comes from it.
    """
    reads = {read for rule in selection.rules for read in rule.reads}
    lock = _lock_or_none(root) if Read.LOCK_PATHS in reads else None
    by_path = sorted({*hub_paths(config), *lock_paths(lock)})
    hub = read_doctor_tree(Path(root), by_path=by_path, listing=not LISTING_READS.isdisjoint(reads))
    base_hooks = base_hooks_block() if Read.BASE_HOOKS in reads else None
    repos = _repo_checkouts(root, config) if Read.REPOS in reads else ()
    prefix = None
    if Read.DEVELOPER_IDENTITY in reads and isinstance(local, LocalConfig):
        prefix = _branch_prefix(config, local=local, home=home)
    return DoctorSnapshot(
        config=config,
        running_version=running,
        hub=hub,
        lock=lock,
        base_hooks=base_hooks,
        repos=repos,
        local=local,
        branch_prefix=prefix,
    )


def _branch_prefix(config: HubConfig, *, local: LocalConfig, home: Path) -> Sourced | None:
    """The developer's effective branch prefix; git runs in ``home`` only when no file sets it.

    ``hub.json``'s own values, never the merged ones, so each value keeps its file as source.
    """
    read_git, _ = git_identity_reader(home)
    return resolve_branch_prefix(
        local=IdentityValues.of(local.project),
        hub=IdentityValues.of(config.project),
        read_git=read_git,
    )


def _repo_checkouts(root: str, config: HubConfig) -> tuple[RepoFiles, ...]:
    """Each ``repos[].dir`` and the listed files of its checkout at ``../<dir>`` (spec D3, Q-9).

    ``../<dir>`` is taken as its real path once (plan E18), so a link to a folder is followed
    there only; absent or not a folder, the repo has no files. A checkout that cannot be listed
    carries the problem; one file that cannot be read does not (plan E36).
    """
    checkouts = (
        (repo.dir, os.path.realpath(os.path.join(root, os.pardir, repo.dir)))
        for repo in config.repos
    )
    return tuple(
        RepoFiles(dir=name, files=read_checkout(Path(real)) if _is_folder(real) else None)
        for name, real in checkouts
    )


def _is_folder(path: str) -> bool:
    """Whether ``path`` is a folder; one that cannot be looked at is left to the tree read."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError, NotADirectoryError:
        return False
    except OSError:
        return True


def _lock_or_none(root: str) -> LockState | None:
    """``hub.lock`` as found, never through a link; ``None`` when it cannot be read.

    An unreadable lock is not an absent one: ``hub.lock`` is a fixed path, so the tree read
    fails on it too and the run reports that problem instead of "not adopted".
    """
    try:
        return lock_state(read_root_entry(Path(root), HUB_LOCK_PATH))
    except GeneratorError:
        return None
