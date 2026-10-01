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

A repo checkout (``read_checkout``) is listed the same way, but only a listing that cannot be
made is its ``problem`` (plan E36): a listed file that cannot be read stays listed with no
content, so the repo rules skip that file, never the whole checkout.
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
from agent_hub.generator.hub_tree import list_every_file, read_every_file, read_planned_tree

GIT_TIMEOUT_SECONDS = 10.0
# Git's repository-local variables (``git rev-parse --local-env-vars``, git 2.43): each makes
# git read another repository, index, config or work tree than the tree's own.
SCRUBBED_VARIABLES: Final = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
    "GIT_DIR",
    "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
)

_LISTING_FAILED: Final = "could not list the files: "
_READING_FAILED: Final = "could not read the files: "
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

    ``by_path`` are looked at by path whatever the listing says, each on its own, so one that
    cannot be read (``could not read the files: …``) never loses the others; ``listing`` asks
    for the tree's file list, and a failure to make or read it (``could not list the files:
    …``) loses only the listing. When both fail, the listing's problem is the one returned.
    Raises ``ValueError`` for a ``by_path`` entry that is not plain and relative.
    """
    fixed, fixed_problem = _read_fixed(root, by_path)
    try:
        found = _list_tree(root) if listing else _NO_LISTING
        unread = sorted(set(found.paths) - found.entries.keys() - fixed.keys())
        looked = read_planned_tree(root, paths=unread, wanted=unread).entries if unread else {}
    except (GeneratorError, _GitError) as error:
        return HubFiles(
            entries=_sorted(fixed),
            listed=(),
            problem=_LISTING_FAILED + one_line(str(error)),
            paths_read=fixed_problem is None,
        )
    entries = {**found.entries, **looked, **fixed}
    listed = tuple(
        path for path in found.paths if isinstance(entries.get(path), FileEntry | LinkEntry)
    )
    return HubFiles(
        entries=_sorted(entries),
        listed=listed,
        problem=fixed_problem,
        paths_read=fixed_problem is None,
    )


def read_checkout(root: Path) -> HubFiles:
    """The listed files of the repo checkout at ``root`` (already a real path), each one read.

    The listing is made as ``read_doctor_tree`` makes it; when it cannot be (git missing or
    failing, a folder of the walk unreadable) that is the ``problem`` and nothing is listed. A
    listed file that cannot be read is recorded with no content and stays listed.
    """
    try:
        found = _list_tree(root, read_files=False)
    except (GeneratorError, _GitError) as error:
        return HubFiles(
            entries={},
            listed=(),
            problem=_LISTING_FAILED + one_line(str(error)),
            paths_read=True,
        )
    unread = sorted(
        path
        for path in found.paths
        if path not in found.entries
        or (isinstance(entry := found.entries[path], FileEntry) and entry.content is None)
    )
    entries = {**found.entries, **_read_each(root, unread, known=found.entries)}
    listed = tuple(
        path for path in found.paths if isinstance(entries.get(path), FileEntry | LinkEntry)
    )
    return HubFiles(entries=_sorted(entries), listed=listed, problem=None, paths_read=True)


def _read_each(
    root: Path, paths: Collection[str], *, known: Mapping[str, TreeEntry]
) -> dict[str, TreeEntry]:
    """The entries of ``paths``, read together, else one by one when one cannot be read.

    A path that cannot be read keeps what the listing knew of it, else a file with no content.
    """
    if not paths:
        return {}
    try:
        return dict(read_planned_tree(root, paths=paths, wanted=paths).entries)
    except GeneratorError:
        pass
    entries: dict[str, TreeEntry] = {}
    for path in paths:
        try:
            found = read_planned_tree(root, paths=[path], wanted=[path]).entries
        except GeneratorError:
            entries[path] = known.get(path, FileEntry(executable=False, content=None))
            continue
        # As ``_read_fixed``: a leftover-shaped name never replaces a path's own read.
        entries = {**found, **entries}
        if path in found:
            entries[path] = found[path]
    return entries


def _read_fixed(root: Path, by_path: Collection[str]) -> tuple[dict[str, TreeEntry], str | None]:
    """The entries of ``by_path`` present, and the first one's problem that cannot be read."""
    entries: dict[str, TreeEntry] = {}
    problems: list[str] = []
    for path in sorted(by_path):
        try:
            found = read_planned_tree(root, paths=[path], wanted=[path]).entries
        except GeneratorError as error:
            problems.append(_READING_FAILED + one_line(str(error)))
            continue
        # A read also records the leftover-shaped names of the folders it lists, unread: such a
        # name never replaces an entry recorded before, and a path's own read always does.
        entries = {**found, **entries}
        if path in found:
            entries[path] = found[path]
    return entries, next(iter(problems), None)


def _sorted(entries: Mapping[str, TreeEntry]) -> dict[str, TreeEntry]:
    return {path: entries[path] for path in sorted(entries)}


def _list_tree(root: Path, *, read_files: bool = True) -> _Listing:
    if not _has_git_entry(root):
        walked = (read_every_file(root) if read_files else list_every_file(root)).entries
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
