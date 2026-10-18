import json
from pathlib import Path

import pytest

from agent_hub.api.local_settings import LocalSettings, write_local_settings
from agent_hub.core.hubs.hub_registry import HubInvalidError


def _local(hub: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((hub / "hub.local.json").read_text())
    return loaded


def test_writes_identity_and_blocked_words_when_no_file_exists(tmp_path: Path) -> None:
    write_local_settings(
        str(tmp_path),
        LocalSettings(author_email="me@example.com", blocked_words=("acme", " acme ", "")),
    )

    assert _local(tmp_path) == {
        "project": {"author_email": "me@example.com"},
        "guard": {"blocked_words": ["acme"]},
    }


def test_keeps_keys_the_screen_does_not_edit(tmp_path: Path) -> None:
    (tmp_path / "hub.local.json").write_text(
        json.dumps({"_comment": "mine", "environments": {}, "project": {"author_name": "Old"}})
    )

    write_local_settings(str(tmp_path), LocalSettings(transport="mcp"))

    assert _local(tmp_path) == {
        "_comment": "mine",
        "environments": {},
        "tracker": {"transport": "mcp"},
    }


def test_removes_the_file_when_nothing_is_left(tmp_path: Path) -> None:
    (tmp_path / "hub.local.json").write_text(json.dumps({"project": {"author_name": "Old"}}))

    write_local_settings(str(tmp_path), LocalSettings())

    assert not (tmp_path / "hub.local.json").exists()


def test_refuses_an_invalid_value_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(HubInvalidError) as raised:
        write_local_settings(str(tmp_path), LocalSettings(branch_prefix="no slash"))

    assert raised.value.problems[0].pointer == "project.branch_prefix"
    assert not (tmp_path / "hub.local.json").exists()
