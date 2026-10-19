"""``RepoChangesReader`` over ``git``: a checkout's changes against its base branch.

Read only: every command reads (``rev-parse``, ``symbolic-ref``, ``merge-base``, ``log``,
``diff``, ``ls-files``), nothing writes a ref, the index or the working tree, and git runs as the
learning actions run it (``git_runner``: an argv list, no shell, no prompt, git's location
variables dropped, stderr discarded), all under one deadline.

The base is ``origin/HEAD`` when the clone knows it, else the first of ``origin/main``,
``origin/master``, ``main`` and ``master`` that exists; the branch is compared from where it
forked from it (``git merge-base``), as a pull request is. The files are ``git diff <fork>``
(the working tree against the fork: committed, staged and unstaged changes alike, renames found)
plus the untracked files git does not ignore, read as all added. Each file's commits come from
``git log --numstat`` over ``<fork>..HEAD``.
"""

import hashlib
import os
import shutil
import stat
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
    RepoFileChange,
    RepoFileCommit,
    RepoFileStatus,
)
from agent_hub.hub_git.git_runner import GIT_OPTIONS, ProcessResult, child_env, run_process

# One deadline for every git command of one repository.
READ_SECONDS: Final = 20.0
# The most of a command's stdout that is read: a diff past it is cut, and its last file dropped.
READ_LIMIT: Final = 16 * 1024 * 1024
# Paths as they are (no octal escapes), no colour, no pager, no external diff tool.
_READ_OPTIONS: Final = (*GIT_OPTIONS, "-c", "core.quotePath=false", "--no-pager")
_BASES: Final = ("origin/main", "origin/master", "main", "master")
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
        environ: Mapping[str, str] | None = None,
        launch: ReadLaunch = _LAUNCH,
        seconds: float = READ_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._git = git
        self._env = child_env(dict(os.environ if environ is None else environ))
        self._launch = launch
        self._seconds = seconds
        self._clock = clock

    def read(self, root: str, *, label: str) -> RepoChanges:
        """The changes of the checkout at ``root``; ``RepoChangesError`` when git cannot read
        it."""
        program = shutil.which(self._git, path=self._env.get("PATH") or "")
        if program is None:
            raise RepoChangesError(label)
        run = _Run(
            launch=self._launch,
            git=os.path.abspath(program),
            env=self._env,
            cwd=Path(root),
            seconds=self._seconds,
            clock=self._clock,
        )
        if run.text("rev-parse", "--is-inside-work-tree").strip() != "true":
            raise RepoChangesError(label)
        branch = run.text("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
        base = GitRepoChanges._base(run)
        if base is None:
            return RepoChanges(root=root, label=label, branch=branch or None)
        fork = run.text("merge-base", "HEAD", base, check=False).strip()
        if not fork:
            return RepoChanges(root=root, label=label, branch=branch or None, base=base)
        commits, by_path = _history(run, fork)
        files, cut = _files(run, root, fork, by_path=by_path)
        truncated = cut or len(commits) > MAX_COMMITS
        return RepoChanges(
            root=root,
            label=label,
            branch=branch or None,
            base=base,
            base_sha=fork,
            commits=tuple(commits[:MAX_COMMITS]),
            files=files,
            truncated=truncated,
        )

    @staticmethod
    def _base(run: _Run) -> str | None:
        remote_head = run.text(
            "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False
        ).strip()
        for candidate in (remote_head, *_BASES):
            if not candidate:
                continue
            found = run.result("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
            if found.returncode == 0:
                return candidate
        return None


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
