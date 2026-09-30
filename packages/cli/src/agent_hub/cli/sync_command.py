"""``hub sync``: bring a hub back to its render without overwriting what the project owns.

The pipeline of the AGH-14 spec, in the current folder (its real path, taken once). Each load
step that fails exits 1 before anything is read after it: ``hub.json`` (pin, schema, model), the
module refusal, then ``hub.lock``, read once without following a link (absent: the ``--adopt``
pointer; not a regular file or malformed: one line per problem, then the way out). Then the
render, a read of only the planned paths, and core's planner: a conflict exits 3 with one line per
path, a plan with nothing to do prints ``up to date``, and pending changes are listed as ``would``
lines with exit 4 (nothing is applied yet). Every error goes to stderr.
"""

from pathlib import Path
from typing import Annotated, Final, NoReturn

import typer

from agent_hub.cli.command_exits import fail, fail_generator, refuse_modules_or_exit, root_or_exit
from agent_hub.cli.generator import NOT_IMPLEMENTED, NOT_IMPLEMENTED_EXIT_CODE
from agent_hub.cli.hub_config_reader import load_hub_json_or_exit
from agent_hub.cli.init_report import shown_path, shown_text
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    ADOPT_POINTER,
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    LOCK_NOT_REGULAR,
    LOCK_WAY_OUT,
    HubLock,
    ManagedFileEntry,
    read_hub_lock,
)
from agent_hub.core.hub_files.plan_sync import (
    ContentConflict,
    SyncConflicts,
    SyncPlan,
    Verb,
    plan_sync,
)
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeSnapshot
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_planned_tree, read_root_entry
from agent_hub.generator.render_hub import render_hub

# A change the project made to a managed path: nothing is written (ADR 0009).
CONFLICT: Final = 3
# Changes are pending: nothing was written.
PENDING: Final = 4
UP_TO_DATE: Final = "up to date"
MISSING_HUB_JSON_HINT: Final = "run hub sync in the hub folder"
CONFLICT_WAY_OUT: Final = (
    "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
    " restore or delete the file, then re-run hub sync"
)
_CONTENT_DIFFERS: Final = "differs from its hub.lock entry and from its render"
_WOULD: Final = {
    Verb.CREATED: "would create",
    Verb.RESTORED: "would restore",
    Verb.UPDATED: "would update",
    Verb.DELETED: "would delete",
}


def sync(
    *,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Plan only: write nothing; exit 4 when changes are pending, 3 on a conflict.",
        ),
    ] = False,
    adopt: Annotated[
        bool, typer.Option("--adopt", help="Join a hand-made hub (not implemented yet).")
    ] = False,
) -> None:
    """Reapply the hub templates without overwriting what the project customized."""
    if adopt:
        typer.echo(NOT_IMPLEMENTED, err=True)
        raise typer.Exit(NOT_IMPLEMENTED_EXIT_CODE)
    root = Path(root_or_exit(None))
    config = load_hub_json_or_exit(root / HUB_JSON_PATH, missing_hint=MISSING_HUB_JSON_HINT).config
    refuse_modules_or_exit(config)
    lock, lock_content = _lock_or_exit(root)
    planned = _plan_or_exit(root, config=config, lock=lock, lock_content=lock_content)
    if isinstance(planned, SyncConflicts):
        _fail_conflicts(planned)
    # Nothing is applied yet, with or without --check: a pending plan is reported and exits 4.
    if not planned.pending:
        typer.echo(UP_TO_DATE)
        return
    for line in _pending_lines(planned):
        typer.echo(line)
    raise typer.Exit(PENDING)


def _lock_line(message: str) -> str:
    return f"{HUB_LOCK_PATH}: {message}"


def _lock_or_exit(root: Path) -> tuple[HubLock, bytes]:
    """The lock and its exact bytes, read once and never through a link (spec Q-6, Q-12)."""
    try:
        entry = read_root_entry(root, HUB_LOCK_PATH)
    except GeneratorError as error:
        fail_generator(error)
    if entry is None:
        fail(ADOPT_POINTER)
    # A regular file is always returned with its content; anything else was never opened.
    if not isinstance(entry, FileEntry) or entry.content is None:
        fail(_lock_line(LOCK_NOT_REGULAR), _lock_line(LOCK_WAY_OUT))
    read = read_hub_lock(entry.content)
    if not isinstance(read, HubLock):
        problems = (_lock_line(f"{problem.path}: {problem.message}") for problem in read)
        fail(*problems, _lock_line(LOCK_WAY_OUT))
    return read, entry.content


def _planned_paths(rendered: RenderedHub, lock: HubLock) -> tuple[list[str], set[str]]:
    """The paths to look at and those whose content is compared.

    ``hub.json`` is the project's and ``hub.lock`` was read already: neither is looked at again.
    """
    in_render = {file.path for file in rendered.files} | {link.path for link in rendered.links}
    paths = sorted((in_render | set(lock.files)) - {HUB_JSON_PATH})
    wanted = {file.path for file in rendered.files if file.ownership is Ownership.MANAGED}
    wanted |= {path for path, entry in lock.files.items() if isinstance(entry, ManagedFileEntry)}
    return paths, wanted - {HUB_JSON_PATH}


def _plan_or_exit(
    root: Path, *, config: HubConfig, lock: HubLock, lock_content: bytes
) -> SyncPlan | SyncConflicts:
    try:
        rendered = render_hub(config)
        paths, wanted = _planned_paths(rendered, lock)
        tree: TreeSnapshot = read_planned_tree(root, paths=paths, wanted=wanted)
    except GeneratorError as error:
        fail_generator(error)
    return plan_sync(
        rendered=rendered, config=config, lock=lock, lock_content=lock_content, tree=tree
    )


def _fail_conflicts(conflicts: SyncConflicts) -> NoReturn:
    # One line per conflicted path, then the way out; nothing on stdout.
    for problem in conflicts.problems:
        cause = _CONTENT_DIFFERS if isinstance(problem, ContentConflict) else problem.message
        typer.echo(shown_text(f"{shown_path(problem.path)}: {cause}"), err=True)
    typer.echo(CONFLICT_WAY_OUT, err=True)
    raise typer.Exit(CONFLICT)


def _pending_lines(plan: SyncPlan) -> list[str]:
    lines = [f"{_WOULD[change.verb]} {shown_path(change.path)}" for change in plan.changes]
    if plan.leftovers:
        lines.append(f"would remove {len(plan.leftovers)} leftover temporary files")
    if plan.lock_written:
        lines.append(f"would update {HUB_LOCK_PATH}")
    return lines
