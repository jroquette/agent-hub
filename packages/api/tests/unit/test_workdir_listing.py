import os
from pathlib import Path

import pytest

from agent_hub.api.workdir_listing import RegisteredWorkdirs, scan_dirs
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.hub_fakes import (
    FakeHub,
    FakeHubFileReader,
    InMemoryHubRegistry,
    hub_json_bytes,
)

RUNNING = "0.9.0"


def _tree(root: Path) -> Path:
    """A hub ``demo-hub`` next to its repo ``demo-api``, whose worktrees folder holds a
    worktree, a link to a folder outside the layout and a file."""
    hub = root / "demo-hub"
    (hub / ".claude" / "skills" / "feature").mkdir(parents=True)
    worktrees = root / "demo-api" / ".claude" / "worktrees"
    (worktrees / "agh-7-collector").mkdir(parents=True)
    outside = root.parent / "outside"
    outside.mkdir()
    (worktrees / "agh-8-escape").symlink_to(outside, target_is_directory=True)
    (worktrees / "notes.txt").write_text("not a folder", "utf-8")
    return hub


def _workdirs(hub: Path) -> RegisteredWorkdirs:
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    reader = FakeHubFileReader({str(hub): FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})
    return RegisteredWorkdirs(registry=registry, reader=reader, running_version=RUNNING)


def test_lists_workdirs_without_following_links_when_scanned(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")

    listing = _workdirs(hub)("demo")

    labels = [entry.workdir.label for entry in listing.entries]
    assert labels == ["demo-hub", "demo-api", "demo-api/agh-7-collector"]
    assert listing.entries[0].workdir.skills == ("feature",)
    assert listing.entries[2].path == os.path.realpath(
        tmp_path / "work" / "demo-api" / ".claude" / "worktrees" / "agh-7-collector"
    )


def test_names_only_real_folders_when_folder_scanned(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")
    worktrees = hub.parent / "demo-api" / ".claude" / "worktrees"

    assert scan_dirs(str(worktrees)) == ["agh-7-collector"]


def test_raises_not_found_when_folder_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_dirs(str(tmp_path / "missing"))


def test_raises_not_found_when_project_unregistered(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")

    with pytest.raises(EntityNotFoundError):
        _workdirs(hub)("other")


def test_lists_again_when_folder_added_after_first_listing(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")
    workdirs = _workdirs(hub)
    first = workdirs("demo")
    (hub.parent / "demo-api" / ".claude" / "worktrees" / "agh-9-new").mkdir()

    second = workdirs("demo")

    assert len(second.entries) == len(first.entries) + 1


def test_lists_nothing_when_hub_owned_by_other_user(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")
    registry = InMemoryHubRegistry()
    registry.add(str(hub))
    reader = FakeHubFileReader({str(hub): FakeHub(hub_json=hub_json_bytes(pin=RUNNING))})
    hub_real = os.path.realpath(hub)

    def stat(path: str) -> os.stat_result:
        found = os.stat(path)
        uid = found.st_uid + 1 if path == hub_real else found.st_uid
        return os.stat_result((found.st_mode, 0, 0, 0, uid, 0, 0, 0, 0, 0))

    workdirs = RegisteredWorkdirs(
        registry=registry,
        reader=reader,
        running_version=RUNNING,
        stat=stat,
        uid=os.stat(hub).st_uid,
    )

    listing = workdirs("demo")

    assert listing.entries == ()
    assert listing.warnings == ("refused demo-hub: not owned by the current user",)


def test_checks_owner_against_effective_uid_when_defaults_used(tmp_path: Path) -> None:
    hub = _tree(tmp_path / "work")
    (hub.parent / "demo-api").chmod(0o777)

    listing = _workdirs(hub)("demo")

    assert [entry.workdir.label for entry in listing.entries] == ["demo-hub"]
    assert listing.warnings == ("refused demo-api: writable by group or others",)
