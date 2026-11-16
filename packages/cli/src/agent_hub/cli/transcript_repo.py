"""The repo a backfilled transcript belongs to, found the way the hook sensor finds it (B1).

The sensor labels a hook with the ``hub.json`` repo whose checkout (or a worktree inside it)
holds the hook's cwd, the workspace being the folder that holds the main hub checkout. The live
tail gives a transcript's events that label, so ``hub collect --transcript`` must give the same
one, or the same ``(source, source_id)`` would arrive with two contents and conflict.
"""

import json
from pathlib import Path
from typing import Final

from agent_hub.cli.hub_config_reader import FILE_LABEL, read_hub_bytes

WORKTREES: Final = (".claude", "worktrees")
# The first lines name the session's cwd; a transcript that names none in these is read as none.
MAX_CWD_LINES: Final = 50


def first_cwd(text: str) -> str | None:
    """The ``cwd`` of the first of the first ``MAX_CWD_LINES`` lines that names one."""
    for line in text.split("\n")[:MAX_CWD_LINES]:
        try:
            record = json.loads(line)
        except ValueError, RecursionError:
            continue
        cwd = record.get("cwd") if isinstance(record, dict) else None
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def repo_of(cwd: str | None, hub: Path) -> str | None:
    """The ``hub.json`` repo of ``hub`` whose checkout holds ``cwd``; None for any other folder."""
    if cwd is None:
        return None
    main = _main_checkout(hub)
    names = _repo_dirs(main)
    try:
        where = Path(cwd).resolve()
        workspace = main.resolve().parent
    except OSError, ValueError, RuntimeError:
        return None
    for name in names:
        home = workspace / name
        if where == home or home in where.parents:
            return name
    return None


def _main_checkout(hub: Path) -> Path:
    """The main hub checkout of a hub worktree (``<hub>/.claude/worktrees/<t>``), else ``hub``."""
    parts = hub.parts
    if len(parts) >= 3 and parts[-3:-1] == WORKTREES and (hub.parents[2] / FILE_LABEL).is_file():
        return hub.parents[2]
    return hub


def _repo_dirs(hub: Path) -> tuple[str, ...]:
    content = read_hub_bytes(hub / FILE_LABEL)
    if not isinstance(content, bytes):
        return ()
    try:
        document = json.loads(content)
    except ValueError, RecursionError:
        return ()
    repos = document.get("repos") if isinstance(document, dict) else None
    if not isinstance(repos, list):
        return ()
    names = (repo.get("dir") for repo in repos if isinstance(repo, dict))
    return tuple(
        name
        for name in names
        if isinstance(name, str) and name and "/" not in name and name not in {".", ".."}
    )
