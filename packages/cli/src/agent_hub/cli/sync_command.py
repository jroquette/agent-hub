"""``hub sync``: bring a hub back to its render without overwriting what the project owns.

The pipeline of the AGH-14 spec, in the current folder (its real path, taken once). Each load
step that fails exits 1 before anything is read after it: ``hub.json`` (pin, schema, model), the
module refusal, then ``hub.lock``, read once without following a link (absent: the ``--adopt``
pointer; not a regular file or malformed: one line per problem, then the way out). Then the
render, a read of only the planned paths (plus a listing of the project's agent and skill folders
and a look at the link path of each name found there), the project's extension inputs from that
one read (a bad ``*.project.json`` sibling or an entry name the lock cannot hold exits 1), the
render with them, and core's planner. A conflict exits 3 with its report
on stderr and nothing written. With nothing pending, ``up to date`` and no write at all (the
adapter is not called). ``--check`` prints the ``would`` lines and exits 4. Otherwise the plan is
applied with one open of the root (leftovers, deletes, folders, files, links, ``hub.lock`` last)
and its lines are printed; an I/O error exits 1 naming the path. Every error goes to stderr.
"""

from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import (
    extension_inputs_or_exit,
    fail,
    fail_generator,
    not_implemented,
    refuse_modules_or_exit,
    root_or_exit,
)
from agent_hub.cli.hub_config_reader import load_hub_json_or_exit
from agent_hub.cli.sync_report import change_lines, conflict_lines
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import LINKED_TYPES
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
from agent_hub.core.hub_files.plan_sync import SyncConflicts, SyncPlan, plan_sync
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeSnapshot
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.file_adapter import apply_sync
from agent_hub.generator.hub_tree import LinkFolder, read_planned_tree, read_root_entry
from agent_hub.generator.render_hub import project_json_siblings, render_hub

# A change the project made to a managed path: nothing is written (ADR 0009).
CONFLICT: Final = 3
# Changes are pending: nothing was written.
PENDING: Final = 4
MISSING_HUB_JSON_HINT: Final = "run hub sync in the hub folder"


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
        not_implemented()
    root = Path(root_or_exit(None))
    config = load_hub_json_or_exit(root / HUB_JSON_PATH, missing_hint=MISSING_HUB_JSON_HINT).config
    refuse_modules_or_exit(config)
    lock, lock_content = _lock_or_exit(root)
    planned = _plan_or_exit(root, config=config, lock=lock, lock_content=lock_content)
    if isinstance(planned, SyncConflicts):
        # Nothing on stdout: the report, then exit 3.
        for line in conflict_lines(planned):
            typer.echo(line, err=True)
        raise typer.Exit(CONFLICT)
    # An empty plan never reaches the adapter: nothing is opened, made or replaced (E4).
    if planned.pending and not check:
        _apply_or_exit(root, planned)
    for line in change_lines(planned, check=check):
        typer.echo(line)
    if planned.pending and check:
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


def _links_in(project: str) -> dict[str, LinkFolder]:
    """The project's agent and skill folders, each with the folder that holds their links."""
    return {
        f"plugin/{project}/{folder}": LinkFolder(f".claude/{folder}", linked=linked)
        for folder, linked in LINKED_TYPES.items()
    }


def _plan_or_exit(
    root: Path, *, config: HubConfig, lock: HubLock, lock_content: bytes
) -> SyncPlan | SyncConflicts:
    """One tree read for both renders (spec Q-20).

    The paths come from the render without extension inputs: the inputs only change the bytes of
    a merged ``X.json`` and add a ``.claude`` link per project entry, whose path the read looks at
    for each name it lists (so a project's own file there is a conflict, never replaced).
    """
    project = config.project.name
    try:
        siblings = project_json_siblings(config)
        paths, wanted = _planned_paths(render_hub(config), lock)
        links_in = _links_in(project)
        tree: TreeSnapshot = read_planned_tree(
            root, paths=paths, wanted={*wanted, *siblings}, listed=links_in, links_in=links_in
        )
    except GeneratorError as error:
        fail_generator(error)
    extensions = extension_inputs_or_exit(tree, project=project, siblings=siblings)
    try:
        # A sibling that cannot be merged is a ``MergeError``: one line, exit 1.
        rendered = render_hub(config, extensions)
    except GeneratorError as error:
        fail_generator(error)
    return plan_sync(
        rendered=rendered,
        config=config,
        lock=lock,
        lock_content=lock_content,
        tree=tree,
        extensions=extensions,
    )


def _apply_or_exit(root: Path, plan: SyncPlan) -> None:
    try:
        apply_sync(
            root,
            leftovers=plan.leftovers,
            deletes=plan.deletes,
            folders=plan.folders,
            writes=plan.writes,
        )
    except GeneratorError as error:
        fail_generator(error)
