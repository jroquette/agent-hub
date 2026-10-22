"""``RepoChangesReader`` over ``git``: a checkout's changes against its base branch.

Read only: every command reads (``rev-parse``, ``symbolic-ref``, ``reflog``, ``merge-base``,
``log``, ``diff``, ``ls-files``), nothing writes a ref, the index or the working tree, and git
runs as the learning actions run it (``git_runner``: an argv list, no shell, no prompt, git's
location variables dropped, stderr discarded), all under one deadline.

The base is the branch the checkout's branch was started from, as git recorded it: the
``Created from <ref>`` of its reflog (``git worktree add -b <branch> <path> <base>`` and
``git branch <branch> <base>`` write it), else its upstream when that is another branch (not its
own pushed copy). A branch started from ``batatinha`` is compared with ``batatinha``, one started
from ``origin/main`` with ``origin/main``. Without either (a reflog expired, a branch made from
``HEAD``), the base is ``origin/HEAD`` when the clone knows it, else the first of
``origin/main``, ``origin/master``, ``main`` and ``master`` that exists. The branch is compared
from where it forked from its base (``git merge-base``), as a pull request is. The files are
``git diff <fork>`` (the working tree against the fork: committed, staged and unstaged changes
alike, renames found) plus the untracked files git does not ignore, read as all added. Each
file's commits come from ``git log --numstat`` over ``<fork>..HEAD``.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Final, Protocol

from agent_hub.core.agent_sessions.repo_changes import (
    MAX_COMMITS,
    MAX_REPO_FILES,
    REPO_DIFF_MAX_BYTES,
    RepoChanges,
    RepoChangesError,
    RepoCommit,
    RepoCommitDiff,
    RepoFileChange,
    RepoFileCommit,
    RepoFileStatus,
    RepoFileText,
    RepoPullRequest,
)
from agent_hub.hub_git.git_runner import GIT_OPTIONS, ProcessResult, child_env, run_process

# One deadline for every git command of one repository.
READ_SECONDS: Final = 20.0
# The most of a command's stdout that is read: a diff past it is cut, and its last file dropped.
READ_LIMIT: Final = 16 * 1024 * 1024
# Paths as they are (no octal escapes), no colour, no pager, no external diff tool.
_READ_OPTIONS: Final = (*GIT_OPTIONS, "-c", "core.quotePath=false", "--no-pager")
_BASES: Final = ("origin/main", "origin/master", "main", "master")
# How long ``gh`` may take to name a branch's pull request.
PR_SECONDS: Final = 8.0
# How git's reflog names a branch's first entry: ``branch: Created from <ref>``.
_CREATED_FROM: Final = "branch: Created from "
_RECORD: Final = "\x1e"
_LAUNCH: Final = partial(run_process, limit=READ_LIMIT)
_FIELD: Final = "\x1f"


class ReadLaunch(Protocol):
    """Starts one git child and waits for it (``git_runner.run_process`` with a limit)."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        """Run ``argv``."""
        ...


@dataclass
class _Patch:
    path: str
    old_path: str | None = None
    status: RepoFileStatus = "modified"
    binary: bool = False
    lines: list[str] = field(default_factory=list)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _unquote(path: str) -> str:
    """A path git quoted (it holds a quote, a backslash or a control character) without its
    quotes; git's escapes are left as they are, so such a path matches nothing."""
    return path[1:-1] if len(path) > 1 and path[0] == path[-1] == '"' else path


def _strip_prefix(path: str) -> str:
    path = _unquote(path)
    return path[2:] if path[:2] in {"a/", "b/"} else path


def _header(patch: _Patch, line: str) -> bool:
    """Read one line of a file's header into ``patch``; True once its first hunk starts."""
    if line.startswith("@@"):
        patch.lines.append(line)
        return True
    if line.startswith("new file mode"):
        patch.status = "added"
    elif line.startswith("deleted file mode"):
        patch.status = "deleted"
    elif line.startswith("rename from "):
        patch.status = "renamed"
        patch.old_path = _unquote(line.removeprefix("rename from "))
    elif line.startswith("rename to "):
        patch.path = _unquote(line.removeprefix("rename to "))
    elif line.startswith("Binary files ") or line == "GIT binary patch":
        patch.binary = True
    elif line.startswith(("--- ", "+++ ")):
        _name_line(patch, line)
    return False


def _name_line(patch: _Patch, line: str) -> None:
    """A ``---``/``+++`` line: kept in the diff; ``+++`` names the file (unless deleted)."""
    patch.lines.append(line)
    name = line[4:]
    if line.startswith("+++ ") and name != "/dev/null":
        patch.path = _strip_prefix(name)


def _first_patch(line: str) -> _Patch:
    """A file from its ``diff --git a/<old> b/<new>`` line: the b/ side, until a later header
    names it more surely."""
    names = line.removeprefix("diff --git ")
    at = names.rfind(" b/")
    return _Patch(path=_strip_prefix(names[at + 1 :]) if at >= 0 else names)


def parse_patch(text: str) -> list[_Patch]:
    """The files of ``git diff`` output, each with its status and its diff from ``---`` on."""
    patches: list[_Patch] = []
    in_hunks = False
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            patches.append(_first_patch(line))
            in_hunks = False
        elif not patches:
            continue
        elif in_hunks:
            patches[-1].lines.append(line)
        else:
            in_hunks = _header(patches[-1], line)
    for patch in patches:
        while patch.lines and patch.lines[-1] == "":
            patch.lines.pop()
    return patches


def _stats(lines: Sequence[str]) -> tuple[int, int]:
    added = removed = 0
    in_hunks = False
    for line in lines:
        if line.startswith("@@"):
            in_hunks = True
        elif in_hunks and line.startswith("+"):
            added += 1
        elif in_hunks and line.startswith("-"):
            removed += 1
    return added, removed


def parse_log(text: str) -> tuple[list[RepoCommit], dict[str, list[RepoFileCommit]]]:
    """The commits of ``git log --format=<record> --numstat --no-renames``, newest first, and
    each path's commits with the lines they added and removed there."""
    commits: list[RepoCommit] = []
    by_path: dict[str, list[RepoFileCommit]] = {}
    for record in text.split(_RECORD):
        if not record.strip():
            continue
        head, _, rest = record.partition("\n")
        parts = head.split(_FIELD)
        if len(parts) != 4:  # noqa: PLR2004 -- sha, author, date, subject
            continue
        sha, author, authored_at, subject = parts
        commits.append(RepoCommit(sha=sha, subject=subject, authored_at=authored_at, author=author))
        for line in rest.splitlines():
            columns = line.split("\t")
            if len(columns) != 3:  # noqa: PLR2004 -- added, removed, path
                continue
            added, removed, path = columns
            by_path.setdefault(_unquote(path), []).append(
                RepoFileCommit(
                    sha=sha,
                    added=int(added) if added.isdigit() else 0,
                    removed=int(removed) if removed.isdigit() else 0,
                )
            )
    return commits, by_path


def _added_file_diff(rel: str, text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    head = ["--- /dev/null", f"+++ b/{rel}"]
    if not lines:
        return head
    return [*head, f"@@ -0,0 +1,{len(lines)} @@", *(f"+{line}" for line in lines)]


class GitRepoChanges:
    """``RepoChangesReader`` with ``git`` as a child process (see the module docstring)."""

    def __init__(
        self,
        *,
        git: str = "git",
        gh: str = "gh",
        environ: Mapping[str, str] | None = None,
        launch: ReadLaunch = _LAUNCH,
        seconds: float = READ_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._git = git
        self._gh = gh
        self._env = child_env(dict(os.environ if environ is None else environ))
        self._launch = launch
        self._seconds = seconds
        self._clock = clock

    def read(self, root: str, *, label: str) -> RepoChanges:
        """The changes of the checkout at ``root``; ``RepoChangesError`` when git cannot read
        it."""
        run = self._run(root, label=label)
        if run.text("rev-parse", "--is-inside-work-tree").strip() != "true":
            raise RepoChangesError(label)
        branch = run.text("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
        base = GitRepoChanges._base(run, branch)
        if base is None:
            return RepoChanges(root=root, label=label, branch=branch or None)
        fork = run.text("merge-base", "HEAD", base, check=False).strip()
        if not fork:
            return RepoChanges(root=root, label=label, branch=branch or None, base=base)
        commits, by_path = _history(run, fork)
        files, cut = _files(run, root, fork, by_path=by_path)
        truncated = cut or len(commits) > MAX_COMMITS
        head = run.text("rev-parse", "--verify", "--quiet", "HEAD", check=False).strip()
        return RepoChanges(
            root=root,
            label=label,
            branch=branch or None,
            base=base,
            base_sha=fork,
            head_sha=head or None,
            commits=tuple(commits[:MAX_COMMITS]),
            files=files,
            truncated=truncated,
        )

    def read_recorded(  # noqa: PLR0913 -- what a review recorded of one repository
        self,
        repo_root: str,
        *,
        label: str,
        root: str,
        branch: str | None,
        base: str | None,
        base_sha: str,
        head_sha: str,
    ) -> RepoChanges:
        """The recorded commits, read in the repo's own checkout (see the port)."""
        run = self._run(repo_root, label=label)
        head = _commit(run, head_sha)
        if head is None and branch:
            head = _commit(run, f"refs/remotes/origin/{branch}") or _commit(
                run, f"refs/heads/{branch}"
            )
        fork = _commit(run, base_sha)
        if head is None or fork is None:
            raise RepoChangesError(label)
        commits, by_path = parse_log(
            run.text(
                "log",
                "--no-color",
                f"--format={_RECORD}%H{_FIELD}%an{_FIELD}%aI{_FIELD}%s",
                "--numstat",
                "--no-renames",
                f"--max-count={MAX_COMMITS + 1}",
                f"{fork}..{head}",
            )
        )
        patch = run.result("diff", "--no-color", "--no-ext-diff", "-M", fork, head, "--")
        if patch.returncode != 0:
            raise RepoChangesError(label)
        patches = parse_patch(patch.stdout.decode("utf-8", errors="replace"))
        cut = len(patch.stdout) >= READ_LIMIT and bool(patches)
        if cut:
            patches.pop()
        files = [
            _file_change(
                root,
                item,
                commits=[*by_path.get(item.path, ()), *by_path.get(item.old_path or "", ())],
                uncommitted=False,
            )
            for item in patches
        ]
        return RepoChanges(
            root=root,
            label=label,
            branch=branch,
            base=base,
            base_sha=fork,
            head_sha=head,
            source="recorded",
            commits=tuple(commits[:MAX_COMMITS]),
            files=tuple(files[:MAX_REPO_FILES]),
            truncated=cut or len(commits) > MAX_COMMITS or len(files) > MAX_REPO_FILES,
        )

    def pull_request(self, root: str, *, branch: str) -> RepoPullRequest | None:
        """``gh pr list --head <branch>``: the branch's newest pull request, open or not; None
        without ``gh``, when it is not signed in or GitHub does not answer in time."""
        program = shutil.which(self._gh, path=self._env.get("PATH") or "")
        if program is None or not branch or branch.startswith("-"):
            return None
        argv = [
            os.path.abspath(program),
            *("pr", "list", "--head", branch, "--state", "all", "--limit", "1"),
            *("--json", "number,url,state,headRefOid"),
        ]
        # A worktree that is gone: ask from the nearest folder left (its repo, usually).
        folder = Path(root)
        while not folder.is_dir() and folder != folder.parent:
            folder = folder.parent
        try:
            result = self._launch(
                argv, cwd=folder, env=self._env, timeout=PR_SECONDS, keep_stdout=True
            )
        except OSError, subprocess.SubprocessError:
            return None
        if result.returncode != 0:
            return None
        return _pull_request(result.stdout)

    def commit_diff(self, root: str, *, sha: str, paths: Sequence[str]) -> RepoCommitDiff:
        """What commit ``sha`` changed in ``paths`` (``git show``, renames found); the first file
        it names, empty when it touched none of them."""
        run = self._run(root, label=root)
        found = run.result("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        if found.returncode != 0 or not paths:
            raise RepoChangesError(root)
        full = found.stdout.decode().strip()
        shown = run.text(
            "show", "--format=", "--no-color", "--no-ext-diff", "-M", full, "--", *paths
        )
        patches = parse_patch(shown)
        if not patches:
            return RepoCommitDiff(sha=full, path=paths[0], diff="")
        item = patches[0]
        text = "\n".join(item.lines)
        too_big = item.binary or len(text.encode()) > REPO_DIFF_MAX_BYTES
        return RepoCommitDiff(
            sha=full, path=item.path, diff=None if too_big else text, binary=item.binary
        )

    def file_text(self, root: str, *, sha: str, path: str) -> RepoFileText:
        """The file at ``path`` as commit ``sha`` has it (``git show <sha>:<path>``); its text
        null when the commit has no such file, it is binary or past ``REPO_DIFF_MAX_BYTES``."""
        run = self._run(root, label=root)
        found = run.result("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        if found.returncode != 0:
            raise RepoChangesError(root)
        full = found.stdout.decode().strip()
        size = run.result("cat-file", "-s", f"{full}:{path}")
        if size.returncode != 0:
            return RepoFileText(sha=full, path=path)
        if int(size.stdout.decode().strip() or 0) > REPO_DIFF_MAX_BYTES:
            return RepoFileText(sha=full, path=path)
        shown = run.result("show", "--no-color", "--no-textconv", f"{full}:{path}")
        if shown.returncode != 0:
            return RepoFileText(sha=full, path=path)
        if b"\0" in shown.stdout:
            return RepoFileText(sha=full, path=path, binary=True)
        return RepoFileText(
            sha=full, path=path, text=shown.stdout.decode("utf-8", errors="replace")
        )

    def _run(self, root: str, *, label: str) -> _Run:
        program = shutil.which(self._git, path=self._env.get("PATH") or "")
        if program is None:
            raise RepoChangesError(label)
        return _Run(
            launch=self._launch,
            git=os.path.abspath(program),
            env=self._env,
            cwd=Path(root),
            seconds=self._seconds,
            clock=self._clock,
        )

    @staticmethod
    def _base(run: _Run, branch: str) -> str | None:
        remote_head = run.text(
            "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False
        ).strip()
        for candidate in (*_started_from(run, branch), remote_head, *_BASES):
            if not candidate or candidate == branch:
                continue
            found = run.result("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
            if found.returncode == 0:
                return candidate
        return None


def _started_from(run: _Run, branch: str) -> tuple[str, ...]:
    """The refs ``branch`` was started from, as git recorded them: its reflog's oldest
    ``branch: Created from <ref>`` (not ``HEAD``, which says nothing of the branch it was), then
    its upstream unless that is the branch's own copy on the remote."""
    if not branch:
        return ()
    found: list[str] = []
    reflog = run.text("reflog", "show", "--format=%gs", f"refs/heads/{branch}", check=False)
    lines = reflog.strip().splitlines()
    if lines and lines[-1].startswith(_CREATED_FROM):
        ref = lines[-1][len(_CREATED_FROM) :].strip()
        if ref and ref != "HEAD":
            found.append(ref)
    upstream = run.text(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}", check=False
    ).strip()
    if upstream and upstream != branch and not upstream.endswith(f"/{branch}"):
        found.append(upstream)
    return tuple(found)


def _commit(run: _Run, ref: str) -> str | None:
    """The full sha of ``ref`` when it names a commit here, else None."""
    if ref.startswith("-"):
        return None
    found = run.result("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if found.returncode != 0:
        return None
    return found.stdout.decode().strip() or None


def _history(run: _Run, fork: str) -> tuple[list[RepoCommit], dict[str, list[RepoFileCommit]]]:
    """The branch's commits since ``fork`` (one past the bound, to tell it was cut)."""
    return parse_log(
        run.text(
            "log",
            "--no-color",
            f"--format={_RECORD}%H{_FIELD}%an{_FIELD}%aI{_FIELD}%s",
            "--numstat",
            "--no-renames",
            f"--max-count={MAX_COMMITS + 1}",
            f"{fork}..HEAD",
        )
    )


def _files(
    run: _Run, root: str, fork: str, *, by_path: Mapping[str, Sequence[RepoFileCommit]]
) -> tuple[tuple[RepoFileChange, ...], bool]:
    """Every file that differs from ``fork``, tracked then untracked, and whether some were
    left out (the diff was cut, or past ``MAX_REPO_FILES``)."""
    patch = run.result("diff", "--no-color", "--no-ext-diff", "-M", fork, "--")
    if patch.returncode != 0:
        raise RepoChangesError(root)
    patches = parse_patch(patch.stdout.decode("utf-8", errors="replace"))
    cut = len(patch.stdout) >= READ_LIMIT and bool(patches)
    if cut:
        patches.pop()
    dirty = set(run.text("diff", "--name-only", "--no-renames", "HEAD", "--").splitlines())
    files = [
        _file_change(
            root,
            item,
            commits=[*by_path.get(item.path, ()), *by_path.get(item.old_path or "", ())],
            uncommitted=item.path in dirty or (item.old_path or "") in dirty,
        )
        for item in patches
    ]
    untracked = run.text("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    for rel in filter(None, untracked):
        added = _read_untracked(Path(root), rel)
        if added is not None:
            files.append(_file_change(root, added, commits=[], uncommitted=True))
    return tuple(files[:MAX_REPO_FILES]), cut or len(files) > MAX_REPO_FILES


def _file_change(
    root: str, item: _Patch, *, commits: list[RepoFileCommit], uncommitted: bool
) -> RepoFileChange:
    added, removed = _stats(item.lines)
    text = "\n".join(item.lines)
    diff = None if item.binary or len(text.encode()) > REPO_DIFF_MAX_BYTES else text
    fingerprint = _sha(
        f"{item.status}\0{item.old_path or ''}\0{diff if diff is not None else added}"
    )
    return RepoFileChange(
        path=os.path.join(root, item.path),
        old_path=os.path.join(root, item.old_path) if item.old_path else None,
        status=item.status,
        added=added,
        removed=removed,
        diff=diff,
        binary=item.binary,
        fingerprint=fingerprint,
        commits=tuple(commits),
        uncommitted=uncommitted,
    )


def _read_untracked(root: Path, rel: str) -> _Patch | None:
    """An untracked regular file as all added (binary when it is not UTF-8 text); None for a
    link, a folder or a file that cannot be read."""
    path = root / rel
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None
        if info.st_size > REPO_DIFF_MAX_BYTES:
            return _Patch(path=rel, status="added", binary=True)
        data = path.read_bytes()
    except OSError:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _Patch(path=rel, status="added", binary=True)
    if "\0" in text:
        return _Patch(path=rel, status="added", binary=True)
    return _Patch(path=rel, status="added", lines=_added_file_diff(rel, text))


class _Run:
    """The git commands of one read, under one deadline."""

    def __init__(  # noqa: PLR0913 -- one read's settings, all keyword-only
        self,
        *,
        launch: ReadLaunch,
        git: str,
        env: Mapping[str, str],
        cwd: Path,
        seconds: float,
        clock: Callable[[], float],
    ) -> None:
        self._launch = launch
        self._git = git
        self._env = env
        self._cwd = cwd
        self._clock = clock
        self._end = clock() + seconds

    def result(self, *args: str) -> ProcessResult:
        left = self._end - self._clock()
        if left <= 0:
            raise RepoChangesError(str(self._cwd))
        try:
            return self._launch(
                [self._git, *_READ_OPTIONS, *args],
                cwd=self._cwd,
                env=self._env,
                timeout=left,
                keep_stdout=True,
            )
        except (TimeoutError, OSError) as error:
            raise RepoChangesError(str(self._cwd)) from error

    def text(self, *args: str, check: bool = True) -> str:
        result = self.result(*args)
        if check and result.returncode != 0:
            raise RepoChangesError(str(self._cwd))
        return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else ""


def _pull_request(stdout: bytes) -> RepoPullRequest | None:
    """The first pull request of ``gh pr list --json number,url,state,headRefOid``."""
    try:
        found = json.loads(stdout.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    if not isinstance(found, list) or not found or not isinstance(found[0], dict):
        return None
    item = found[0]
    number, url, state, head = (item.get(k) for k in ("number", "url", "state", "headRefOid"))
    if not isinstance(number, int) or not isinstance(url, str):
        return None
    return RepoPullRequest(
        number=number,
        url=url,
        state=state if isinstance(state, str) else "OPEN",
        head_sha=head if isinstance(head, str) else None,
    )
