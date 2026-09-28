from pathlib import Path

import pytest

from agent_hub.collector.errors import CollectorError, InputNotFoundError, InputUnreadableError
from agent_hub.collector.jsonl import read_text
from agent_hub.core.testing.builders import an_event, events_to_jsonl


def test_reads_text_when_file_exists(tmp_path: Path) -> None:
    text = events_to_jsonl([an_event(payload={"text": "café"}), an_event()])
    path = tmp_path / "events.jsonl"
    path.write_text(text, encoding="utf-8")

    assert read_text(path) == text


def test_raises_not_found_when_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"

    with pytest.raises(InputNotFoundError) as caught:
        read_text(path)

    assert str(path) in str(caught.value)
    assert isinstance(caught.value, CollectorError)


def test_raises_unreadable_when_path_is_directory(tmp_path: Path) -> None:
    with pytest.raises(InputUnreadableError) as caught:
        read_text(tmp_path)

    assert str(tmp_path) in str(caught.value)
    assert isinstance(caught.value, CollectorError)


def test_raises_unreadable_when_bytes_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "latin1.jsonl"
    path.write_bytes(b'{"project": "caf\xe9"}\n')

    with pytest.raises(InputUnreadableError) as caught:
        read_text(path)

    assert str(path) in str(caught.value)
    assert "UTF-8" in str(caught.value)


def test_drops_byte_order_mark_when_file_starts_with_one(tmp_path: Path) -> None:
    text = events_to_jsonl([an_event()])
    path = tmp_path / "bom.jsonl"
    path.write_bytes(b"\xef\xbb\xbf" + text.encode())

    assert read_text(path) == text
