import errno
import os
import stat
from pathlib import Path

import pytest

from agent_hub.cli import exclusive_write
from agent_hub.cli.exclusive_write import write_exclusive

NAME = "hub.local.json"
CONTENT = b'{\n  "project": {\n    "branch_prefix": "jane/"\n  }\n}\n'


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """An empty folder: its listing is exactly what a write left."""
    path = tmp_path / "hub"
    path.mkdir()
    return path


@pytest.mark.parametrize("umask", [0o077, 0o022], ids=["umask-077", "umask-022"])
def test_writes_bytes_with_mode_when_name_free(folder: Path, umask: int) -> None:
    previous = os.umask(umask)
    try:
        written = write_exclusive(folder, NAME, CONTENT)
    finally:
        os.umask(previous)

    assert written is True
    assert (folder / NAME).read_bytes() == CONTENT
    assert stat.S_IMODE((folder / NAME).stat().st_mode) == 0o644
    assert sorted(os.listdir(folder)) == [NAME]


def test_keeps_existing_file_when_name_taken(folder: Path) -> None:
    target = folder / NAME
    target.write_bytes(b"existing\n")
    before = target.stat().st_mtime_ns

    written = write_exclusive(folder, NAME, CONTENT)

    assert written is False
    assert target.read_bytes() == b"existing\n"
    assert target.stat().st_mtime_ns == before
    assert sorted(os.listdir(folder)) == [NAME]


def test_keeps_appeared_file_when_link_races(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = os.link

    def appear_then_link(source: str | Path, destination: str | Path) -> None:
        Path(destination).write_bytes(b"appeared\n")
        real_link(source, destination)

    monkeypatch.setattr(exclusive_write.os, "link", appear_then_link)

    written = write_exclusive(folder, NAME, CONTENT)

    assert written is False
    assert (folder / NAME).read_bytes() == b"appeared\n"
    assert sorted(os.listdir(folder)) == [NAME]


def test_removes_temp_and_raises_when_link_fails(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_link(source: str | Path, destination: str | Path) -> None:
        raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(destination))

    monkeypatch.setattr(exclusive_write.os, "link", refuse_link)

    with pytest.raises(PermissionError) as raised:
        write_exclusive(folder, NAME, CONTENT)

    assert raised.value.strerror == os.strerror(errno.EPERM)
    assert os.listdir(folder) == []


def test_keeps_published_file_when_temp_removal_fails(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_unlink(path: str | Path) -> None:
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))

    monkeypatch.setattr(exclusive_write.os, "unlink", refuse_unlink)

    written = write_exclusive(folder, NAME, CONTENT)

    assert written is True
    assert (folder / NAME).read_bytes() == CONTENT


def test_raises_link_error_when_temp_removal_also_fails(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_link(source: str | Path, destination: str | Path) -> None:
        raise PermissionError(errno.EPERM, os.strerror(errno.EPERM), str(destination))

    def refuse_unlink(path: str | Path) -> None:
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(path))

    monkeypatch.setattr(exclusive_write.os, "link", refuse_link)
    monkeypatch.setattr(exclusive_write.os, "unlink", refuse_unlink)

    with pytest.raises(PermissionError) as raised:
        write_exclusive(folder, NAME, CONTENT)

    assert raised.value.strerror == os.strerror(errno.EPERM)
    assert not (folder / NAME).exists()


def test_keeps_published_file_when_folder_sync_fails(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync
    synced_folders: list[int] = []

    def refuse_folder_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            synced_folders.append(descriptor)
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        real_fsync(descriptor)

    monkeypatch.setattr(exclusive_write.os, "fsync", refuse_folder_fsync)

    written = write_exclusive(folder, NAME, CONTENT)

    assert written is True
    assert len(synced_folders) == 1
    assert (folder / NAME).read_bytes() == CONTENT
    assert sorted(os.listdir(folder)) == [NAME]
