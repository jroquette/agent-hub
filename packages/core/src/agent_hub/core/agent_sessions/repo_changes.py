"""What a session's repositories change against their base branch: the pull request's diff.

The chat knows a file only through the file tools Claude called in that session, so a change made
from the shell, by another session or before this one never shows there. This reads git instead:
for each repository a session worked in, its branch, the base it forked from, the commits since,
and every file that differs from the base (committed or not), with its diff and the commits that
touched it.

Git runs only in a listed workdir (``WorkdirListing``: the hub's repos and their worktrees), never
in a path taken from the session's log: ``repo_roots`` picks the listed repos and worktrees that
hold the session's folder or one of the files it changed, deepest first, so a worktree wins over
the repo it sits in. The reading itself is the ``RepoChangesReader`` port's (``hub_git``).
"""

import os
from collections.abc import Iterable, Sequence
from typing import Final, Literal, Protocol

from pydantic import Field

from agent_hub.core.agent_sessions.workdirs import ResolvedWorkdir, WorkdirListing
from agent_hub.core.readmodels.view_types import ViewModel

# At most this many repositories per session, commits per repository and files per repository.
MAX_REPOS: Final = 8
MAX_COMMITS: Final = 200
MAX_REPO_FILES: Final = 500
# A file's diff past this many UTF-8 bytes is left out (``diff`` null, the stats still count).
REPO_DIFF_MAX_BYTES: Final = 512 * 1024

# A commit as the routes take it: 7 to 40 hex digits, never a ref name or an option.
COMMIT_SHA_PATTERN: Final = r"^[0-9a-f]{7,40}$"

type RepoFileStatus = Literal["added", "modified", "deleted", "renamed"]


class RepoCommit(ViewModel):
    """A commit of the branch since its base, newest first."""

    sha: str
    subject: str
    authored_at: str
    author: str


class RepoFileCommit(ViewModel):
    """A commit that touched a file, and the lines it added and removed there."""

    sha: str
    added: int = Field(ge=0)
    removed: int = Field(ge=0)


class RepoFileChange(ViewModel):
    """A file that differs from the base: committed on the branch, staged, unstaged or
    untracked. ``path`` is absolute (the repository's folder joined with git's path), as Claude's
    file tools name it; ``old_path`` the name before a rename. ``diff`` is the unified diff from
    the base to the working tree, with the file's line numbers; null for a binary file or one
    past ``REPO_DIFF_MAX_BYTES``. ``fingerprint`` changes whenever the diff does (a review mark
    is kept against it). ``commits`` are the branch's commits that touched it, newest first;
    ``uncommitted`` says the working tree differs from ``HEAD`` too."""

    path: str
    old_path: str | None = None
    status: RepoFileStatus
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    diff: str | None = None
    binary: bool = False
    fingerprint: str
    commits: tuple[RepoFileCommit, ...] = ()
    uncommitted: bool = False


class RepoChanges(ViewModel):
    """One repository's changes against its base. ``root`` is the folder git ran in, ``branch``
    its checked-out branch (null when detached), ``base`` the ref the branch is compared with
    (``origin/main``…, null when none was found: then nothing is compared and ``files`` is
    empty), ``base_sha`` the commit the branch forked from. ``truncated`` says commits or files
    were left out past the bounds."""

    root: str
    label: str
    branch: str | None = None
    base: str | None = None
    base_sha: str | None = None
    commits: tuple[RepoCommit, ...] = ()
    files: tuple[RepoFileChange, ...] = ()
    truncated: bool = False


class SessionRepoChanges(ViewModel):
    """``GET /agent-sessions/{id}/repo-changes``: each repository the session worked in, and the
    ones that could not be read (``warnings``, named by folder label)."""

    repos: tuple[RepoChanges, ...] = ()
    warnings: tuple[str, ...] = ()


class RepoCommitDiff(ViewModel):
    """``GET /agent-sessions/{id}/repo-changes/commit``: what one commit changed in one file, as a
    unified diff with the file's line numbers. ``diff`` is null for a binary file or one past
    ``REPO_DIFF_MAX_BYTES``, empty when the commit did not touch the file."""

    sha: str
    path: str
    diff: str | None = None
    binary: bool = False


class RepoChangesReader(Protocol):
    """Reads one listed repository's changes against its base (the ``hub_git`` adapter)."""

    def read(self, root: str, *, label: str) -> RepoChanges:
        """The changes of the repository checked out at ``root``; ``RepoChangesError`` when
        git cannot read it."""
        ...

    def commit_diff(self, root: str, *, sha: str, paths: Sequence[str]) -> RepoCommitDiff:
        """What commit ``sha`` changed in ``paths`` (relative to ``root``: a file and the name it
        had before a rename); ``RepoChangesError`` when git cannot read it (no such commit)."""
        ...


class RepoChangesError(Exception):
    """Git could not read a repository (not a checkout, git missing, a timeout)."""


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def repo_roots(
    listing: WorkdirListing, *, workdir_id: str, paths: Iterable[str]
) -> tuple[ResolvedWorkdir, ...]:
    """The listed repos and worktrees a session worked in: the one it started in (when it is a
    repo or a worktree) and the deepest one holding each of ``paths``, in that order, at most
    ``MAX_REPOS``. The hub is never one: its files are the brain's, not a pull request's."""
    candidates = [entry for entry in listing.entries if entry.workdir.kind != "hub"]
    # Deepest first: a worktree under ``<repo>/.claude/worktrees/`` wins over its repo.
    candidates.sort(key=lambda entry: len(entry.path), reverse=True)
    roots: list[ResolvedWorkdir] = [
        entry for entry in candidates if entry.workdir.workdir_id == workdir_id
    ]
    for path in paths:
        hit = next((entry for entry in candidates if _inside(path, entry.path)), None)
        if hit is not None and hit not in roots:
            roots.append(hit)
    return tuple(roots[:MAX_REPOS])


def relative_to_root(root: str, path: str) -> str | None:
    """``path`` relative to ``root`` when it is a file inside it (no ``..`` part), else None."""
    if not _inside(path, root) or path == root:
        return None
    rel = os.path.relpath(path, root)
    if rel.startswith("..") or os.path.isabs(rel) or ".." in rel.split(os.sep):
        return None
    return rel
