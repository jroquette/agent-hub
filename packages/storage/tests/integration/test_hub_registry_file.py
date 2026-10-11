"""``hubs.json`` on disk (D18): file and folder modes, bounds, unreadable files, atomic writes."""

import json
import os
import stat
from pathlib import Path

import pytest

from agent_hub.core.hubs.hub_registry import MAX_HUBS, HubRegistryError
from agent_hub.storage.hub_registry import MAX_REGISTRY_BYTES, JsonHubRegistry


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    return tmp_path / "config" / "agent-hub" / "hubs.json"


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_writes_private_modes_when_first_hub_added(registry_path: Path) -> None:
    JsonHubRegistry(registry_path).add("/hubs/demo-hub")

    assert mode_of(registry_path) == 0o600
    assert mode_of(registry_path.parent) == 0o700


def test_keeps_entries_when_registry_reopened(registry_path: Path) -> None:
    added = JsonHubRegistry(registry_path).add("/hubs/demo-hub")

    assert JsonHubRegistry(registry_path).entries() == (added,)


def test_lists_nothing_when_file_absent(registry_path: Path) -> None:
    assert JsonHubRegistry(registry_path).entries() == ()
    assert not registry_path.exists()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")


def make_invalid_json(path: Path) -> None:
    write_text(path, "{")


def make_wrong_shape(path: Path) -> None:
    write_text(path, json.dumps({"hubs": [{"path": "/hubs/x"}]}))


def make_too_large(path: Path) -> None:
    write_text(path, " " * (MAX_REGISTRY_BYTES + 1))


def make_fifo(path: Path) -> None:
    path.parent.mkdir(parents=True)
    os.mkfifo(path)


def make_link(path: Path) -> None:
    path.parent.mkdir(parents=True)
    target = path.parent / "real.json"
    target.write_text(json.dumps({"hubs": []}), encoding="utf-8")
    path.symlink_to(target)


@pytest.mark.parametrize(
    ("make_file", "reason"),
    [
        (make_invalid_json, "not valid JSON"),
        (make_wrong_shape, "id"),
        (make_too_large, f"larger than {MAX_REGISTRY_BYTES} bytes"),
        (make_fifo, "not a regular file"),
        (make_link, "cannot read"),
    ],
    ids=["invalid-json", "wrong-shape", "too-large", "fifo", "link"],
)
def test_raises_registry_error_when_file_unreadable(
    registry_path: Path, make_file: object, reason: str
) -> None:
    assert callable(make_file)
    make_file(registry_path)

    with pytest.raises(HubRegistryError, match=reason) as raised:
        JsonHubRegistry(registry_path).entries()

    assert "\n" not in str(raised.value)
    assert str(registry_path) in str(raised.value)


def test_refuses_hub_when_registry_full(registry_path: Path) -> None:
    registry = JsonHubRegistry(registry_path)
    for index in range(MAX_HUBS):
        registry.add(f"/hubs/hub-{index}")

    with pytest.raises(HubRegistryError, match=f"{MAX_HUBS} hubs"):
        registry.add("/hubs/one-more")

    assert len(registry.entries()) == MAX_HUBS


def test_keeps_old_file_atomic_when_replace_fails(
    registry_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = JsonHubRegistry(registry_path)
    registry.add("/hubs/demo-hub")
    before = registry_path.read_bytes()

    def failing_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(HubRegistryError, match="No space left on device"):
        registry.add("/hubs/other-hub")

    assert registry_path.read_bytes() == before
    assert sorted(path.name for path in registry_path.parent.iterdir()) == ["hubs.json"]


def test_raises_registry_error_when_folder_unwritable(tmp_path: Path) -> None:
    folder = tmp_path / "locked"
    folder.mkdir(mode=0o500)
    if os.access(folder, os.W_OK):
        pytest.skip("running as a user that writes any folder")

    with pytest.raises(HubRegistryError, match="cannot write"):
        JsonHubRegistry(folder / "hubs.json").add("/hubs/demo-hub")
