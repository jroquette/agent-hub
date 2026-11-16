"""The hub's checkout as the knowledge index sees it (AGH-391, ADR 0044: D-sources, D-files, P-7).

The sources are the hub's ``brain/`` (minus ``brain/auto/``) in the hub's main checkout, and
each repo's ``docs/`` in ``<dir>`` beside it. Each source is listed by one ``git ls-files -z
--cached --others --exclude-standard -- <folder>``: tracked files and untracked ones git does
not ignore, never what ``.gitignore`` hides. Git runs as an absolute executable, without the
caller's location variables, with no optional lock, no fsmonitor hook, a ceiling at the source's
parent (it never takes an enclosing repo for the source's), a timeout, and its output bounded
(AM-1). A repo folder that does not exist is not checked out: it is left out of the listing,
and ``not_checked_out`` names it for the caller's warning.

It lives in ``hub_git`` so ``cli`` (``hub search``, ``hub mcp``) and ``api`` share one walk
(AGH-393 Q-1). Git runs through its own small child runner, not ``GitRunner``: an error names
git's last stderr line, which ``GitRunner`` does not keep.
"""

import errno
import os
import signal
import stat
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import IO, Final, NamedTuple, Self

from agent_hub.core.brain.brain_path import BRAIN_FOLDER
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.knowledge import document_rules
from agent_hub.core.knowledge.document_rules import (
    NOT_REGULAR,
    NOT_UTF8,
    THROUGH_LINK,
    TOO_LARGE,
    UNREADABLE,
    is_indexed_name,
)
from agent_hub.core.knowledge.knowledge_index import Fingerprint
from agent_hub.core.knowledge.sync_knowledge import KnowledgeCheckoutError
from agent_hub.core.knowledge.sync_plan import ListedFile
from agent_hub.core.regular_files import NOT_REGULAR as READER_NOT_REGULAR
from agent_hub.core.regular_files import read_regular
from agent_hub.hub_git.git_runner import GIT_LOCATION_VARIABLES

GIT_TIMEOUT_SECONDS: Final = 30.0
# Of git's last stderr line, an error shows at most this many characters.
MAX_GIT_MESSAGE_CHARS: Final = 200
# Of git's stderr, only the end is read back: the last line is all an error shows.
_STDERR_TAIL_BYTES: Final = 4096
_DOCS_FOLDER: Final = "docs"
_LIST_ARGUMENTS: Final = ("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--")
_CEILING_VARIABLE: Final = "GIT_CEILING_DIRECTORIES"
_FOLDER_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class _Source(NamedTuple):
    """One source: the folder git runs in, the folder listed in it, and the prefix that makes
    a listed path hub-relative."""

    cwd: Path
    folder: str
    prefix: str

    @property
    def label(self) -> str:
        """The source as an error names it: ``brain`` or ``<dir>/docs``."""
        return self.prefix + self.folder


class GitKnowledgeCheckout:
    """A ``KnowledgeCheckout`` over the hub's main checkout ``checkout`` and the repos
    ``repo_dirs`` beside it, listed with the absolute ``git`` run with ``environ``."""

    def __init__(
        self, checkout: Path, repo_dirs: Sequence[str], *, git: str, environ: Mapping[str, str]
    ) -> None:
        self._checkout = checkout
        self._repo_dirs = tuple(repo_dirs)
        self._git = git
        self._environ = dict(environ)

    def not_checked_out(self) -> tuple[str, ...]:
        """The repo folders that do not exist beside the hub, in ``repo_dirs`` order."""
        return tuple(name for name in self._repo_dirs if not self._repo_exists(name))

    def listed(self) -> tuple[ListedFile, ...]:
        """Every Markdown file under the sources, by hub-relative path, sorted, each once.

        ``KnowledgeCheckoutError`` naming the source when git cannot list it, and before any
        file is looked at when the listing holds more than ``MAX_LISTED_FILES`` names (AM-1).
        """
        names = [name for source in self._sources() for name in self._names(source)]
        cap = document_rules.MAX_LISTED_FILES
        if len(names) > cap:
            msg = f"{len(names)} Markdown files under the hub's sources, more than {cap}; "
            raise KnowledgeCheckoutError(msg + "nothing was indexed")
        found = {file.path: file for file in self._walk(names)}
        return tuple(found[path] for path in sorted(found))

    def read(self, path: str) -> bytes | str | None:
        """The file's first ``MAX_DOCUMENT_BYTES + 1`` bytes, read without following a link on
        any segment below the source's folder; the skip reason when it cannot be read as a
        regular file (``cannot be read`` when the open or the read fails, AM-2); None when it is
        gone, or ``path`` is not under a source."""
        located = self._locate(path)
        if located is None:
            return None
        root, entry = located
        segments = entry.split(b"/")
        try:
            chain = _FolderChain.open(root)
        except FileNotFoundError:
            return None
        except OSError:
            return UNREADABLE
        with chain:
            folder = chain.folder(segments[:-1])
            if not isinstance(folder, int):
                return folder
            return _read_file(folder, segments[-1])

    def _repo_exists(self, name: str) -> bool:
        return os.path.lexists(self._checkout.parent / name)

    def _sources(self) -> Iterator[_Source]:
        yield _Source(cwd=self._checkout, folder=BRAIN_FOLDER, prefix="")
        for name in self._repo_dirs:
            if self._repo_exists(name):
                yield _Source(
                    cwd=self._checkout.parent / name, folder=_DOCS_FOLDER, prefix=f"{name}/"
                )

    def _names(self, source: _Source) -> Iterator[tuple[_Source, bytes, str]]:
        """Each listed name under ``source`` the index looks at: as git printed it (relative
        to the source's cwd) and as a hub-relative path, in the order of the printed names.

        Splitting the output still builds every printed name; names the index never looks at
        are then dropped, so what is kept past the scan grows with the Markdown names only. A
        name that is not UTF-8 is shown with its bytes escaped; when a UTF-8 name reads the
        same, that one is kept, whichever git printed first.
        """
        chosen: dict[str, bytes] = {}
        for entry in self._list(source).split(b"\0"):
            # ``dir/`` is an untracked nested repository: never listed or walked.
            if not entry or entry.endswith(b"/"):
                continue
            path = source.prefix + entry.decode("utf-8", "backslashreplace")
            kept = chosen.get(path)
            if is_indexed_name(path) and (kept is None or not _is_utf8(kept)):
                chosen[path] = entry
        for path, entry in sorted(chosen.items(), key=lambda item: item[1]):
            yield source, entry, path

    def _list(self, source: _Source) -> bytes:
        limit = document_rules.MAX_LISTING_BYTES
        env = _git_env(self._environ)
        env[_CEILING_VARIABLE] = str(source.cwd.parent)
        try:
            result = _list_child(
                [self._git, "-c", "core.fsmonitor=false", *_LIST_ARGUMENTS, source.folder],
                cwd=source.cwd,
                env=env,
                timeout=GIT_TIMEOUT_SECONDS,
                limit=limit,
            )
        except subprocess.TimeoutExpired as error:
            msg = f"{source.label}: {self._git} timed out after {GIT_TIMEOUT_SECONDS:g} s"
            raise KnowledgeCheckoutError(msg) from error
        except OSError as error:
            msg = f"{source.label}: git could not run: {error.strerror or error}"
            raise KnowledgeCheckoutError(msg) from error
        if result.returncode != 0:
            said = [line for line in result.stderr.decode("utf-8", "replace").splitlines() if line]
            last = said[-1][:MAX_GIT_MESSAGE_CHARS] if said else ""
            msg = f"{source.label}: git exited with {result.returncode}: {one_line(last)}"
            raise KnowledgeCheckoutError(msg.removesuffix(": "))
        if len(result.stdout) > limit:
            msg = f"{source.label}: git listed more than {limit} bytes; nothing was indexed"
            raise KnowledgeCheckoutError(msg)
        return result.stdout

    def _locate(self, path: str) -> tuple[Path, bytes] | None:
        """The source root a hub-relative ``path`` lies in, and the path below that root."""
        sources = [(self._checkout, f"{BRAIN_FOLDER}/", "")]
        sources += [
            (self._checkout.parent / name, f"{name}/{_DOCS_FOLDER}/", f"{name}/")
            for name in self._repo_dirs
        ]
        for root, folder, prefix in sources:
            if path.startswith(folder):
                entry = path.removeprefix(prefix).encode("utf-8", "surrogateescape")
                return (root, entry) if _is_plain(entry) else None
        return None

    def _walk(self, names: Sequence[tuple[_Source, bytes, str]]) -> Iterator[ListedFile]:
        """Each listed name as ``lstat`` sees it, one source's folder chain open at a time."""
        by_source: dict[_Source, list[tuple[bytes, str]]] = {}
        for source, entry, path in names:
            by_source.setdefault(source, []).append((entry, path))
        for source, entries in by_source.items():
            try:
                chain = _FolderChain.open(source.cwd)
            except OSError as error:
                msg = f"{source.label}: the folder cannot be opened: {error.strerror or error}"
                raise KnowledgeCheckoutError(msg) from error
            with chain:
                for entry, path in entries:
                    found = _listed_file(chain, entry, path)
                    if found is not None:
                        yield found


class _ChildResult(NamedTuple):
    """What a finished git left: its exit code, the start of stdout and the end of stderr."""

    returncode: int
    stdout: bytes
    stderr: bytes


def _git_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The caller's environment without git's location variables, so the cwd names the repo,
    and with no optional lock, so a listing never contends with the user's own git."""
    env = {name: value for name, value in environ.items() if name not in GIT_LOCATION_VARIABLES}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _list_child(
    argv: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float, limit: int
) -> _ChildResult:
    """Run ``argv`` (never a shell) in its own session with an empty stdin, both streams to
    temporary files; at most ``limit + 1`` bytes of stdout and the last few KiB of stderr are
    read back. Past ``timeout`` the whole process group is killed and ``TimeoutExpired`` raised;
    ``OSError`` when git cannot start."""
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        with subprocess.Popen(  # noqa: S603 - an argv list, never a shell; the caller's git
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        ) as child:
            try:
                child.wait(timeout=timeout)
            except BaseException:
                # A timeout or an interruption: git and anything it started go with it.
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                raise
        stdout.seek(0)
        return _ChildResult(child.returncode, stdout.read(limit + 1), _tail(stderr))


def _tail(file: IO[bytes]) -> bytes:
    size = file.seek(0, os.SEEK_END)
    file.seek(max(0, size - _STDERR_TAIL_BYTES))
    return file.read()


def _is_utf8(entry: bytes) -> bool:
    try:
        entry.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _is_plain(entry: bytes) -> bool:
    """Whether ``entry`` is a relative path that stays below its root (no empty, ``.`` or
    ``..`` segment)."""
    return all(segment not in {b"", b".", b".."} for segment in entry.split(b"/"))


def _listed_file(chain: _FolderChain, entry: bytes, path: str) -> ListedFile | None:
    """``entry`` as listed: its fingerprint, and why the listing already rules it out; None
    when it is gone since git listed it."""
    segments = entry.split(b"/")
    folder = chain.folder(segments[:-1])
    if not isinstance(folder, int):
        return None if folder is None else ListedFile(path=path, skip_reason=folder)
    try:
        status = os.stat(segments[-1], dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        return ListedFile(path=path, skip_reason=UNREADABLE)
    fingerprint = Fingerprint(size=status.st_size, mtime_ns=status.st_mtime_ns)
    return ListedFile(path=path, fingerprint=fingerprint, skip_reason=_skip_reason(entry, status))


def _skip_reason(entry: bytes, status: os.stat_result) -> str | None:
    """Why the file ``lstat`` described is not read, or None to read it."""
    if not _is_utf8(entry):
        return NOT_UTF8
    if stat.S_ISLNK(status.st_mode):
        return THROUGH_LINK
    if not stat.S_ISREG(status.st_mode):
        return NOT_REGULAR
    if status.st_size > document_rules.MAX_DOCUMENT_BYTES:
        return TOO_LARGE
    return None


def _read_file(folder: int, name: bytes) -> bytes | str | None:
    try:
        content = read_regular(
            folder, os.fsdecode(name), limit=document_rules.MAX_DOCUMENT_BYTES + 1
        )
    except FileNotFoundError:
        return None
    except OSError:
        return UNREADABLE
    if isinstance(content, str):
        # The shared reader names any other failure by its message: here, a read that failed.
        return NOT_REGULAR if content == READER_NOT_REGULAR else UNREADABLE
    return content


class _FolderChain:
    """The folders of the current path, opened one segment at a time from a source's root with
    ``O_NOFOLLOW``, each relative to its parent's descriptor. Only the current chain stays open:
    names come sorted, so each folder opens once.

    A folder is its descriptor, the skip reason of the files below it (reached through a link,
    or cannot be read), or None when it is gone.
    """

    def __init__(self, root: int) -> None:
        self._root = root
        self._open: list[tuple[bytes, int | str | None]] = []

    @classmethod
    def open(cls, root: Path) -> Self:
        """The chain from ``root``, which is followed (it is the source's checkout); ``OSError``
        when it cannot be opened. Closed, root included, on leaving its ``with`` block."""
        return cls(os.open(root, _FOLDER_FLAGS & ~os.O_NOFOLLOW))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._close_from(0)
        os.close(self._root)

    def folder(self, segments: Sequence[bytes]) -> int | str | None:
        """The folder ``segments`` names below the root."""
        kept = 0
        while kept < min(len(self._open), len(segments)) and self._open[kept][0] == segments[kept]:
            found = self._open[kept][1]
            if not isinstance(found, int):
                return found
            kept += 1
        self._close_from(kept)
        folder: int | str | None = self._root if kept == 0 else self._open[kept - 1][1]
        for segment in segments[kept:]:
            if not isinstance(folder, int):
                break
            folder = _open_folder(folder, segment)
            self._open.append((segment, folder))
        return folder

    def _close_from(self, kept: int) -> None:
        for _, folder in self._open[kept:]:
            if isinstance(folder, int):
                os.close(folder)
        del self._open[kept:]


def _open_folder(parent: int, name: bytes) -> int | str | None:
    try:
        return os.open(name, _FOLDER_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            return _not_a_folder(parent, name)
        return UNREADABLE


def _not_a_folder(parent: int, name: bytes) -> str | None:
    """Why ``name`` could not be opened as a folder: a link, or gone (a file stands there now)."""
    try:
        status = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        return UNREADABLE
    return THROUGH_LINK if stat.S_ISLNK(status.st_mode) else None
