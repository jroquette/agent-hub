import json
from pathlib import Path

import pytest

from agent_hub.api import local_settings
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


def test_keeps_other_keys_when_local_values_saved(tmp_path: Path) -> None:
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


def test_writes_nothing_when_value_invalid(tmp_path: Path) -> None:
    with pytest.raises(HubInvalidError) as raised:
        write_local_settings(str(tmp_path), LocalSettings(branch_prefix="no slash"))

    assert raised.value.problems[0].pointer == "project.branch_prefix"
    assert not (tmp_path / "hub.local.json").exists()


# AC-PG-38.4: the write is atomic: a failed write leaves the old file whole, and no temporary
# file is left beside it.
def test_keeps_old_file_when_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "hub.local.json"
    path.write_text(json.dumps({"project": {"author_name": "Old"}}))
    before = path.read_bytes()

    def refuse(_source: object, _target: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(local_settings.os, "replace", refuse)

    with pytest.raises(OSError, match="No space left"):
        write_local_settings(str(tmp_path), LocalSettings(author_name="New"))

    assert path.read_bytes() == before
    assert sorted(child.name for child in tmp_path.iterdir()) == ["hub.local.json"]


# AC-PG-38.4: a successful write replaces the file whole and leaves no temporary file.
def test_leaves_only_the_file_when_write_succeeds(tmp_path: Path) -> None:
    (tmp_path / "hub.local.json").write_text(json.dumps({"project": {"author_name": "Old"}}))

    write_local_settings(str(tmp_path), LocalSettings(author_name="New"))

    assert _local(tmp_path) == {"project": {"author_name": "New"}}
    assert sorted(child.name for child in tmp_path.iterdir()) == ["hub.local.json"]


# AC-PG-38.4: the team's hub.json is never touched by a local write.
def test_leaves_team_file_unchanged_when_local_values_saved(tmp_path: Path) -> None:
    team = tmp_path / "hub.json"
    team.write_text('{"project": {"author_name": "Team"}}\n')
    before = team.read_bytes()

    write_local_settings(str(tmp_path), LocalSettings(author_name="Me", transport="mcp"))

    assert team.read_bytes() == before
    assert _local(tmp_path) == {"project": {"author_name": "Me"}, "tracker": {"transport": "mcp"}}


# AC-PG-38.4: an invalid value leaves an existing file exactly as it was.
def test_keeps_existing_file_when_value_invalid(tmp_path: Path) -> None:
    path = tmp_path / "hub.local.json"
    path.write_text(json.dumps({"project": {"author_name": "Old"}}))
    before = path.read_bytes()

    with pytest.raises(HubInvalidError):
        write_local_settings(str(tmp_path), LocalSettings(branch_prefix="no slash"))

    assert path.read_bytes() == before


# AC-PG-38.4: a hub.local.json that is not JSON is refused, never overwritten.
def test_refuses_and_keeps_file_when_local_file_not_json(tmp_path: Path) -> None:
    path = tmp_path / "hub.local.json"
    path.write_text("{not json")

    with pytest.raises(HubInvalidError, match="hub.local.json is not valid JSON"):
        write_local_settings(str(tmp_path), LocalSettings(author_name="New"))

    assert path.read_text() == "{not json"
