"""``BrainChangeRequests`` over ``git`` and ``gh`` (L8, ADR 0024, E8).

An action works in a temporary clone of the hub's ``origin`` that borrows the hub's objects
(``--reference-if-able``), never in the user's checkout, so its working tree, index, refs and
worktree list stay as they were. It takes the note from ``origin/<default_branch>``, or, when
``/learn`` wrote it in the checkout and it was never pushed, reads it from there (the checkout is
only read); it checks that the destination and the branch are free; builds one commit with plumbing (no checkout, no
hook) that moves the note and sets its frontmatter, as the change's author; pushes that one new
branch through the push guard; and opens the pull request with ``gh pr create``. When the push
or ``gh`` fails (a timeout may come after GitHub accepted the ref), the branch is deleted again
so a retry starts clean. A retry that still finds the branch on ``origin`` (the action got as far
as the pull request, or its cleanup failed) adopts the branch's open pull request and returns it;
with none open it deletes the branch, which can only be this action's (``<prefix>learning-
<action>-<slug>``), and goes on. The temporary folder is always removed, and no git or gh output
is logged, kept or put in an error.
"""

import contextlib
import os
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Final

from agent_hub.core.brain.brain_path import (
    BRAIN_FOLDER,
    MAX_NOTE_BYTES,
    BrainPathError,
    accept_destination,
    archive_destination,
    inbox_note,
    learning_branch,
)
from agent_hub.core.brain.frontmatter import FrontmatterError, with_frontmatter
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    ChangeRequestConflictError,
    ChangeRequestError,
    ChangeRequestFailedError,
    ChangeRequestResult,
    RefspecRefusedError,
)
from agent_hub.hub_git.git_runner import GitRunner, GitSession
from agent_hub.hub_git.github_remote import (
    UnexpectedOutputError,
    github_repo,
    open_pull_request_url,
    pull_request_url,
)
from agent_hub.hub_git.refspec_guard import push_argv

# Why actions are unavailable for a hub (shown to the owner as they are).
READ_ONLY: Final = "Hub is read-only here"
NO_GIT: Final = "git is not installed"
NOT_A_CHECKOUT: Final = "Hub is not a git checkout"
NOT_GITHUB: Final = "Hub remote is not on GitHub"
NO_GH: Final = "gh is not installed"
NOT_SIGNED_IN: Final = "gh is not signed in to GitHub"
CHECK_TIMED_OUT: Final = "Could not check the hub in time"
# The availability checks run local commands only; deleting a branch after a failed ``gh`` gets
# a budget of its own, since the action's deadline may be what failed.
CHECK_SECONDS: Final = 10.0
CLEANUP_SECONDS: Final = 15.0
CONTAINER_VARIABLE: Final = "AGENT_HUB_IN_CONTAINER"
GITHUB_HOST: Final = "github.com"
_REGULAR_MODES: Final = frozenset({"100644", "100755"})
_NEW_FILE_MODE: Final = "100644"
_CLONE: Final = "clone"


def _conflict(reason: str) -> ChangeRequestConflictError:
    return ChangeRequestConflictError(reason)


def _checked_note(change: BrainChange) -> PurePosixPath:
    try:
        return inbox_note(f"{BRAIN_FOLDER}/{change.note}")
    except BrainPathError as error:
        raise _conflict(error.reason) from None


def _check_destination(change: BrainChange, note: PurePosixPath) -> None:
    try:
        allowed = (
            accept_destination(change.destination, note)
            if change.action == "accept"
            else archive_destination(note)
        )
    except BrainPathError as error:
        raise _conflict(error.reason) from None
    if allowed != change.destination:
        raise _conflict(f"Destination not allowed: brain/{change.destination}")


def _branch_prefix(change: BrainChange, note: PurePosixPath) -> str:
    """The hub's branch prefix: what precedes ``learning-<action>-<note slug>`` in the branch."""
    suffix = learning_branch(branch_prefix="", action=change.action, note=note)
    if not change.branch.endswith(suffix):
        reason = f"Push refused: {change.branch!r} is not the {change.action} branch of the note"
        raise RefspecRefusedError(reason)
    prefix = change.branch.removesuffix(suffix)
    push_argv(change.branch, default_branch=change.default_branch, prefix=prefix)
    return prefix


def _text(stdout: bytes) -> str:
    return stdout.decode("utf-8", errors="replace").strip()


class GitBrainChangeRequests:
    """Opens hub pull requests for learning decisions with ``git`` and ``gh``.

    ``temp_root`` is where the temporary clones go (the system's temporary folder by default).
    """

    def __init__(self, runner: GitRunner, temp_root: Path | str | None = None) -> None:
        self._runner = runner
        self._temp_root = None if temp_root is None else Path(temp_root)

    def availability(self, hub_path: str) -> str | None:
        """Why actions are unavailable for the hub at ``hub_path``, or None when they are not:
        the container image or a hub folder that is missing or not writable, no ``git``, not a
        git checkout's root, an ``origin`` not on GitHub, no ``gh``, ``gh`` not signed in."""
        try:
            return self._unavailable(Path(hub_path), self._runner.start(seconds=CHECK_SECONDS))
        except ChangeRequestError:
            return CHECK_TIMED_OUT

    def accept(self, change: BrainChange) -> ChangeRequestResult:
        """Push a branch that moves the note into the brain and open its PR."""
        return self._open(change)

    def reject(self, change: BrainChange) -> ChangeRequestResult:
        """Push a branch that archives the note with the reason and open its PR."""
        return self._open(change)

    def _unavailable(self, hub: Path, session: GitSession) -> str | None:
        runner = self._runner
        if runner.environ.get(CONTAINER_VARIABLE) == "1":
            return READ_ONLY
        if not hub.is_dir() or not os.access(hub, os.W_OK):
            return READ_ONLY
        if runner.program(runner.git_name) is None:
            return NO_GIT
        top = session.git(["rev-parse", "--show-toplevel"], cwd=hub, step="checkout", check=False)
        if top.returncode != 0 or Path(_text(top.stdout)).resolve() != hub.resolve():
            return NOT_A_CHECKOUT
        if github_repo(self._origin_url(hub, session)) is None:
            return NOT_GITHUB
        if runner.program(runner.gh_name) is None:
            return NO_GH
        auth = ["auth", "token", "--hostname", GITHUB_HOST]
        signed_in = session.gh(auth, cwd=hub, step="auth", keep_stdout=False, check=False)
        return None if signed_in.returncode == 0 else NOT_SIGNED_IN

    @staticmethod
    def _origin_url(hub: Path, session: GitSession) -> str:
        args = ["config", "--get", "remote.origin.url"]
        found = session.git(args, cwd=hub, step="origin", check=False)
        return _text(found.stdout) if found.returncode == 0 else ""

    def _open(self, change: BrainChange) -> ChangeRequestResult:
        note = _checked_note(change)
        _check_destination(change, note)
        prefix = _branch_prefix(change, note)
        hub = Path(change.hub_path)
        session = self._runner.start()
        reason = self._unavailable(hub, session)
        if reason is not None:
            raise _conflict(reason)
        url = self._origin_url(hub, session)
        if (github_repo(url) or "").lower() != change.hub_repo.lower():
            raise _conflict(f"Hub remote is not {change.hub_repo}")
        work = Path(tempfile.mkdtemp(prefix="hub-learning-", dir=self._temp_root))
        try:
            action = _Action(self._runner, session, change=change, work=work, prefix=prefix)
            return action.run(url=url, hub=hub)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class _Action:
    """One accept or reject in the temporary folder ``work`` (the clone is ``work/clone``)."""

    def __init__(
        self,
        runner: GitRunner,
        session: GitSession,
        *,
        change: BrainChange,
        work: Path,
        prefix: str,
    ) -> None:
        self._runner = runner
        self._session = session
        self._change = change
        self._work = work
        self._clone = work / _CLONE
        self._prefix = prefix

    def run(self, *, url: str, hub: Path) -> ChangeRequestResult:
        change = self._change
        self._clone_origin(url, hub)
        base = self._base()
        if self._branch_on_origin():
            adopted = self._open_pull_request_of_branch()
            if adopted is not None:
                return ChangeRequestResult(pr_url=adopted, branch=change.branch)
            self._push(delete=True)
        self._refuse_taken(base)
        mode, text = self._note(base)
        commit = self._commit(base, mode, text)
        self._git(["update-ref", f"refs/heads/{change.branch}", commit, ""], step="branch")
        try:
            self._push()
            pr_url = self._open_pull_request()
        except ChangeRequestError:
            self._delete_branch()
            raise
        return ChangeRequestResult(pr_url=pr_url, branch=change.branch)

    def _push(self, *, delete: bool = False) -> None:
        change = self._change
        self._session.push(
            change.branch,
            cwd=self._clone,
            default_branch=change.default_branch,
            prefix=self._prefix,
            delete=delete,
        )

    def _git(self, args: list[str], *, step: str, check: bool = True) -> bytes:
        return self._session.git(args, cwd=self._clone, step=step, check=check).stdout

    def _clone_origin(self, url: str, hub: Path) -> None:
        args = [
            "clone",
            "--quiet",
            "--no-checkout",
            "--single-branch",
            "--no-tags",
            f"--branch={self._change.default_branch}",
            f"--reference-if-able={hub}",
            "--",
            url,
            str(self._clone),
        ]
        self._session.git(args, cwd=self._work, step="clone")

    def _base(self) -> str:
        ref = f"refs/remotes/origin/{self._change.default_branch}^{{commit}}"
        return _text(self._git(["rev-parse", "--verify", "--end-of-options", ref], step="clone"))

    def _entry(self, base: str, path: str) -> tuple[str, str, str] | None:
        """``(mode, type, object)`` of ``brain/<path>`` in ``base``, or None when absent."""
        listed = self._git(["ls-tree", "-z", base, "--", f"{BRAIN_FOLDER}/{path}"], step="read")
        entry = listed.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        if not entry:
            return None
        mode, kind, name = entry.split("\t", 1)[0].split(" ")
        return mode, kind, name

    def _branch_on_origin(self) -> bool:
        heads = ["ls-remote", "--heads", "origin", f"refs/heads/{self._change.branch}"]
        return bool(_text(self._git(heads, step="branch")))

    def _open_pull_request_of_branch(self) -> str | None:
        """The url of the open pull request whose head is the change's branch, or None."""
        change = self._change
        args = [
            "pr",
            "list",
            "--repo",
            change.hub_repo,
            "--head",
            change.branch,
            "--state",
            "open",
            "--json",
            "url",
        ]
        listed = self._session.gh(args, cwd=self._clone, step="pr")
        try:
            return open_pull_request_url(listed.stdout, hub_repo=change.hub_repo)
        except UnexpectedOutputError:
            raise ChangeRequestFailedError(step="pr") from None

    def _refuse_taken(self, base: str) -> None:
        change = self._change
        if self._entry(base, change.destination) is not None:
            raise _conflict(f"Destination exists: brain/{change.destination}")

    def _note(self, base: str) -> tuple[str, str]:
        change = self._change
        shown = f"brain/{change.note}"
        entry = self._entry(base, change.note)
        if entry is None:
            return _NEW_FILE_MODE, self._checkout_note(shown)
        mode, kind, blob = entry
        if kind != "blob" or mode not in _REGULAR_MODES:
            raise _conflict(f"Note is not a regular file: {shown}")
        if int(_text(self._git(["cat-file", "-s", blob], step="read"))) > MAX_NOTE_BYTES:
            raise _conflict(f"Note too large: {shown}")
        raw = self._git(["cat-file", "blob", blob], step="read")
        try:
            return mode, raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _conflict(f"Note is not UTF-8 text: {shown}") from None

    def _checkout_note(self, shown: str) -> str:
        """The note as it sits in the hub checkout, for a note ``/learn`` wrote there and nobody
        pushed yet: it is only read (never through a link), and the branch then adds it."""
        change = self._change
        missing = f"Note not on origin/{change.default_branch} nor in the hub checkout: {shown}"
        path = Path(change.hub_path) / BRAIN_FOLDER / change.note
        try:
            found = path.lstat()
        except OSError:
            raise _conflict(missing) from None
        if not stat.S_ISREG(found.st_mode):
            raise _conflict(f"Note is not a regular file: {shown}")
        if found.st_size > MAX_NOTE_BYTES:
            raise _conflict(f"Note too large: {shown}")
        try:
            return path.read_bytes().decode("utf-8")
        except OSError:
            raise _conflict(missing) from None
        except UnicodeDecodeError:
            raise _conflict(f"Note is not UTF-8 text: {shown}") from None

    def _commit(self, base: str, mode: str, text: str) -> str:
        change = self._change
        try:
            moved = with_frontmatter(text, change.frontmatter)
        except FrontmatterError:
            raise _conflict(f"Note frontmatter is not closed: brain/{change.note}") from None
        note_file = self._work / "note.md"
        note_file.write_bytes(moved.encode("utf-8"))
        hashed = ["hash-object", "-w", "--no-filters", "--", str(note_file)]
        blob = _text(self._git(hashed, step="commit"))
        self._git(["read-tree", base], step="commit")
        self._git(["update-index", "--force-remove", "--", f"brain/{change.note}"], step="commit")
        cacheinfo = f"{mode},{blob},brain/{change.destination}"
        self._git(["update-index", "--add", "--cacheinfo", cacheinfo], step="commit")
        tree = _text(self._git(["write-tree"], step="commit"))
        author = change.author
        identity = {
            "GIT_AUTHOR_NAME": author.name,
            "GIT_AUTHOR_EMAIL": author.email,
            "GIT_COMMITTER_NAME": author.name,
            "GIT_COMMITTER_EMAIL": author.email,
        }
        args = ["commit-tree", tree, "-p", base, "-m", change.commit_message]
        made = self._session.git(args, cwd=self._clone, step="commit", extra_env=identity)
        return _text(made.stdout)

    def _open_pull_request(self) -> str:
        change = self._change
        body_file = self._work / "body.md"
        body_file.write_text(change.body, encoding="utf-8")
        args = [
            "pr",
            "create",
            f"--repo={change.hub_repo}",
            f"--base={change.default_branch}",
            f"--head={change.branch}",
            f"--title={change.title}",
            f"--body-file={body_file}",
        ]
        created = self._session.gh(args, cwd=self._clone, step="pr")
        pr_url = pull_request_url(created.stdout, hub_repo=change.hub_repo)
        if pr_url is None:
            raise ChangeRequestFailedError(step="pr")
        return pr_url

    def _delete_branch(self) -> None:
        change = self._change
        cleanup = self._runner.start(seconds=CLEANUP_SECONDS)
        with contextlib.suppress(ChangeRequestError):
            cleanup.push(
                change.branch,
                cwd=self._clone,
                default_branch=change.default_branch,
                prefix=self._prefix,
                delete=True,
            )
