"""``hub sync --adopt [--accept PATH]… [--check]``: join a hand-made hub to ``hub.lock`` (AGH-16).

The load order is plain sync's, in the current folder (its real path, taken once): ``hub.json``
(pin, schema, model), then ``hub.lock``, which may be absent; a lock that is not a regular file or
is malformed exits 1 with its lines and adopt's way out (spec Q-5). Then the steps of
``sync_steps`` (one tree read, the extension inputs, the render with them) and core's
``plan_adopt``. A refused ``--accept`` names each refused path on stderr and exits 2 with nothing
written. Otherwise the settled paths are applied, ``hub.lock`` last, even when something is listed
(Q-4), unless ``--check``. stdout gets the change lines (``would`` with ``--check``, Q-6, Q-7):
``up to date`` only when nothing is pending and nothing listed; nothing when only listings remain.
stderr gets each listed path, each conflict and one way out. Exit 3 while anything is listed or
conflicting, else 4 with ``--check`` and writes pending, else 0.
"""

from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.adopt_report import listing_lines, refusal_lines
from agent_hub.cli.command_exits import root_or_exit
from agent_hub.cli.hub_config_reader import load_hub_json_or_exit
from agent_hub.cli.sync_report import change_lines
from agent_hub.cli.sync_steps import (
    CONFLICT,
    MISSING_HUB_JSON_HINT,
    PENDING,
    apply_or_exit,
    lock_or_exit,
    rendering_or_exit,
)
from agent_hub.core.hub_files.hub_lock import ADOPT_LOCK_WAY_OUT, HUB_JSON_PATH
from agent_hub.core.hub_files.plan_adopt import AdoptPlan, AdoptRefusal, plan_adopt

# An ``--accept`` path this run does not list: a usage-level refusal, nothing written (Q-3).
REFUSED: Final = 2


def run_adopt(*, check: bool, accept: tuple[str, ...]) -> None:
    """Adopt the hub in the current folder, taking the render of each ``accept`` path."""
    root = Path(root_or_exit(None))
    planned = _plan_or_exit(root, accept=frozenset(accept))
    # Q-4: the settled paths are applied even when something is listed; an empty plan never
    # reaches the adapter.
    if planned.pending and not check:
        apply_or_exit(root, planned)
    # ``up to date`` would hide a listing: with nothing to write, only the listing is printed.
    if planned.pending or planned.settled:
        for line in change_lines(planned, check=check):
            typer.echo(line)
    for line in listing_lines(planned):
        typer.echo(line, err=True)
    if not planned.settled:
        raise typer.Exit(CONFLICT)
    if planned.pending and check:
        raise typer.Exit(PENDING)


def _plan_or_exit(root: Path, *, accept: frozenset[str]) -> AdoptPlan:
    """Load, read and render as plain sync does, the lock optional; a refused accept exits 2."""
    config = load_hub_json_or_exit(root / HUB_JSON_PATH, missing_hint=MISSING_HUB_JSON_HINT).config
    read = lock_or_exit(root, way_out=ADOPT_LOCK_WAY_OUT)
    lock, lock_content = read if read is not None else (None, None)
    tree, extensions, rendered = rendering_or_exit(
        root, config=config, lock_files={} if lock is None else lock.files
    )
    planned = plan_adopt(
        rendered=rendered,
        config=config,
        lock=lock,
        lock_content=lock_content,
        tree=tree,
        extensions=extensions,
        accept=accept,
    )
    if isinstance(planned, AdoptRefusal):
        for line in refusal_lines(planned):
            typer.echo(line, err=True)
        raise typer.Exit(REFUSED)
    return planned
