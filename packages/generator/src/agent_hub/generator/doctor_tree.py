"""Read a tree for ``hub doctor``: its file listing and the files rules read (spec D3, E7-E9).

A tree whose root holds a ``.git`` entry and that git names as its work tree top is listed by
``git ls-files -z --cached --others --exclude-standard``, sorted, without the ``dir/`` entries of
nested repositories; the listed paths are then read by path (``hub_tree.read_planned_tree``). Git
runs as an absolute executable with ``core.fsmonitor`` off (so no project hook runs), without the
caller's location variables, with ``GIT_OPTIONAL_LOCKS=0`` (so it never refreshes the index), in a
session of its own that is killed on the way out, and with a timeout. A missing, failing or
hanging git is the tree's ``problem``; nothing falls back to a walk.

Any other folder, a hub inside a larger repository included, is walked
(``hub_tree.read_every_file``): every regular file is read, links are recorded and never
followed, FIFOs are never opened, and nothing under ``.git`` or a nested repository is listed.
The fixed paths the rules read by name are always looked at by path, listed or not. Nothing here
writes, and a folder that cannot be read gives a ``problem`` (one line, escaped), never a raise.
"""

import contextlib
import os
import shutil
import signal
import subprocess
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.core.doctor.snapshot import HubFiles
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.hub_tree import read_every_file, read_planned_tree

GIT_TIMEOUT_SECONDS = 10.0
# Each one makes git read another repository, index or work tree than the tree's own.
SCRUBBED_VARIABLES: Final = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"}
)

_LISTING_FAILED: Final = "could not list the files: "
_GIT_ENTRY: Final = ".git"
_LIST_ARGUMENTS: Final = ("ls-files", "-z", "--cached", "--others", "--exclude-standard")


class _GitError(Exception):
    """Why git could not list the tree, as one line."""


@dataclass(frozen=True, kw_only=True, slots=True)
class _Listing:
    paths: tuple[str, ...]
    # What the listing already read (the walk reads as it lists; git only names paths).
    entries: Mapping[str, TreeEntry]


_NO_LISTING: Final = _Listing(paths=(), entries={})


def read_doctor_tree(root: Path, *, by_path: Collection[str], listing: bool) -> HubFiles:
    """The files of the tree at ``root`` (already a real path) that the selected rules need.

    ``by_path`` are looked at by path whatever the listing says; ``listing`` asks for the
    tree's file list. Raises ``ValueError`` for a ``by_path`` entry that is not plain and
    relative; any failure to list or read the tree is the returned ``problem``.
    """
    problem: str | None = None
    try:
        found = _list_tree(root) if listing else _NO_LISTING
    except (GeneratorError, _GitError) as error:
        found, problem = _NO_LISTING, _LISTING_FAILED + one_line(str(error))
    unread = sorted({*found.paths, *by_path} - found.entries.keys())
    try:
        looked = read_planned_tree(root, paths=unread, wanted=unread).entries if unread else {}
    except GeneratorError as error:
        return HubFiles(
            entries=found.entries,
            listed=(),
            problem=problem or _LISTING_FAILED + one_line(str(error)),
        )
    entries = {**found.entries, **looked}
    listed = tuple(
        path for path in found.paths if isinstance(entries.get(path), FileEntry | LinkEntry)
    )
    return HubFiles(
        entries={path: entries[path] for path in sorted(entries)}, listed=listed, problem=problem
    )


def _list_tree(root: Path) -> _Listing:
    if not _has_git_entry(root):
        walked = read_every_file(root).entries
        return _Listing(paths=tuple(walked), entries=walked)
    found = shutil.which("git")
    if found is None:
        raise _GitError("git not found")
    # PATH may hold a relative folder, found from the process cwd; git runs in the root.
    executable = os.path.abspath(found)
    top = os.fsdecode(_git(executable, ("rev-parse", "--show-toplevel"), cwd=root))
    top = top.removesuffix("\n")
    if os.path.realpath(top) != os.path.realpath(root):
        raise _GitError(f"git puts this folder in the work tree {top}")
    printed = _git(executable, _LIST_ARGUMENTS, cwd=root).split(b"\0")
    # ``dir/`` is an untracked nested repository or worktree: never listed or walked.
    paths = {os.fsdecode(path) for path in printed if path and not path.endswith(b"/")}
    return _Listing(paths=tuple(sorted(paths)), entries={})


def _has_git_entry(root: Path) -> bool:
    try:
        os.lstat(root / _GIT_ENTRY)
    except FileNotFoundError:
        return False
    except OSError as error:
        msg = f"{_GIT_ENTRY}: {error.strerror or error}"
        raise GeneratorError(msg) from error
    return True


def _git(executable: str, arguments: Collection[str], *, cwd: Path) -> bytes:
    """Git's stdout; raises ``_GitError`` when it cannot start, fails or runs too long."""
    timeout = GIT_TIMEOUT_SECONDS
    try:
        with subprocess.Popen(  # noqa: S603 - absolute git, fixed argv, no shell
            [executable, "-c", "core.fsmonitor=false", *arguments],
            cwd=cwd,
            env=_git_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as child:
            try:
                output, errors = child.communicate(timeout=timeout)
            finally:
                # Whatever happened, no child git started is left running or holding the pipes.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(child.pid, signal.SIGKILL)
    except subprocess.TimeoutExpired as error:
        raise _GitError(f"git timed out after {timeout:g} s") from error
    except OSError as error:
        raise _GitError(f"git could not run: {error.strerror or error}") from error
    if child.returncode != 0:
        first_line = next(iter(errors.decode("utf-8", "replace").splitlines()), "")
        raise _GitError(f"git exited with {child.returncode}: {first_line}".removesuffix(": "))
    return output


def _git_environment() -> dict[str, str]:
    kept = {name: value for name, value in os.environ.items() if name not in SCRUBBED_VARIABLES}
    return {**kept, "GIT_OPTIONAL_LOCKS": "0"}
