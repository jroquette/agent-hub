"""The generator's file adapter on real trees under ``tmp_path``: reading and writing a hub tree.

The reader lists what a target folder holds without following a link, opening only the regular
files the render wants (AC-12.17, AC-12.18, AC-12.21). A test that meets a FIFO or a socket runs
under a ``signal.alarm`` guard, so a reader that opened one fails the test instead of hanging it.
The writer goes through a temp file in the final folder and ``os.replace``, re-checking every
ancestor at write time (AC-12.17 to AC-12.20). A test that sets the umask restores it.
"""

import contextlib
import errno
import hashlib
import os
import shutil
import signal
import socket
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

import pytest

from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite
from agent_hub.core.hub_files.tree_snapshot import (
    TEMP_NAME,
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeSnapshot,
)
from agent_hub.generator.errors import (
    FileWriteError,
    GeneratorError,
    LinkOutsideHubError,
    SymlinkedAncestorError,
)
from agent_hub.generator.file_adapter import apply_writes, ensure_root, remove_leftovers
from agent_hub.generator.hub_tree import read_hub_tree

# A reader blocked on a FIFO has hung: no read of a small tree takes this long.
HANG_SECONDS = 5


class HungError(Exception):
    """The alarm fired: the code under test blocked."""


@contextlib.contextmanager
def alarm_guard(seconds: int) -> Iterator[None]:
    """Fail with ``HungError`` if the block runs longer than ``seconds``."""

    def fire(signum: int, frame: FrameType | None) -> None:
        raise HungError

    previous = signal.signal(signal.SIGALRM, fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def write_file(path: Path, content: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def tree_digest(folder: Path) -> str:
    """A hash of every path, kind, mode, link target and file content under ``folder``."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        info = path.lstat()
        digest.update(f"{path.relative_to(folder)}\0{info.st_mode:o}\0".encode())
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def outside_folder(tmp_path: Path) -> Path:
    """A folder next to the root, holding files a reader must never list."""
    outside = tmp_path / "outside"
    write_file(outside / "x.md", b"outside\n")
    write_file(outside / "agents" / "y.md", b"outside agent\n", mode=0o755)
    return outside


def test_reads_files_links_and_folders_when_tree_read(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "AGENTS.md", b"# agents\r\n")
    write_file(root / "scripts" / "run.sh", b"#!/bin/sh\n", mode=0o755)
    write_file(root / "scripts" / "notes.txt", b"not wanted\n", mode=0o700)
    (root / "empty").mkdir()
    (root / "link.md").symlink_to("AGENTS.md")

    snapshot = read_hub_tree(root, wanted={"AGENTS.md", "scripts/run.sh", "link.md", "empty"})

    assert snapshot == TreeSnapshot(
        entries={
            "AGENTS.md": FileEntry(executable=False, content=b"# agents\r\n"),
            "empty": FolderEntry(),
            "link.md": LinkEntry(target="AGENTS.md", outside=False),
            "scripts": FolderEntry(),
            "scripts/notes.txt": FileEntry(executable=True, content=None),
            "scripts/run.sh": FileEntry(executable=True, content=b"#!/bin/sh\n"),
        },
        git_present=False,
    )


@pytest.mark.parametrize("kind", ["folder", "file"])
def test_skips_git_when_tree_read(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    write_file(root / "README.md", b"readme\n")
    if kind == "folder":
        write_file(root / ".git" / "HEAD", b"ref: refs/heads/main\n")
        (root / ".git" / "objects").mkdir()
    else:
        write_file(root / ".git", b"gitdir: ../elsewhere/.git\n")

    # Only the root's own ``.git`` is left out: one deeper is an ordinary entry.
    write_file(root / "vendor" / ".git", b"gitdir: ../../elsewhere/.git\n")

    snapshot = read_hub_tree(root, wanted={".git", ".git/HEAD", "README.md"})

    assert snapshot.entries == {
        "README.md": FileEntry(executable=False, content=b"readme\n"),
        "vendor": FolderEntry(),
        "vendor/.git": FileEntry(executable=False, content=None),
    }
    assert snapshot.git_present is True


@pytest.mark.parametrize("linked", ["plugin", ".claude", "brain/journal"])
def test_stops_at_symlinked_folder_when_tree_read(tmp_path: Path, linked: str) -> None:
    outside = outside_folder(tmp_path)
    before = tree_digest(outside)
    root = tmp_path / "root"
    root.mkdir()
    (root / linked).parent.mkdir(parents=True, exist_ok=True)
    (root / linked).symlink_to(outside, target_is_directory=True)

    snapshot = read_hub_tree(root, wanted={f"{linked}/x.md", f"{linked}/agents/y.md"})

    listed = {path for path in snapshot.entries if path == linked or path.startswith(f"{linked}/")}
    assert listed == {linked}
    assert snapshot.entries[linked] == LinkEntry(target=str(outside), outside=True)
    assert tree_digest(outside) == before


def test_marks_link_outside_when_target_resolves_outside(tmp_path: Path) -> None:
    outside = outside_folder(tmp_path)
    root = tmp_path / "root"
    write_file(root / "plugin" / "p" / "agents" / "x.md", b"inside\n")
    (root / "brain").mkdir()
    (root / "brain" / "journal").symlink_to(outside, target_is_directory=True)
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    # Lexically the first two stay under the root; only the real path tells them apart.
    (agents / "inside.md").symlink_to("../../plugin/p/agents/x.md")
    (agents / "through.md").symlink_to("../../brain/journal/x.md")
    (agents / "upward.md").symlink_to("../../../outside/x.md")

    snapshot = read_hub_tree(root, wanted=set())

    assert {path: entry for path, entry in snapshot.entries.items() if "/agents/" in path} == {
        ".claude/agents/inside.md": LinkEntry(target="../../plugin/p/agents/x.md", outside=False),
        ".claude/agents/through.md": LinkEntry(target="../../brain/journal/x.md", outside=True),
        ".claude/agents/upward.md": LinkEntry(target="../../../outside/x.md", outside=True),
        "plugin/p/agents/x.md": FileEntry(executable=False, content=None),
    }


def test_reports_not_regular_when_fifo_or_socket_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    folder = root / "plugin"
    folder.mkdir(parents=True)
    os.mkfifo(folder / "fifo.md")
    # AF_UNIX paths are capped near 104-108 bytes, and tmp_path can exceed that: bind by a
    # relative name from inside the folder (E13).
    monkeypatch.chdir(folder)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind("socket.md")
        assert stat.S_ISSOCK((folder / "socket.md").lstat().st_mode)

        with alarm_guard(HANG_SECONDS):
            snapshot = read_hub_tree(root, wanted={"plugin/fifo.md", "plugin/socket.md"})

    assert snapshot.entries == {
        "plugin": FolderEntry(),
        "plugin/fifo.md": OtherEntry(kind="fifo"),
        "plugin/socket.md": OtherEntry(kind="socket"),
    }


def test_returns_empty_snapshot_when_root_absent(tmp_path: Path) -> None:
    snapshot = read_hub_tree(tmp_path / "missing" / "root", wanted={"hub.json"})

    assert snapshot == TreeSnapshot(entries={}, git_present=False)


def test_raises_generator_error_when_root_is_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root, b"a file\n")

    with pytest.raises(GeneratorError, match=r"not a folder"):
        read_hub_tree(root, wanted=set())


def test_raises_generator_error_when_wanted_file_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    write_file(root / "hub.json", b"{}\n")

    real_open = os.open

    def refuse(path: str, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        # Only the file is refused: the walk opens folders with ``O_DIRECTORY``.
        if flags & os.O_DIRECTORY:
            return real_open(path, flags, mode, **kwargs)
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "open", refuse)

    with pytest.raises(GeneratorError, match=r"^hub\.json: Permission denied$"):
        read_hub_tree(root, wanted={"hub.json"})


def swap_before_open(
    monkeypatch: pytest.MonkeyPatch, swap: Callable[[str, int | None], None]
) -> None:
    """Run ``swap`` on the file the reader opens (name and ``dir_fd``), right before the real
    ``os.open``: a race. Folder opens (``O_DIRECTORY``) pass through."""
    real_open = os.open

    def swapped_open(path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if not flags & os.O_DIRECTORY:
            swap(path, dir_fd)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapped_open)


def test_reports_not_regular_when_file_swapped_for_fifo_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    write_file(root / "hub.json", b"{}\n")

    def to_fifo(path: str, dir_fd: int | None) -> None:
        os.unlink(path, dir_fd=dir_fd)
        os.mkfifo(path, dir_fd=dir_fd)

    swap_before_open(monkeypatch, to_fifo)

    with alarm_guard(HANG_SECONDS):
        snapshot = read_hub_tree(root, wanted={"hub.json"})

    assert snapshot.entries == {"hub.json": OtherEntry(kind="fifo")}


def test_raises_generator_error_when_file_swapped_for_link_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    root = tmp_path / "root"
    write_file(root / "hub.json", b"{}\n")

    def to_link(path: str, dir_fd: int | None) -> None:
        os.unlink(path, dir_fd=dir_fd)
        os.symlink(outside / "x.md", path, dir_fd=dir_fd)

    swap_before_open(monkeypatch, to_link)

    with pytest.raises(GeneratorError, match=r"^hub\.json: "):
        read_hub_tree(root, wanted={"hub.json"})


def test_marks_link_outside_when_target_is_sibling_prefix_or_parent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    # ``rootx`` shares the root's name as a prefix: only a path-wise check tells it apart.
    write_file(tmp_path / "rootx" / "x.md", b"sibling\n")
    (root / "sibling").symlink_to("../rootx", target_is_directory=True)
    (root / "sibling.md").symlink_to("../rootx/x.md")
    (root / "parent").symlink_to("..", target_is_directory=True)

    snapshot = read_hub_tree(root, wanted={"sibling/x.md", "sibling.md"})

    assert snapshot.entries == {
        "parent": LinkEntry(target="..", outside=True),
        "sibling": LinkEntry(target="../rootx", outside=True),
        "sibling.md": LinkEntry(target="../rootx/x.md", outside=True),
    }


def test_keeps_links_inside_when_root_reached_through_symlinked_folder(tmp_path: Path) -> None:
    real = tmp_path / "real"
    write_file(real / "root" / "plugin" / "x.md", b"inside\n")
    (real / "root" / "x.md").symlink_to("plugin/x.md")
    (real / "root" / "tools").symlink_to("plugin", target_is_directory=True)
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)

    snapshot = read_hub_tree(tmp_path / "alias" / "root", wanted={"plugin/x.md"})

    assert snapshot.entries == {
        "plugin": FolderEntry(),
        "plugin/x.md": FileEntry(executable=False, content=b"inside\n"),
        "tools": LinkEntry(target="plugin", outside=False),
        "x.md": LinkEntry(target="plugin/x.md", outside=False),
    }


def after_root_listing(monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> None:
    """Run ``action`` once, as soon as the reader has listed the root (the first listing)."""
    real_scandir = os.scandir
    pending = [action]

    @contextlib.contextmanager
    def listing(path: Any) -> Iterator[Any]:
        with real_scandir(path) as found:
            yield found
        if pending:
            pending.pop()()

    monkeypatch.setattr(os, "scandir", listing)


def before_plugin_descent(monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> None:
    """Run ``action`` once, right before the reader opens or lists the folder ``plugin``."""
    real_open, real_scandir = os.open, os.scandir
    pending = [action]

    def fire() -> None:
        if pending:
            pending.pop()()

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if flags & os.O_DIRECTORY and os.fspath(path) == "plugin":
            fire()
        return real_open(path, flags, mode, **kwargs)

    def listed(path: Any) -> Any:
        # A reader that lists by path (not by descriptor) meets the swap here.
        if isinstance(path, str) and path.endswith(f"{os.sep}plugin"):
            fire()
        return real_scandir(path)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "scandir", listed)


def before_first_file_open(monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> None:
    """Run ``action`` once, right before the reader opens its first file."""
    real_open = os.open
    pending = [action]

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if pending and not flags & os.O_DIRECTORY:
            pending.pop()()
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", opened)


def test_reads_no_outside_bytes_when_parent_swapped_after_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    root = tmp_path / "root"
    write_file(root / "plugin" / "x.md", b"inside\n")
    # ``plugin`` was a folder when the root was listed; it is a link when the walk reaches it.
    after_root_listing(monkeypatch, lambda: swap_for_link(root, outside))

    snapshot = read_hub_tree(root, wanted={"plugin/x.md", "plugin/agents/y.md"})

    assert snapshot.entries == {"plugin": LinkEntry(target=str(outside), outside=True)}


def test_raises_generator_error_when_parent_swapped_before_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    root = tmp_path / "root"
    write_file(root / "plugin" / "x.md", b"inside\n")
    # ``plugin`` was a folder when it was looked at; it is a link when the walk opens it.
    before_plugin_descent(monkeypatch, lambda: swap_for_link(root, outside))

    with pytest.raises(GeneratorError, match=r"^plugin: "):
        read_hub_tree(root, wanted={"plugin/x.md", "plugin/agents/y.md"})


def test_reads_held_folder_when_parent_swapped_before_file_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    root = tmp_path / "root"
    write_file(root / "plugin" / "x.md", b"inside\n")
    write_file(root / "plugin" / "agents" / "y.md", b"inside agent\n")
    # The swap comes after ``plugin`` was opened: the reader follows the descriptor it holds.
    before_first_file_open(monkeypatch, lambda: swap_for_link(root, outside))

    snapshot = read_hub_tree(root, wanted={"plugin/x.md", "plugin/agents/y.md"})

    assert snapshot.entries == {
        "plugin": FolderEntry(),
        "plugin/agents": FolderEntry(),
        "plugin/agents/y.md": FileEntry(executable=False, content=b"inside agent\n"),
        "plugin/x.md": FileEntry(executable=False, content=b"inside\n"),
    }


def test_raises_generator_error_when_root_cannot_be_looked_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    real_lstat = os.lstat

    def refuse(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        if os.fspath(path) == os.fspath(root):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", refuse)

    # A root that cannot be looked at is not an absent root.
    with pytest.raises(GeneratorError) as raised:
        read_hub_tree(root, wanted=set())

    assert str(raised.value) == f"{root}: {os.strerror(errno.EACCES)}"


def refuse_second_listing(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """The root lists; the next folder cannot be read."""
    real_scandir = os.scandir
    calls: list[Any] = []

    def listed(path: Any) -> Any:
        calls.append(path)
        if len(calls) > 1:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", listed)


def remove_after_listing(monkeypatch: pytest.MonkeyPatch, root: Path, name: str) -> None:
    """Remove ``root/name`` once the root was listed, before the walk looks at it."""

    def remove() -> None:
        if (root / name).is_dir():
            shutil.rmtree(root / name)
        else:
            (root / name).unlink()

    after_root_listing(monkeypatch, remove)


def refuse_readlink(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    def refuse(*args: Any, **kwargs: Any) -> str:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(os, "readlink", refuse)


WALK_FAILURES = [
    pytest.param(
        refuse_second_listing, f"plugin: {os.strerror(errno.EACCES)}", id="unreadable-folder"
    ),
    pytest.param(
        lambda m, root: remove_after_listing(m, root, "plugin"),
        f"plugin: {os.strerror(errno.ENOENT)}",
        id="folder-vanished",
    ),
    pytest.param(
        lambda m, root: remove_after_listing(m, root, "notes.txt"),
        f"notes.txt: {os.strerror(errno.ENOENT)}",
        id="entry-vanished",
    ),
    pytest.param(refuse_readlink, f"link.md: {os.strerror(errno.EIO)}", id="unreadable-link"),
]


@pytest.mark.parametrize(("fail", "message"), WALK_FAILURES)
def test_raises_generator_error_naming_path_when_walk_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: Callable[[pytest.MonkeyPatch, Path], None],
    message: str,
) -> None:
    root = tmp_path / "root"
    write_file(root / "plugin" / "x.md", b"inside\n")
    write_file(root / "notes.txt", b"not wanted\n")
    (root / "link.md").symlink_to("notes.txt")
    fail(monkeypatch, root)

    with pytest.raises(GeneratorError) as raised:
        read_hub_tree(root, wanted={"plugin/x.md"})

    assert str(raised.value) == message


@pytest.fixture
def set_umask() -> Iterator[Callable[[int], None]]:
    """Set the process umask for the test; the original one is restored afterwards."""
    original = os.umask(0o022)
    os.umask(original)
    try:
        yield lambda mask: os.umask(mask) and None
    finally:
        os.umask(original)


def temp_entries(root: Path) -> list[str]:
    """Every entry under ``root`` whose name has the temp-file shape."""
    return sorted(
        str(path.relative_to(root)) for path in root.rglob("*") if TEMP_NAME.fullmatch(path.name)
    )


def a_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    ensure_root(root)
    return root


@pytest.mark.parametrize("mask", [0o022, 0o077], ids=["umask-022", "umask-077"])
def test_writes_bytes_and_mode_when_file_applied(
    tmp_path: Path, set_umask: Callable[[int], None], mask: int
) -> None:
    root = a_root(tmp_path)
    set_umask(mask)
    writes = [
        FileWrite(path="AGENTS.md", content=b"# Rules\r\n\xc3\xa9\n", executable=False),
        FileWrite(path="scripts/run.py", content=b"#!/usr/bin/env python3\n", executable=True),
    ]

    apply_writes(root, folders=["scripts"], writes=writes)

    for write in writes:
        info = (root / write.path).lstat()
        assert stat.S_ISREG(info.st_mode), write.path
        assert (root / write.path).read_bytes() == write.content
        assert bool(info.st_mode & stat.S_IXUSR) is write.executable
        wanted = (0o777 if write.executable else 0o666) & ~mask
        assert stat.S_IMODE(info.st_mode) == wanted, write.path


def test_writes_link_when_link_applied(tmp_path: Path) -> None:
    root = a_root(tmp_path)
    writes = [
        FileWrite(path="plugin/agents/x.md", content=b"agent\n", executable=False),
        LinkWrite(path=".claude/agents/x.md", target="../../plugin/agents/x.md"),
    ]

    apply_writes(
        root, folders=[".claude", ".claude/agents", "plugin", "plugin/agents"], writes=writes
    )

    link = root / ".claude" / "agents" / "x.md"
    assert link.is_symlink()
    assert os.readlink(link) == "../../plugin/agents/x.md"
    assert link.read_bytes() == b"agent\n"


def test_creates_root_with_parents_when_root_absent(tmp_path: Path) -> None:
    root = tmp_path / "a" / "b" / "root"

    ensure_root(root)
    ensure_root(root)

    assert root.is_dir()


def test_raises_file_write_error_when_root_cannot_be_made(tmp_path: Path) -> None:
    write_file(tmp_path / "file", b"x\n")

    with pytest.raises(FileWriteError) as raised:
        ensure_root(tmp_path / "file" / "root")

    assert raised.value.path == str(tmp_path / "file" / "root")
    assert raised.value.cause == os.strerror(errno.ENOTDIR)


PLANTED_CASES = [
    pytest.param({"folders": ["plugin/agents"], "writes": []}, "plugin/agents", id="folder"),
    pytest.param(
        {"folders": [], "writes": [FileWrite(path="plugin/x.md", content=b"x\n", executable=True)]},
        "plugin/x.md",
        id="file",
    ),
    pytest.param(
        {
            "folders": [],
            "writes": [FileWrite(path="plugin/agents/z.md", content=b"z\n", executable=False)],
        },
        "plugin/agents/z.md",
        id="nested-file",
    ),
    pytest.param(
        {"folders": [], "writes": [LinkWrite(path="plugin/y.md", target="x.md")]},
        "plugin/y.md",
        id="link",
    ),
]


@pytest.mark.parametrize(("plan", "path"), PLANTED_CASES)
def test_refuses_write_when_ancestor_planted_after_plan(
    tmp_path: Path, plan: dict[str, Any], path: str
) -> None:
    outside = outside_folder(tmp_path)
    before = tree_digest(outside)
    root = a_root(tmp_path)
    (root / "plugin").mkdir()
    # The plan was made while ``plugin`` was a folder; it becomes a link before the write.
    (root / "plugin").rmdir()
    (root / "plugin").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SymlinkedAncestorError) as raised:
        apply_writes(root, **plan)

    assert (raised.value.path, raised.value.ancestor) == (path, "plugin")
    assert str(raised.value) == f"{path}: symlinked ancestor plugin"
    assert tree_digest(outside) == before
    assert sorted(p.name for p in root.iterdir()) == ["plugin"]


def test_names_cause_when_ancestor_is_file_at_write_time(tmp_path: Path) -> None:
    root = a_root(tmp_path)
    write_file(root / "plugin", b"a file\n")

    with pytest.raises(FileWriteError) as raised:
        apply_writes(
            root,
            folders=[],
            writes=[FileWrite(path="plugin/x.md", content=b"x\n", executable=False)],
        )

    assert (raised.value.path, raised.value.cause) == ("plugin/x.md", os.strerror(errno.ENOTDIR))


def test_names_cause_when_planned_folder_already_exists(tmp_path: Path) -> None:
    root = a_root(tmp_path)
    (root / "plugin").mkdir()

    with pytest.raises(FileWriteError) as raised:
        apply_writes(root, folders=["plugin"], writes=[])

    assert (raised.value.path, raised.value.cause) == ("plugin", os.strerror(errno.EEXIST))


def test_refuses_leftover_removal_when_ancestor_planted_after_plan(tmp_path: Path) -> None:
    outside = outside_folder(tmp_path)
    write_file(outside / ".x.md.hub-tmp-0a1b2c3d", b"outside\n")
    before = tree_digest(outside)
    root = a_root(tmp_path)
    (root / "plugin").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SymlinkedAncestorError, match=r"symlinked ancestor plugin$"):
        remove_leftovers(root, ["plugin/.x.md.hub-tmp-0a1b2c3d"])

    assert tree_digest(outside) == before


def test_refuses_link_when_target_resolves_outside(tmp_path: Path) -> None:
    outside = outside_folder(tmp_path)
    root = a_root(tmp_path)
    (root / ".claude" / "agents").mkdir(parents=True)
    # Lexically the target stays in the root; its folder's ancestor ``plugin`` leaves it.
    (root / "plugin").symlink_to(outside, target_is_directory=True)
    write = LinkWrite(path=".claude/agents/y.md", target="../../plugin/agents/y.md")

    with pytest.raises(LinkOutsideHubError) as raised:
        apply_writes(root, folders=[], writes=[write])

    assert raised.value.path == ".claude/agents/y.md"
    assert str(raised.value) == ".claude/agents/y.md: resolves outside the hub"
    assert list((root / ".claude" / "agents").iterdir()) == []


type FolderId = tuple[int, int]


def folder_id(folder: Path | int) -> FolderId:
    """The device and inode of a folder, by path or by open descriptor."""
    info = os.fstat(folder) if isinstance(folder, int) else folder.stat()
    return (info.st_dev, info.st_ino)


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Any, ...]
    # Which folder each ``*dir_fd`` argument named, taken at call time.
    folders: dict[str, FolderId]


class Recorder:
    """Wraps ``os`` calls of the writer and records them, in order, before calling through."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, fail_at: str | None = None) -> None:
        self.calls: list[Call] = []
        self.fail_at = fail_at
        for name in ("open", "symlink", "fchmod", "replace"):
            monkeypatch.setattr(os, name, self._wrap(name, getattr(os, name)))

    def _wrap(self, name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            folders = {
                key: folder_id(value)
                for key, value in kwargs.items()
                if key.endswith("dir_fd") and value is not None
            }
            self.calls.append(Call(name, args, folders))
            if name == self.fail_at:
                raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
            return real(*args, **kwargs)

        return recorded

    def writes(self) -> list[Call]:
        """Every recorded call except the folder opens of the descent."""
        return [c for c in self.calls if c.name != "open" or c.args[1] & os.O_CREAT]


def test_supports_descriptor_calls_when_platform_checked() -> None:
    # ``os.replace`` takes ``src_dir_fd``/``dst_dir_fd`` through ``renameat``, as ``os.rename``.
    used = {os.open, os.mkdir, os.symlink, os.rename, os.unlink, os.stat}

    assert used <= os.supports_dir_fd
    assert os.stat in os.supports_follow_symlinks


def test_uses_temp_in_same_folder_when_writing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, set_umask: Callable[[int], None]
) -> None:
    root = a_root(tmp_path)
    (root / "scripts").mkdir()
    folder = folder_id(root / "scripts")
    set_umask(0o022)
    recorder = Recorder(monkeypatch)

    apply_writes(
        root,
        folders=[],
        writes=[FileWrite(path="scripts/run.py", content=b"#!\n", executable=True)],
    )

    opened, mode_set, replaced = recorder.writes()
    temp, flags, mode = opened.args
    assert (opened.name, mode_set.name, replaced.name) == ("open", "fchmod", "replace")
    assert TEMP_NAME.fullmatch(temp)
    assert temp.startswith(".run.py.hub-tmp-")
    wanted_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    assert flags & wanted_flags == wanted_flags
    assert mode == 0o600
    assert opened.folders == {"dir_fd": folder}
    assert mode_set.args[1] == 0o755
    assert replaced.args == (temp, "run.py")
    assert replaced.folders == {"src_dir_fd": folder, "dst_dir_fd": folder}
    # The descent opens the root, then each folder, never following a link.
    descent = [c for c in recorder.calls if c.name == "open" and c not in recorder.writes()]
    assert len(descent) == 2
    assert all(c.args[1] & os.O_NOFOLLOW for c in descent)


def test_uses_temp_in_same_folder_when_writing_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_root(tmp_path)
    (root / "scripts").mkdir()
    folder = folder_id(root / "scripts")
    recorder = Recorder(monkeypatch)

    apply_writes(root, folders=[], writes=[LinkWrite(path="scripts/run", target="run.py")])

    linked, replaced = recorder.writes()
    target, temp = linked.args
    assert (linked.name, target) == ("symlink", "run.py")
    assert TEMP_NAME.fullmatch(temp)
    assert temp.startswith(".run.hub-tmp-")
    assert linked.folders == {"dir_fd": folder}
    assert (replaced.name, replaced.args) == ("replace", (temp, "run"))
    assert replaced.folders == {"src_dir_fd": folder, "dst_dir_fd": folder}


def swap_for_link(root: Path, outside: Path) -> None:
    """Move ``root/plugin`` aside and put a link to ``outside`` in its place."""
    (root / "plugin").rename(root / "moved")
    (root / "plugin").symlink_to(outside, target_is_directory=True)


def swap_on_open(
    monkeypatch: pytest.MonkeyPatch, swap: Callable[[], None], *, creating: bool
) -> None:
    """Run ``swap`` once, right before the first ``os.open`` (or the first creating one)."""
    real_open = os.open
    pending = [swap]

    def swapped_open(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if pending and (flags & os.O_CREAT or not creating):
            pending.pop()()
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", swapped_open)


def test_refuses_write_when_ancestor_swapped_before_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    before = tree_digest(outside)
    root = a_root(tmp_path)
    (root / "plugin").mkdir()
    swap_on_open(monkeypatch, lambda: swap_for_link(root, outside), creating=False)

    with pytest.raises(GeneratorError, match=r"^plugin/x\.md: symlinked ancestor plugin$"):
        apply_writes(
            root,
            folders=[],
            writes=[FileWrite(path="plugin/x.md", content=b"x\n", executable=False)],
        )

    assert tree_digest(outside) == before
    assert list((root / "moved").iterdir()) == []


def test_writes_inside_when_ancestor_swapped_after_descent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = outside_folder(tmp_path)
    before = tree_digest(outside)
    root = a_root(tmp_path)
    (root / "plugin").mkdir()
    # The swap comes after the folder was opened: the write follows the descriptor it holds.
    swap_on_open(monkeypatch, lambda: swap_for_link(root, outside), creating=True)

    apply_writes(
        root, folders=[], writes=[FileWrite(path="plugin/x.md", content=b"x\n", executable=False)]
    )

    assert tree_digest(outside) == before
    assert sorted(p.name for p in (root / "moved").iterdir()) == ["x.md"]


@pytest.mark.parametrize(
    ("write", "fail_at"),
    [
        pytest.param(
            FileWrite(path="scripts/run.py", content=b"#!\n", executable=True),
            "fchmod",
            id="file-mode",
        ),
        pytest.param(
            FileWrite(path="scripts/run.py", content=b"#!\n", executable=True),
            "replace",
            id="file-replace",
        ),
        pytest.param(LinkWrite(path="scripts/run", target="run.py"), "replace", id="link-replace"),
    ],
)
def test_leaves_no_temp_when_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    write: FileWrite | LinkWrite,
    fail_at: str,
) -> None:
    root = a_root(tmp_path)
    (root / "scripts").mkdir()
    Recorder(monkeypatch, fail_at=fail_at)

    with pytest.raises(FileWriteError) as raised:
        apply_writes(root, folders=[], writes=[write])

    assert (raised.value.path, raised.value.cause) == (write.path, os.strerror(errno.ENOSPC))
    assert str(raised.value) == f"{write.path}: {os.strerror(errno.ENOSPC)}"
    assert list((root / "scripts").iterdir()) == []


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(FileWrite(path="scripts/run.py", content=b"#!\n", executable=True), id="file"),
        pytest.param(LinkWrite(path="scripts/run", target="run.py"), id="link"),
    ],
)
def test_reports_write_error_when_temp_cleanup_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: FileWrite | LinkWrite
) -> None:
    root = a_root(tmp_path)
    (root / "scripts").mkdir()
    Recorder(monkeypatch, fail_at="replace")

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES))

    monkeypatch.setattr(os, "unlink", refuse)

    with pytest.raises(FileWriteError) as raised:
        apply_writes(root, folders=[], writes=[write])

    # The write's own failure is the one reported; the cleanup's is a note naming the leftover.
    assert (raised.value.path, raised.value.cause) == (write.path, os.strerror(errno.ENOSPC))
    (left,) = temp_entries(root)
    assert raised.value.__notes__ == [f"{left}: not removed: {os.strerror(errno.EACCES)}"]


def test_leaves_no_temp_when_write_succeeds(tmp_path: Path) -> None:
    root = a_root(tmp_path)
    writes = [
        FileWrite(path="AGENTS.md", content=b"# Rules\n", executable=False),
        FileWrite(path="scripts/run.py", content=b"#!\n", executable=True),
        LinkWrite(path="scripts/run", target="run.py"),
    ]

    apply_writes(root, folders=["scripts"], writes=writes)

    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == [
        "AGENTS.md",
        "scripts",
        "scripts/run",
        "scripts/run.py",
    ]
    assert temp_entries(root) == []


def test_removes_leftovers_when_listed(tmp_path: Path) -> None:
    root = a_root(tmp_path)
    write_file(root / ".Makefile.hub-tmp-0a1b2c3d", b"half\n")
    write_file(root / "plugin" / "x.md", b"kept\n")
    (root / "plugin" / ".y.md.hub-tmp-ffffffff").symlink_to("x.md")

    remove_leftovers(root, [".Makefile.hub-tmp-0a1b2c3d", "plugin/.y.md.hub-tmp-ffffffff"])

    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == ["plugin", "plugin/x.md"]
    assert (root / "plugin" / "x.md").read_bytes() == b"kept\n"


def test_removes_link_itself_when_leftover_resolves_outside(tmp_path: Path) -> None:
    outside = outside_folder(tmp_path)
    before = tree_digest(outside)
    root = a_root(tmp_path)
    (root / ".x.md.hub-tmp-0a1b2c3d").symlink_to(outside / "x.md")
    (root / ".agents.hub-tmp-0a1b2c3d").symlink_to(outside / "agents", target_is_directory=True)

    remove_leftovers(root, [".agents.hub-tmp-0a1b2c3d", ".x.md.hub-tmp-0a1b2c3d"])

    assert list(root.iterdir()) == []
    assert tree_digest(outside) == before


def plant_folder(path: Path) -> None:
    path.mkdir()
    write_file(path / "x.md", b"inside\n")


def plant_fifo(path: Path) -> None:
    os.mkfifo(path)


@pytest.mark.parametrize("plant", [plant_folder, plant_fifo], ids=["folder", "fifo"])
def test_keeps_entry_when_leftover_no_longer_file_or_link(
    tmp_path: Path, plant: Callable[[Path], None]
) -> None:
    root = a_root(tmp_path)
    plant(root / ".x.md.hub-tmp-0a1b2c3d")
    before = tree_digest(root)

    with pytest.raises(FileWriteError) as raised:
        remove_leftovers(root, [".x.md.hub-tmp-0a1b2c3d"])

    assert raised.value.path == ".x.md.hub-tmp-0a1b2c3d"
    assert raised.value.cause == "not a leftover file or link"
    assert tree_digest(root) == before


@pytest.mark.parametrize("name", ["AGENTS.md", ".x.md.hub-tmp-0A1B2C3D", ".hub-tmp-0a1b2c3d"])
def test_raises_when_listed_path_not_leftover_shaped(tmp_path: Path, name: str) -> None:
    root = a_root(tmp_path)
    write_file(root / name, b"user file\n")

    with pytest.raises(ValueError, match=r"not a leftover name"):
        remove_leftovers(root, [name])

    assert (root / name).read_bytes() == b"user file\n"


def test_skips_leftover_when_already_gone(tmp_path: Path) -> None:
    root = a_root(tmp_path)

    remove_leftovers(root, [".x.md.hub-tmp-0a1b2c3d"])

    assert list(root.iterdir()) == []


def test_skips_absent_root_when_no_leftovers_listed(tmp_path: Path) -> None:
    # The cleanup runs before the root is made: with nothing listed, it does not open the root.
    remove_leftovers(tmp_path / "missing", [])

    assert list(tmp_path.iterdir()) == []


NOT_UNDER_ROOT = r"not a relative path inside the hub"
LEFTOVER = ".x.md.hub-tmp-0a1b2c3d"


# Paths the adapter must refuse, each shape once, built from ``tmp_path`` and the entry's name.
BAD_PATHS: dict[str, Callable[[Path, str], str]] = {
    "absolute": lambda tmp_path, name: str(tmp_path / "abs" / name),
    "empty": lambda tmp_path, name: "",
    "empty-segment": lambda tmp_path, name: f"plugin//{name}",
    "trailing-slash": lambda tmp_path, name: f"plugin/{name}/",
    "dot-first": lambda tmp_path, name: f"./{name}",
    "dot-inside": lambda tmp_path, name: f"plugin/./{name}",
    "dot-dot-first": lambda tmp_path, name: f"../{name}",
    "dot-dot-inside": lambda tmp_path, name: f"plugin/../../{name}",
    # The OS refuses a NUL only when the path reaches it, after the entries listed before it.
    "nul-name": lambda tmp_path, name: "a\x00b",
    "nul-folder": lambda tmp_path, name: f"a\x00b/{name}",
}


def apply_bad_folder(root: Path, path: str) -> None:
    apply_writes(root, folders=["ok", path], writes=[])


def apply_bad_file(root: Path, path: str) -> None:
    apply_writes(
        root,
        folders=["ok"],
        writes=[
            FileWrite(path="ok.md", content=b"ok\n", executable=False),
            FileWrite(path=path, content=b"x\n", executable=False),
        ],
    )


def apply_bad_link(root: Path, path: str) -> None:
    apply_writes(
        root,
        folders=["ok"],
        writes=[
            FileWrite(path="ok.md", content=b"ok\n", executable=False),
            LinkWrite(path=path, target="ok.md"),
        ],
    )


@pytest.mark.parametrize("shape", list(BAD_PATHS))
@pytest.mark.parametrize(
    "apply", [apply_bad_folder, apply_bad_file, apply_bad_link], ids=["folder", "file", "link"]
)
def test_raises_value_error_and_writes_nothing_when_path_not_under_root(
    tmp_path: Path, *, apply: Callable[[Path, str], None], shape: str
) -> None:
    root = a_root(tmp_path)
    (root / "plugin").mkdir()
    (tmp_path / "abs").mkdir()
    before = tree_digest(tmp_path)

    # Checked before anything is written: the valid entries listed first are not made either.
    with pytest.raises(ValueError, match=NOT_UNDER_ROOT):
        apply(root, BAD_PATHS[shape](tmp_path, "x.md"))

    assert tree_digest(tmp_path) == before


@pytest.mark.parametrize("shape", list(BAD_PATHS))
def test_raises_value_error_and_removes_nothing_when_leftover_not_under_root(
    tmp_path: Path, shape: str
) -> None:
    root = a_root(tmp_path)
    # A leftover-shaped file wherever each bad path could reach, and one the valid entry names.
    for folder in (root, root / "plugin", tmp_path, tmp_path / "abs"):
        write_file(folder / LEFTOVER, b"not the adapter's\n")
    before = tree_digest(tmp_path)

    with pytest.raises(ValueError, match=NOT_UNDER_ROOT):
        remove_leftovers(root, [LEFTOVER, BAD_PATHS[shape](tmp_path, LEFTOVER)])

    assert tree_digest(tmp_path) == before


PINNED_SUFFIX = "0a1b2c3d"


def pin_temp_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every temp name the writer draws end in ``PINNED_SUFFIX``."""
    monkeypatch.setattr(os, "urandom", lambda size: bytes.fromhex(PINNED_SUFFIX)[:size])


def plant_temp_file(path: Path) -> str:
    write_file(path, b"not the writer's\n")
    return "file"


def plant_temp_link(path: Path) -> str:
    path.symlink_to("somewhere-else")
    return "link"


def planted_state(path: Path) -> tuple[int, bytes | str]:
    info = path.lstat()
    held = os.readlink(path) if stat.S_ISLNK(info.st_mode) else path.read_bytes()
    return (stat.S_IFMT(info.st_mode), held)


@pytest.mark.parametrize("plant", [plant_temp_file, plant_temp_link], ids=["file", "link"])
@pytest.mark.parametrize(
    "write",
    [
        pytest.param(FileWrite(path="scripts/run.py", content=b"#!\n", executable=True), id="file"),
        pytest.param(LinkWrite(path="scripts/run", target="run.py"), id="link"),
    ],
)
def test_keeps_planted_entry_when_temp_name_taken(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    write: FileWrite | LinkWrite,
    plant: Callable[[Path], str],
) -> None:
    root = a_root(tmp_path)
    (root / "scripts").mkdir()
    name = write.path.rpartition("/")[2]
    temp = root / "scripts" / f".{name}.hub-tmp-{PINNED_SUFFIX}"
    plant(temp)
    before = planted_state(temp)
    pin_temp_token(monkeypatch)

    with pytest.raises(FileWriteError) as raised:
        apply_writes(root, folders=[], writes=[write])

    # The temp entry was not the writer's: it is left exactly as it was.
    assert (raised.value.path, raised.value.cause) == (write.path, os.strerror(errno.EEXIST))
    assert planted_state(temp) == before
    assert sorted(p.name for p in (root / "scripts").iterdir()) == [temp.name]


@pytest.mark.parametrize(
    ("folders", "write"),
    [
        pytest.param([], LinkWrite(path="x.md", target="../rootx/x.md"), id="top"),
        pytest.param(
            ["plugin"], LinkWrite(path="plugin/x.md", target="../../rootx/x.md"), id="nested"
        ),
    ],
)
def test_refuses_link_when_target_in_sibling_prefix_folder(
    tmp_path: Path, folders: list[str], write: LinkWrite
) -> None:
    root = a_root(tmp_path)
    # ``rootx`` shares the root's name as a prefix: only a path-wise check tells it apart.
    write_file(tmp_path / "rootx" / "x.md", b"sibling\n")
    before = tree_digest(tmp_path / "rootx")

    with pytest.raises(LinkOutsideHubError) as raised:
        apply_writes(root, folders=folders, writes=[write])

    assert raised.value.path == write.path
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == folders
    assert tree_digest(tmp_path / "rootx") == before


def test_writes_link_when_root_reached_through_symlinked_folder(tmp_path: Path) -> None:
    real = tmp_path / "real"
    ensure_root(real / "root")
    (tmp_path / "via").symlink_to(real, target_is_directory=True)
    writes = [
        FileWrite(path="plugin/x.md", content=b"inside\n", executable=False),
        LinkWrite(path=".claude/x.md", target="../plugin/x.md"),
    ]

    apply_writes(tmp_path / "via" / "root", folders=[".claude", "plugin"], writes=writes)

    link = real / "root" / ".claude" / "x.md"
    assert link.is_symlink()
    assert os.readlink(link) == "../plugin/x.md"
    assert link.read_bytes() == b"inside\n"


def swap_root(root: Path, moved: Path) -> None:
    """Move the root folder aside and put a new, empty folder at its path."""
    root.rename(moved)
    root.mkdir()


def after_first_call(
    monkeypatch: pytest.MonkeyPatch, name: str, action: Callable[[], None]
) -> None:
    """Run ``action`` once, right after the first ``os.<name>`` call returned."""
    real = getattr(os, name)
    pending = [action]

    def called(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        if pending:
            pending.pop()()
        return result

    monkeypatch.setattr(os, name, called)


def test_writes_into_held_root_when_root_swapped_between_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_root(tmp_path)
    moved = tmp_path / "moved"
    after_first_call(monkeypatch, "replace", lambda: swap_root(root, moved))
    writes = [
        FileWrite(path="AGENTS.md", content=b"# Rules\n", executable=False),
        FileWrite(path="scripts/run.py", content=b"#!\n", executable=True),
    ]

    apply_writes(root, folders=["scripts"], writes=writes)

    # Every write went to the folder opened at the start; nothing landed in the new one.
    assert list(root.iterdir()) == []
    assert sorted(str(p.relative_to(moved)) for p in moved.rglob("*")) == [
        "AGENTS.md",
        "scripts",
        "scripts/run.py",
    ]


def test_refuses_link_when_root_swapped_before_link_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_root(tmp_path)
    moved = tmp_path / "moved"
    after_first_call(monkeypatch, "replace", lambda: swap_root(root, moved))
    writes = [
        FileWrite(path="scripts/run.py", content=b"#!\n", executable=True),
        LinkWrite(path="scripts/run", target="run.py"),
    ]

    # The link's check reads the root by path, which now names another folder: it is refused.
    with pytest.raises(FileWriteError) as raised:
        apply_writes(root, folders=["scripts"], writes=writes)

    assert (raised.value.path, raised.value.cause) == ("scripts/run", "the hub folder moved")
    assert list(root.iterdir()) == []
    assert sorted(str(p.relative_to(moved)) for p in moved.rglob("*")) == [
        "scripts",
        "scripts/run.py",
    ]


def before_first_folder_open(monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]) -> None:
    """Run ``action`` once, right before the first folder open (``O_DIRECTORY``)."""
    real_open = os.open
    pending = [action]

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if pending and flags & os.O_DIRECTORY:
            pending.pop()()
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", opened)


def test_raises_when_root_moves_between_resolve_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    ensure_root(first / "root")
    ensure_root(second / "root")
    via = tmp_path / "via"
    via.symlink_to(first, target_is_directory=True)

    def retarget() -> None:
        via.unlink()
        via.symlink_to(second, target_is_directory=True)

    before_first_folder_open(monkeypatch, retarget)

    with pytest.raises(FileWriteError) as raised:
        apply_writes(
            via / "root",
            folders=[],
            writes=[FileWrite(path="AGENTS.md", content=b"# Rules\n", executable=False)],
        )

    assert (raised.value.path, raised.value.cause) == (str(via / "root"), "the hub folder moved")
    assert list((first / "root").iterdir()) == []
    assert list((second / "root").iterdir()) == []


def test_removes_from_held_root_when_root_swapped_between_leftovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = a_root(tmp_path)
    moved = tmp_path / "moved"
    names = [".a.md.hub-tmp-0a1b2c3d", ".b.md.hub-tmp-0a1b2c3d"]
    for name in names:
        write_file(root / name, b"half\n")

    def swap() -> None:
        swap_root(root, moved)
        # The new folder holds an entry of the same name: it is not the one listed.
        write_file(root / names[1], b"someone else's\n")

    after_first_call(monkeypatch, "unlink", swap)

    remove_leftovers(root, names)

    assert list(moved.iterdir()) == []
    assert (root / names[1]).read_bytes() == b"someone else's\n"


def open_descriptors() -> int:
    """How many descriptors the process holds (``/dev/fd`` lists them on Linux and macOS)."""
    return len(os.listdir("/dev/fd"))


def fail_descent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_writes(
        root, folders=[], writes=[FileWrite(path="missing/x.md", content=b"x\n", executable=False)]
    )


def fail_existing_folder(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "plugin").mkdir()
    apply_writes(root, folders=["plugin", "plugin/agents"], writes=[])


def fail_link_outside(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_writes(root, folders=["plugin"], writes=[LinkWrite(path="plugin/x.md", target="../..")])


def fail_symlinked_ancestor(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "plugin").symlink_to(root.parent, target_is_directory=True)
    apply_writes(
        root, folders=[], writes=[FileWrite(path="plugin/x.md", content=b"x\n", executable=False)]
    )


def fail_leftover_missing_folder(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remove_leftovers(root, [".x.md.hub-tmp-0a1b2c3d", "missing/.x.md.hub-tmp-0a1b2c3d"])


def fail_collision(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_file(root / f".x.md.hub-tmp-{PINNED_SUFFIX}", b"not the writer's\n")
    pin_temp_token(monkeypatch)
    apply_writes(
        root, folders=[], writes=[FileWrite(path="x.md", content=b"x\n", executable=False)]
    )


def fail_tree_read(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The nested folder is opened, then cannot be listed: the reader must still close it.
    write_file(root / "plugin" / "agents" / "x.md", b"inside\n")
    refuse_second_listing(monkeypatch, root)
    read_hub_tree(root, wanted={"plugin/agents/x.md"})


@pytest.mark.parametrize(
    "fail",
    [
        fail_descent,
        fail_existing_folder,
        fail_link_outside,
        fail_symlinked_ancestor,
        fail_leftover_missing_folder,
        fail_collision,
        fail_tree_read,
    ],
    ids=[
        "descent",
        "folder-exists",
        "link-outside",
        "symlinked",
        "leftover-descent",
        "collision",
        "tree-read",
    ],
)
def test_closes_every_descriptor_when_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: Callable[[Path, pytest.MonkeyPatch], None],
) -> None:
    root = a_root(tmp_path)
    before = open_descriptors()

    with pytest.raises(GeneratorError):
        fail(root, monkeypatch)

    assert open_descriptors() == before


def test_closes_every_descriptor_when_tree_read(tmp_path: Path) -> None:
    root = tmp_path / "root"
    write_file(root / "plugin" / "agents" / "x.md", b"agent\n", mode=0o755)
    write_file(root / "brain" / "journal" / "day.md", b"day\n")
    write_file(root / "AGENTS.md", b"rules\n")
    (root / "plugin" / "link.md").symlink_to("agents/x.md")
    before = open_descriptors()

    snapshot = read_hub_tree(root, wanted={"plugin/agents/x.md", "AGENTS.md"})

    assert snapshot.entries["plugin/agents/x.md"] == FileEntry(executable=True, content=b"agent\n")
    assert open_descriptors() == before
