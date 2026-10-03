"""The hub root of ``hub worktree``, ``hub brief`` and ``hub agent``, and its main checkout.

The ``./hub`` shim keeps the caller's cwd and exports ``AGENT_HUB_ROOT`` (spec Q-2): set and not
empty, it names the hub; otherwise the cwd does. Either way the root must hold ``hub.json``.
The developer's ``hub.local.json`` and git identity live in the main checkout (``local_home``).
"""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import typer

from agent_hub.cli.child_process import git_env, run_child
from agent_hub.cli.command_exits import root_or_exit
from agent_hub.cli.hub_config_reader import FILE_LABEL
from agent_hub.cli.init_report import shown_path

HUB_ROOT_VARIABLE: Final = "AGENT_HUB_ROOT"
# A root without hub.json is a usage error, as in hub doctor.
NOT_A_HUB_EXIT: Final = 2
_GIT_FOLDER = ".git"
# One line each, in this order.
_ASKED = ("--show-toplevel", "--git-common-dir")


def hub_root_or_exit(environ: Mapping[str, str], *, command: str) -> Path:
    """The real path of the hub root; exit 2 with one stderr line when it holds no ``hub.json``.

    Only an absent entry means "not a hub": any other problem looking at it is left to the
    hub.json reader, which names it.
    """
    given = environ.get(HUB_ROOT_VARIABLE) or None
    root = root_or_exit(None if given is None else Path(given))
    try:
        os.lstat(os.path.join(root, FILE_LABEL))
    except FileNotFoundError:
        typer.echo(
            f"{shown_path(root)}: not a hub: no {FILE_LABEL} in this folder"
            f" (hub {command} runs in the hub folder or through ./hub)",
            err=True,
        )
        raise typer.Exit(NOT_A_HUB_EXIT) from None
    except OSError:
        pass
    return Path(root)


def main_checkout(root: Path, *, git: str, environ: Mapping[str, str]) -> Path:
    """The hub's main checkout: ``root`` itself, unless ``root`` is a worktree of the hub repo.

    ``root`` is used as it is when it is not the top of a git work tree (a hub that is not a
    repo, or a folder inside another repo) or when its repo keeps its git data elsewhere than a
    ``.git`` folder of a checkout. Raises ``OSError`` when ``git`` cannot start.
    """
    result = run_child(
        [git, "rev-parse", "--path-format=absolute", *_ASKED],
        cwd=root,
        env=git_env(environ, optional_locks=False),
        timeout=None,
        own_session=False,
    )
    lines = result.stdout.rstrip(b"\n").split(b"\n")
    if result.returncode != 0 or len(lines) != len(_ASKED):
        return root
    top, common = (Path(os.fsdecode(line)) for line in lines)
    if common.name != _GIT_FOLDER or not _is_same_folder(top, root):
        return root
    return Path(os.path.realpath(common.parent))


def local_home(root: Path, *, environ: Mapping[str, str]) -> Path:
    """Where the developer's ``hub.local.json`` and git identity are read: the main checkout.

    Git runs only when ``root`` is a worktree (its ``.git`` a file); without git, or when git
    cannot start, ``root`` is used.
    """
    if not os.path.isfile(os.path.join(root, _GIT_FOLDER)):
        return root
    found = shutil.which("git", path=environ.get("PATH"))
    if found is None:
        return root
    try:
        return main_checkout(root, git=os.path.abspath(found), environ=environ)
    except OSError:
        return root


def _is_same_folder(top: Path, root: Path) -> bool:
    # The file identity, not the spelling: a case-insensitive file system may spell it otherwise.
    try:
        return os.path.samefile(top, root)
    except OSError:
        return False
