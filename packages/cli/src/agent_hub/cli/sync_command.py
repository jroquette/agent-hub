"""``hub sync``: bring a hub back to its render without overwriting what the project owns.

The pipeline of the AGH-14 spec, in the current folder (its real path, taken once). Each load step
that fails exits 1 before anything is read after it: ``hub.json`` (pin, schema, model; any module
set is accepted), then ``hub.lock``, read once without following a link (absent: the ``--adopt``
pointer; not a regular file or malformed: one line per problem, then the way out). Then the steps
of ``sync_steps``: the tree read, the extension inputs and the render with them, and core's
planner. A conflict exits 3 with its report on stderr and nothing written. With nothing pending,
``up to date`` and no write at all (the adapter is not called). ``--check`` prints the ``would``
lines and exits 4. Otherwise the plan is applied and its lines are printed. Every error goes to
stderr.
"""

from pathlib import Path
from typing import Annotated

import typer

from agent_hub.cli.command_exits import fail, not_implemented, root_or_exit
from agent_hub.cli.hub_config_reader import load_hub_json_or_exit
from agent_hub.cli.sync_report import change_lines, conflict_lines
from agent_hub.cli.sync_steps import (
    CONFLICT,
    MISSING_HUB_JSON_HINT,
    PENDING,
    apply_or_exit,
    lock_or_exit,
    rendering_or_exit,
)
from agent_hub.core.hub_files.hub_lock import ADOPT_POINTER, HUB_JSON_PATH, LOCK_WAY_OUT
from agent_hub.core.hub_files.plan_sync import SyncConflicts, plan_sync


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
    _sync(check=check)


def _sync(*, check: bool) -> None:
    root = Path(root_or_exit(None))
    config = load_hub_json_or_exit(root / HUB_JSON_PATH, missing_hint=MISSING_HUB_JSON_HINT).config
    read = lock_or_exit(root, way_out=LOCK_WAY_OUT)
    if read is None:
        fail(ADOPT_POINTER)
    lock, lock_content = read
    tree, extensions, rendered = rendering_or_exit(root, config=config, lock_files=lock.files)
    planned = plan_sync(
        rendered=rendered,
        config=config,
        lock=lock,
        lock_content=lock_content,
        tree=tree,
        extensions=extensions,
    )
    if isinstance(planned, SyncConflicts):
        # Nothing on stdout: the report, then exit 3.
        for line in conflict_lines(planned):
            typer.echo(line, err=True)
        raise typer.Exit(CONFLICT)
    # An empty plan never reaches the adapter: nothing is opened, made or replaced (E4).
    if planned.pending and not check:
        apply_or_exit(root, planned)
    for line in change_lines(planned, check=check):
        typer.echo(line)
    if planned.pending and check:
        raise typer.Exit(PENDING)
