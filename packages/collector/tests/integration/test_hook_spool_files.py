"""``HookSpool`` on real files: the sensor's spool is moved aside, read, and removed once stored."""

import fcntl
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agent_hub.collector.errors import CollectorError
from agent_hub.collector.hook_spool import LOCK_FILE, SPOOL_FILE, TAKEN_FILE, HookSpool
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope


def _line(tool_use_id: str) -> bytes:
    hook = a_hook_input("PreToolUse", tool_use_id=tool_use_id)
    return an_envelope(hook).model_dump_json().encode() + b"\n"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "state" / "agent-hub"
    path.mkdir(parents=True, mode=0o700)
    return path


def _spool(folder: Path, *tool_use_ids: str) -> None:
    path = folder / SPOOL_FILE
    with path.open("ab") as file:
        for tool_use_id in tool_use_ids:
            file.write(_line(tool_use_id))
    path.chmod(0o600)


def _ids(taken: Any) -> list[str]:
    return [str(item.envelope.hook["tool_use_id"]) for item in taken.lines.envelopes]


def test_returns_none_when_folder_missing(tmp_path: Path) -> None:
    assert HookSpool(tmp_path / "missing").take() is None


def test_returns_none_when_nothing_spooled(folder: Path) -> None:
    assert HookSpool(folder).take() is None


def test_moves_spool_aside_and_parses_it_when_taken(folder: Path) -> None:
    _spool(folder, "toolu_1", "toolu_2")

    taken = HookSpool(folder).take()

    assert taken is not None
    assert _ids(taken) == ["toolu_1", "toolu_2"]
    assert not (folder / SPOOL_FILE).exists()
    assert (folder / TAKEN_FILE).read_bytes() == _line("toolu_1") + _line("toolu_2")
    assert stat.S_IMODE((folder / TAKEN_FILE).stat().st_mode) == 0o600


def test_reads_taken_again_when_not_removed(folder: Path) -> None:
    _spool(folder, "toolu_1")
    spool = HookSpool(folder)
    spool.take()

    again = spool.take()

    assert again is not None
    assert _ids(again) == ["toolu_1"]


def test_appends_new_spool_to_taken_when_earlier_take_not_removed(folder: Path) -> None:
    _spool(folder, "toolu_1")
    spool = HookSpool(folder)
    spool.take()
    _spool(folder, "toolu_2")

    taken = spool.take()

    assert taken is not None
    assert _ids(taken) == ["toolu_1", "toolu_2"]
    assert not (folder / SPOOL_FILE).exists()


def test_removes_taken_when_unchanged_since_read(folder: Path) -> None:
    _spool(folder, "toolu_1")
    spool = HookSpool(folder)
    taken = spool.take()
    assert taken is not None

    spool.remove(taken)

    assert sorted(path.name for path in folder.iterdir()) == [LOCK_FILE]
    assert spool.take() is None


def test_keeps_taken_when_it_grew_since_read(folder: Path) -> None:
    _spool(folder, "toolu_1")
    spool = HookSpool(folder)
    first = spool.take()
    assert first is not None
    _spool(folder, "toolu_2")
    spool.take()

    spool.remove(first)

    later = spool.take()
    assert later is not None
    assert _ids(later) == ["toolu_1", "toolu_2"]


def test_waits_for_sensor_lock_when_spool_being_written(folder: Path) -> None:
    _spool(folder, "toolu_1")
    lock = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    taken: list[Any] = []
    taker = threading.Thread(target=lambda: taken.append(HookSpool(folder).take()))
    taker.start()
    time.sleep(0.2)
    _spool(folder, "toolu_2")  # the sensor's write, under its lock
    fcntl.flock(lock, fcntl.LOCK_UN)
    os.close(lock)
    taker.join(timeout=5)

    [batch] = taken
    assert _ids(batch) == ["toolu_1", "toolu_2"]


def test_refuses_when_folder_is_link(folder: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    os.symlink(folder, link)
    _spool(folder, "toolu_1")

    with pytest.raises(CollectorError, match="cannot open"):
        HookSpool(link).take()

    assert (folder / SPOOL_FILE).exists()


def test_refuses_when_spool_is_link(folder: Path, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.jsonl"
    target.write_bytes(_line("toolu_1"))
    os.symlink(target, folder / SPOOL_FILE)

    with pytest.raises(CollectorError, match="not a regular file"):
        HookSpool(folder).take()

    assert (folder / SPOOL_FILE).is_symlink()
    assert not (folder / TAKEN_FILE).exists()


def test_refuses_when_taken_larger_than_bound(folder: Path) -> None:
    _spool(folder, "toolu_1", "toolu_2")
    size = (folder / SPOOL_FILE).stat().st_size

    with pytest.raises(CollectorError, match=f"larger than {size - 1} bytes"):
        HookSpool(folder, max_bytes=size - 1).take()
