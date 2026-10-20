"""A hub's discoveries on the file system: ``HubDiscoveryFiles`` under ``.agent-runs``."""

import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_hub.api.discovery_files import FOLDER, DiscoveryFolderError, HubDiscoveryFiles
from agent_hub.core.environment_discovery.discovery import DiscoveryRecord


def _record(discovery_id: str = "0123456789ab", **fields: object) -> DiscoveryRecord:
    body: dict[str, object] = {
        "id": discovery_id,
        "project": "demo",
        "agent_session_id": "01929a4e-7a11-7c00-8a00-00000000a001",
        "repos": ["demo-api"],
        "environments": ["staging"],
        "suggest_environments": False,
        "created_at": datetime(2026, 10, 20, 9, 0, tzinfo=UTC),
    }
    return DiscoveryRecord.model_validate(body | fields)


def test_reads_back_record_when_created(tmp_path: Path) -> None:
    files = HubDiscoveryFiles()

    files.create(str(tmp_path), _record())

    assert files.get(str(tmp_path), "0123456789ab") == _record()
    assert files.list(str(tmp_path)) == (_record(),)
    stored = tmp_path / FOLDER / "0123456789ab.json"
    assert stat.S_IMODE(stored.stat().st_mode) == 0o600
    assert stat.S_IMODE(stored.parent.stat().st_mode) == 0o700


def test_refuses_second_create_when_id_taken(tmp_path: Path) -> None:
    files = HubDiscoveryFiles()
    files.create(str(tmp_path), _record())

    with pytest.raises(FileExistsError):
        files.create(str(tmp_path), _record())


def test_rewrites_record_when_replaced(tmp_path: Path) -> None:
    files = HubDiscoveryFiles()
    files.create(str(tmp_path), _record())

    files.replace(str(tmp_path), _record(discarded=True))

    found = files.get(str(tmp_path), "0123456789ab")
    assert found is not None
    assert found.discarded is True
    assert sorted(path.name for path in (tmp_path / FOLDER).iterdir()) == ["0123456789ab.json"]


def test_answers_nothing_when_folder_absent(tmp_path: Path) -> None:
    files = HubDiscoveryFiles()

    assert files.list(str(tmp_path)) == ()
    assert files.get(str(tmp_path), "0123456789ab") is None


@pytest.mark.parametrize("discovery_id", ["../../etc", "0123456789AB", "short"])
def test_answers_none_when_id_not_a_discovery_id(tmp_path: Path, discovery_id: str) -> None:
    assert HubDiscoveryFiles().get(str(tmp_path), discovery_id) is None


def test_skips_file_when_not_a_record(tmp_path: Path) -> None:
    files = HubDiscoveryFiles()
    files.create(str(tmp_path), _record())
    (tmp_path / FOLDER / "aaaaaaaaaaaa.json").write_text("{not json", encoding="utf-8")

    assert files.list(str(tmp_path)) == (_record(),)


def test_refuses_folder_when_it_is_a_link(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".agent-runs").mkdir()
    (tmp_path / FOLDER).symlink_to(elsewhere)

    with pytest.raises(DiscoveryFolderError):
        HubDiscoveryFiles().create(str(tmp_path), _record())
    assert list(elsewhere.iterdir()) == []
