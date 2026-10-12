"""The brain reader on real folders (AGH-201 B7): bounded, under ``brain/``, no link followed."""

import os
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.hubs.hub_registry import BrainListing, UnreadHubFile
from agent_hub.generator import brain_files
from agent_hub.generator.brain_files import brain_file_size, list_brain, read_brain_file

LIMIT = 1024


def a_brain(hub: Path, files: dict[str, bytes]) -> Path:
    brain = hub / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        target = brain / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return brain


def paths_of(listing: BrainListing) -> list[str]:
    return [entry.path for entry in listing.entries]


def test_lists_markdown_when_brain_nested(tmp_path: Path) -> None:
    a_brain(
        tmp_path,
        {
            "index.md": b"# Brain\n",
            "decisions/index.md": b"# D\n",
            "playbooks/deep/x.md": b"xyz",
            "playbooks/notes.txt": b"not a note",
        },
    )

    listing = list_brain(tmp_path)

    assert listing == BrainListing(
        entries=(
            BrainEntry(path="decisions/index.md", size=4),
            BrainEntry(path="index.md", size=8),
            BrainEntry(path="playbooks/deep/x.md", size=3),
        )
    )


def test_lists_nothing_when_hub_has_no_brain(tmp_path: Path) -> None:
    assert list_brain(tmp_path) == BrainListing(entries=())


def test_skips_auto_and_hidden_when_listing(tmp_path: Path) -> None:
    brain = a_brain(
        tmp_path,
        {
            "index.md": b"#",
            "auto/workspace/me.md": b"personal",
            ".git/x.md": b"#",
            "notes/.draft.md": b"#",
            "notes/auto/kept.md": b"#",
        },
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"#")
    (brain / "linked").symlink_to(outside)
    (brain / "linked.md").symlink_to(outside / "secret.md")
    os.mkfifo(brain / "pipe.md")

    assert paths_of(list_brain(tmp_path)) == ["index.md", "notes/auto/kept.md"]


def test_skips_auto_when_name_differs_in_case(tmp_path: Path) -> None:
    a_brain(tmp_path, {"index.md": b"#", "Auto/me.md": b"personal", "AUTO/x/me.md": b"p"})

    assert paths_of(list_brain(tmp_path)) == ["index.md"]


def test_skips_brain_when_brain_is_link(tmp_path: Path) -> None:
    elsewhere = a_brain(tmp_path / "elsewhere", {"index.md": b"#"})
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "brain").symlink_to(elsewhere)

    assert list_brain(hub) == BrainListing(entries=())


def test_skips_unreadable_folder_when_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_brain(tmp_path, {"index.md": b"#", "locked/x.md": b"#"})
    real_open = os.open

    def denied(name: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if name == "locked":
            raise PermissionError(13, "Permission denied")
        return real_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", denied)

    listing = list_brain(tmp_path)

    assert (paths_of(listing), listing.skipped, listing.truncated) == (["index.md"], 1, False)


def test_stops_listing_when_file_cap_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brain_files, "MAX_BRAIN_FILES", 3)
    a_brain(tmp_path, {f"n{index}.md": b"#" for index in range(5)})

    listing = list_brain(tmp_path)

    assert paths_of(listing) == ["n0.md", "n1.md", "n2.md"]
    assert (listing.truncated, listing.skipped) == (True, 2)


def test_stops_listing_when_folder_cap_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brain_files, "MAX_BRAIN_FOLDERS", 2)
    a_brain(tmp_path, {"a/x.md": b"#", "b/x.md": b"#", "c/x.md": b"#"})

    listing = list_brain(tmp_path)

    assert paths_of(listing) == ["a/x.md", "b/x.md"]
    assert (listing.truncated, listing.skipped) == (True, 1)


def test_stops_descending_when_depth_cap_reached(tmp_path: Path) -> None:
    deep = "/".join(f"d{level}" for level in range(1, brain_files.MAX_BRAIN_DEPTH + 2))
    kept = "/".join(f"d{level}" for level in range(1, brain_files.MAX_BRAIN_DEPTH + 1))
    a_brain(tmp_path, {f"{kept}/kept.md": b"#", f"{deep}/too-deep.md": b"#"})

    listing = list_brain(tmp_path)

    assert paths_of(listing) == [f"{kept}/kept.md"]
    assert (listing.truncated, listing.skipped) == (True, 1)


def test_reads_note_when_path_regular_file(tmp_path: Path) -> None:
    a_brain(tmp_path, {"decisions/index.md": b"# Decisions\n"})

    assert read_brain_file(tmp_path, "decisions/index.md", max_bytes=LIMIT) == b"# Decisions\n"
    assert brain_file_size(tmp_path, "decisions/index.md") == len(b"# Decisions\n")


def test_reports_missing_when_note_absent(tmp_path: Path) -> None:
    a_brain(tmp_path, {"index.md": b"#"})

    for path in ("absent.md", "nope/absent.md", "index.md/x.md"):
        read = read_brain_file(tmp_path, path, max_bytes=LIMIT)
        assert isinstance(read, UnreadHubFile)
        assert (read.kind, read.is_missing) == ("missing", True)
        assert brain_file_size(tmp_path, path) is None


@pytest.mark.parametrize("linked", ["linked.md", "folder/x.md"])
def test_refuses_note_when_symlink_in_path(tmp_path: Path, linked: str) -> None:
    brain = a_brain(tmp_path, {"index.md": b"#"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_bytes(b"secret")
    (brain / "linked.md").symlink_to(outside / "x.md")
    (brain / "folder").symlink_to(outside)

    read = read_brain_file(tmp_path, linked, max_bytes=LIMIT)

    assert isinstance(read, UnreadHubFile)
    assert (read.kind, read.is_missing) == ("not_regular", False)
    assert "outside" not in read.message
    assert brain_file_size(tmp_path, linked) is None


def test_refuses_note_when_not_regular(tmp_path: Path) -> None:
    brain = a_brain(tmp_path, {"folder.md/x.md": b"#"})
    os.mkfifo(brain / "pipe.md")

    for path in ("folder.md", "pipe.md"):
        read = read_brain_file(tmp_path, path, max_bytes=LIMIT)
        assert isinstance(read, UnreadHubFile)
        assert read.kind == "not_regular"
        assert brain_file_size(tmp_path, path) is None


def test_refuses_note_when_over_size(tmp_path: Path) -> None:
    a_brain(tmp_path, {"big.md": b"x" * (LIMIT + 1), "edge.md": b"x" * LIMIT})

    read = read_brain_file(tmp_path, "big.md", max_bytes=LIMIT)

    assert isinstance(read, UnreadHubFile)
    assert (read.kind, read.is_missing) == ("too_large", False)
    assert brain_file_size(tmp_path, "big.md") == LIMIT + 1
    assert read_brain_file(tmp_path, "edge.md", max_bytes=LIMIT) == b"x" * LIMIT


@pytest.mark.parametrize(
    "path",
    [
        "../hub.json",
        "/etc/passwd",
        "../x.md",
        "a/../../x.md",
        "a\\b.md",
        "auto/workspace/x.md",
        "x.txt",
        ".hidden/x.md",
        "link/x.md",
        "linked.md",
    ],
)
def test_opens_no_file_outside_brain_when_path_traversal_attempted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    hub = tmp_path / "hub"
    brain = a_brain(hub, {"a/index.md": b"#", "auto/workspace/x.md": b"personal"})
    (hub / "hub.json").write_bytes(b"{}")
    (hub / "x.md").write_bytes(b"#")
    (hub / "x.txt").write_bytes(b"#")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_bytes(b"secret")
    (brain / "link").symlink_to(outside)
    (brain / "linked.md").symlink_to(outside / "x.md")
    inside = {_identity(hub.stat())} | {
        _identity(found.lstat())
        for found in (brain, *brain.rglob("*"))
        if "auto" not in found.parts
    }
    opened: list[tuple[int, int]] = []
    real_open = os.open

    def spy(name: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        descriptor = real_open(name, flags, mode, dir_fd=dir_fd)
        opened.append(_identity(os.fstat(descriptor)))
        return descriptor

    monkeypatch.setattr(os, "open", spy)

    read = read_brain_file(hub, path, max_bytes=LIMIT)
    size = brain_file_size(hub, path)

    assert isinstance(read, UnreadHubFile)
    assert read.kind != "too_large"
    assert size is None
    assert set(opened) <= inside


def _identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino
