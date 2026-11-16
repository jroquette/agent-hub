"""The non-exiting ``hub.json`` and ``hub.local.json`` readers on real files (plan F.1).

The cli's ``hub_config_reader`` re-exports them; its own tests keep covering the exiting loaders.
"""

import json
import os
from pathlib import Path

from agent_hub.core.hub_config.local_config import LOCAL_FILE_MAX_BYTES, LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.hub_config_files import (
    LoadedHubJson,
    UnreadFile,
    load_hub_document,
    read_file_bytes,
    read_hub_bytes,
    read_hub_json,
    read_local_json,
)

PIN = "4.5.6"


def write_hub(tmp_path: Path, *, pin: str = PIN) -> Path:
    document = a_hub_document()
    document["platform"]["version"] = pin
    path = tmp_path / "hub.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_reports_missing_when_hub_json_absent(tmp_path: Path) -> None:
    unread = read_file_bytes(tmp_path / "hub.json")

    assert isinstance(unread, UnreadFile)
    assert unread.is_missing
    assert unread.problem.path == ROOT_PATH
    assert "No such file or directory" in unread.problem.message


def test_refuses_without_blocking_when_hub_json_is_fifo(tmp_path: Path) -> None:
    path = tmp_path / "hub.json"
    os.mkfifo(path)

    read = read_hub_bytes(path)

    assert isinstance(read, tuple)
    assert read[0].message.endswith("not a regular file")


def test_reports_not_missing_when_local_file_is_fifo(tmp_path: Path) -> None:
    path = tmp_path / "hub.local.json"
    os.mkfifo(path)

    read = read_local_json(path)

    assert isinstance(read, tuple)
    assert read[0].message.endswith("not a regular file")


def test_gives_empty_local_config_when_local_file_missing(tmp_path: Path) -> None:
    assert read_local_json(tmp_path / "hub.local.json") == LocalConfig()


def test_refuses_local_file_when_larger_than_cap(tmp_path: Path) -> None:
    path = tmp_path / "hub.local.json"
    path.write_bytes(b" " * (LOCAL_FILE_MAX_BYTES + 1))

    read = read_local_json(path)

    assert isinstance(read, tuple)
    assert f"larger than {LOCAL_FILE_MAX_BYTES} bytes" in read[0].message


def test_checks_pin_against_given_version_when_hub_json_read(tmp_path: Path) -> None:
    path = write_hub(tmp_path)

    loaded = read_hub_json(path, running_version=PIN)
    other = read_hub_json(path, running_version="9.9.9")

    assert isinstance(loaded, LoadedHubJson)
    assert loaded.content == path.read_bytes()
    assert isinstance(loaded.config, HubConfig)
    assert isinstance(other, tuple)
    assert other[0].path == "platform.version"


def test_keeps_missing_flag_when_document_loaded_from_absent_file(tmp_path: Path) -> None:
    loaded = load_hub_document(tmp_path / "hub.json", running_version=PIN)

    assert isinstance(loaded, UnreadFile)
    assert loaded.is_missing
