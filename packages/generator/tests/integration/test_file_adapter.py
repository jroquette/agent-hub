"""The generator's file adapter on real trees under ``tmp_path``: reading a hub tree.

The reader lists what a target folder holds without following a link, opening only the regular
files the render wants (AC-12.17, AC-12.18, AC-12.21). A test that meets a FIFO or a socket runs
under a ``signal.alarm`` guard, so a reader that opened one fails the test instead of hanging it.
"""

import contextlib
import hashlib
import os
import signal
import socket
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from types import FrameType

import pytest

from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeSnapshot,
)
from agent_hub.generator.errors import GeneratorError
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

    def refuse(path: str, flags: int, mode: int = 0o777) -> int:
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(os, "open", refuse)

    with pytest.raises(GeneratorError, match=r"^hub\.json: Permission denied$"):
        read_hub_tree(root, wanted={"hub.json"})


def swap_before_open(monkeypatch: pytest.MonkeyPatch, swap: Callable[[str], None]) -> None:
    """Run ``swap`` on the path the reader opens, right before the real ``os.open``: a race."""
    real_open = os.open

    def swapped_open(path: str, flags: int, mode: int = 0o777) -> int:
        swap(path)
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", swapped_open)


def test_reports_not_regular_when_file_swapped_for_fifo_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    write_file(root / "hub.json", b"{}\n")

    def to_fifo(path: str) -> None:
        os.unlink(path)
        os.mkfifo(path)

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

    def to_link(path: str) -> None:
        os.unlink(path)
        os.symlink(outside / "x.md", path)

    swap_before_open(monkeypatch, to_link)

    with pytest.raises(GeneratorError, match=r"^hub\.json: "):
        read_hub_tree(root, wanted={"hub.json"})
