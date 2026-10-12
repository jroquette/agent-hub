"""``hub doctor``: check a hub against the rules of this release, read-only.

The pipeline of the AGH-11 spec, in the current folder (its real path, taken once, no walk-up):
an ``--only`` id that is no rule at all is a usage error (exit 2) before anything is read; no
``hub.json`` entry in the folder (a dangling link counts as one) exits 2 saying it is not a hub.
Then ``hub.json`` is read once into its config, or why it cannot be used, and the developer's
``hub.local.json`` from the hub's main checkout (``local_home``): on a failed config only
``config.schema`` and ``platform.version`` run, and no other hub file is read. Otherwise the
selection (``doctor.rules``, ``modules`` and ``--only``; a refusal exits 2, a note goes to
stderr), then ``hub.lock`` when a selected rule reads it, and the hub's files the selected
rules need (the lock's managed paths among them), read without following links (git runs only
when a rule reads the listing), the release's base hooks block when a rule reads it (built
from the installed generator, never by a render), each repo checkout at ``../<dir>`` when a
rule reads the repos (its real path, taken once; inside it nothing is followed), and the
developer's branch prefix when a rule reads it and the local file is valid (``git config`` runs
in the main checkout only when no file sets the prefix), and, from a Claude Code session only
(``CLAUDECODE=1``), each repo checkout's ``git ls-remote origin`` when a rule reads the remotes
(AGH-134: run inside the session's sandbox, it shows whether a sandboxed fetch can work). The
findings go to stdout as lines and totals, or as one JSON object with ``--json``; the exit is 1
when one is an error, else 0. ``check_hub`` is the same check on a given root, for ``hub setup``.
"""

import os
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final, NamedTuple

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.command_exits import root_or_exit
from agent_hub.cli.doctor_report import report_json, report_lines
from agent_hub.cli.effective_config import git_identity_reader
from agent_hub.cli.errors import ChildTimedOutError
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
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import (
    UsageProblem,
    count_findings,
    run_rules,
    select_rules,
)
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, HubFiles, RemoteProbe
from agent_hub.core.hub_config.doctor_rules import RULE_IDS
from agent_hub.core.hub_config.effective_identity import (
    IdentityValues,
    Sourced,
    resolve_branch_prefix,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.generator.doctor_snapshot import (
    BranchPrefixReader,
    RemoteProber,
    build_doctor_snapshot,
)

# A usage error, an unknown or unrunnable ``--only`` id, or a folder that is not a hub.
NOT_A_HUB_EXIT: Final = 2
NOT_A_HUB: Final = (
    "not a hub: no hub.json in this folder (hub doctor runs in the hub folder, never a parent)"
)
# At least one finding is an error.
FINDINGS_FAILED: Final = 1
# A failed config reads no file: only the config rules run, and they read hub.json alone.
_NO_FILES: Final = HubFiles(entries={}, listed=(), problem=None, paths_read=True)
# Claude Code sets it in its Bash tool's environment; the probe is about that session's sandbox.
CLAUDE_CODE_VARIABLE: Final = "CLAUDECODE"
PROBE_TIMEOUT: Final = 20


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
    run = check_hub(root, only=wanted)
    if isinstance(run, UsageProblem):
        context.fail(run.message)
    for note in run.notes:
        typer.echo(note, err=True)
    if as_json:
        typer.echo(report_json(run.findings), nl=False)
    else:
        for line in report_lines(run.findings):
            typer.echo(line)
    if count_findings(run.findings).has_errors:
        raise typer.Exit(FINDINGS_FAILED)


class DoctorRun(NamedTuple):
    """The findings of one check, and the selection's notes (for stderr)."""

    findings: tuple[Finding, ...]
    notes: tuple[str, ...]


def check_hub(root: str, *, only: Sequence[str] = ()) -> DoctorRun | UsageProblem:
    """The check of ``hub doctor`` on the hub at ``root``: same reads, same order, no output.

    ``root`` must be the hub's real absolute path, taken once (as ``root_or_exit`` gives it):
    the repo checkouts are found at ``root/../<dir>`` and the findings name paths relative to
    it. ``only`` holds known rule ids; a selection the config refuses is the ``UsageProblem``.
    """
    running = version(DISTRIBUTION)
    config = config_state(read_hub_bytes(Path(root, FILE_LABEL)), running_version=running)
    # No token reaches git, which only looks for the main checkout.
    home = local_home(Path(root), environ=without(os.environ, SESSION_HIDDEN))
    local = read_local_json(home / LOCAL_FILE)
    selection = select_rules(REGISTRY, config=config, only=only)
    if isinstance(selection, UsageProblem):
        return selection
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
        snapshot = build_doctor_snapshot(
            root,
            config=config,
            running=running,
            selection=selection,
            local=local,
            branch_prefix=_prefix_reader(config, local=local, home=home),
            remote_probes=_remote_prober(root, config),
        )
    return DoctorRun(findings=run_rules(selection, snapshot), notes=selection.notes)


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


def _prefix_reader(
    config: HubConfig, *, local: LocalConfig | tuple[ConfigProblem, ...], home: Path
) -> BranchPrefixReader | None:
    """The developer's effective branch prefix, read only when the snapshot asks for it.

    Git runs in ``home`` only when no file sets it. ``hub.json``'s own values, never the merged
    ones, so each value keeps its file as source. None when the local file is invalid.
    """
    if not isinstance(local, LocalConfig):
        return None
    values = IdentityValues.of(local.project)

    def read() -> Sourced | None:
        read_git, _ = git_identity_reader(home)
        return resolve_branch_prefix(
            local=values, hub=IdentityValues.of(config.project), read_git=read_git
        )

    return read


def _remote_prober(root: str, config: HubConfig) -> RemoteProber | None:
    """Each repo checkout's ``git ls-remote origin``, only from a Claude Code session.

    A ``../<dir>`` that is no git checkout is left out (``repos.agents`` names it). Git gets no
    terminal prompt and ``PROBE_TIMEOUT`` seconds; a git that cannot run is a probe problem.
    """
    if os.environ.get(CLAUDE_CODE_VARIABLE) != "1":
        return None

    def probe() -> tuple[RemoteProbe, ...]:
        env = git_env(os.environ, optional_locks=False) | {"GIT_TERMINAL_PROMPT": "0"}
        found = []
        for repo in config.repos:
            checkout = os.path.join(root, os.pardir, repo.dir)
            if not os.path.lexists(os.path.join(checkout, ".git")):
                continue
            found.append(RemoteProbe(dir=repo.dir, problem=_ls_remote(checkout, env=env)))
        return tuple(found)

    return probe


def _ls_remote(checkout: str, *, env: dict[str, str]) -> str | None:
    """Why ``git ls-remote origin HEAD`` failed in ``checkout``, or ``None`` when it answered."""
    try:
        result = run_child(
            ["git", "ls-remote", "-q", "origin", "HEAD"],
            cwd=checkout,
            env=env,
            timeout=PROBE_TIMEOUT,
        )
    except ChildTimedOutError:
        return f"timed out after {PROBE_TIMEOUT} s"
    except OSError as error:
        return f"git could not run: {error.strerror or error}"
    if result.returncode == 0:
        return None
    lines = [line.strip() for line in result.stderr.decode(errors="replace").splitlines()]
    return next((line for line in lines if line), f"git exited {result.returncode}")
