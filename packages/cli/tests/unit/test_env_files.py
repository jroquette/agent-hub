import errno
import os
import stat
from pathlib import Path

import pytest

from agent_hub.cli import env_files
from agent_hub.cli.env_files import document_bytes, is_reformatted, write_document

NAME = "hub.json"
READ = b'{\n  "_comment": "first",\n  "schema_version": 1\n}\n'


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """An empty folder: its listing is exactly what a write left."""
    path = tmp_path / "hub"
    path.mkdir()
    return path


def test_writes_indent_two_with_final_newline_when_document_dumped() -> None:
    document = {"z": 1, "a": {"é": [1, 2]}}

    assert (
        document_bytes(document)
        == '{\n  "z": 1,\n  "a": {\n    "é": [\n      1,\n      2\n    ]\n  }\n}\n'.encode()
    )
    assert is_reformatted(READ) is False
    assert is_reformatted(b'{"_comment": "first", "schema_version": 1}\n') is True
    assert is_reformatted(b'{\n    "schema_version": 1\n}\n') is True


def test_replaces_file_keeping_mode_when_unchanged_since_read(folder: Path) -> None:
    target = folder / NAME
    target.write_bytes(READ)
    target.chmod(0o640)

    refusal = write_document(target, read=READ, content=b"{}\n")

    assert refusal is None
    assert target.read_bytes() == b"{}\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert sorted(os.listdir(folder)) == [NAME]


def test_refuses_write_when_file_changed_since_read(folder: Path) -> None:
    target = folder / NAME
    target.write_bytes(b'{"changed": true}\n')

    refusal = write_document(target, read=READ, content=b"{}\n")

    assert refusal == "hub.json changed since it was read; run the command again"


def test_keeps_bytes_when_write_refused(folder: Path) -> None:
    target = folder / NAME
    target.write_bytes(b'{"changed": true}\n')
    gone = folder / "hub.local.json"

    assert write_document(target, read=READ, content=b"{}\n") is not None
    assert write_document(gone, read=READ, content=b"{}\n") is not None
    assert target.read_bytes() == b'{"changed": true}\n'
    assert sorted(os.listdir(folder)) == [NAME]


def test_creates_local_file_when_absent(folder: Path) -> None:
    target = folder / "hub.local.json"

    assert write_document(target, read=None, content=b"{}\n") is None
    assert target.read_bytes() == b"{}\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    # A file that appeared after the read is never replaced.
    assert write_document(target, read=None, content=b"[]\n") == (
        "hub.local.json changed since it was read; run the command again"
    )
    assert target.read_bytes() == b"{}\n"


def test_names_reason_only_when_write_fails(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = folder / NAME
    target.write_bytes(READ)

    def refuse(*_args: object) -> None:
        raise OSError(errno.EACCES, "Permission denied", str(target))

    monkeypatch.setattr(env_files.os, "replace", refuse)

    assert write_document(target, read=READ, content=b"{}\n") == (
        "hub.json: cannot write: Permission denied"
    )
    assert target.read_bytes() == READ
    assert sorted(os.listdir(folder)) == [NAME]
