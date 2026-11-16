"""Seed units (AGH-227): a workflow pack is seeded whole, only into a hub that never had it."""

import pytest

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.seed_units import held_units, is_held, seed_unit
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, TreeEntry


def an_entry(content: bytes) -> FileEntry:
    return FileEntry(executable=False, content=content)


def a_file(path: str, ownership: Ownership = Ownership.SEEDED) -> RenderedFile:
    return RenderedFile(
        path=path,
        content=b"",
        executable=False,
        kind=Kind.GENERIC,
        ownership=ownership,
        module=None,
    )


RENDERED = RenderedHub(
    files=(a_file("README.md"), a_file("workflows/a/a.yaml"), a_file("workflows/b/b.yaml")),
    links=(),
)


@pytest.mark.parametrize(
    ("path", "unit"),
    [
        ("workflows/a/a.yaml", "workflows/a"),
        ("workflows/a/fixtures/done.yaml", "workflows/a"),
        ("workflows/a", None),
        ("workflows/top.yaml", None),
        ("brain/now.md", None),
    ],
)
def test_names_pack_folder_when_path_lies_inside_a_pack(path: str, unit: str | None) -> None:
    assert seed_unit(path) == unit


def test_holds_unit_when_foreign_file_on_disk_or_path_in_lock() -> None:
    entries = {"workflows/a": FolderEntry(), "workflows/a/mine.yaml": an_entry(b"ours")}

    held = held_units(RENDERED, entries, ["workflows/b/fixtures/x.yaml", "README.md"])

    assert held == frozenset({"workflows/a", "workflows/b"})
    assert is_held("workflows/a/new.yaml", held)
    assert not is_held("README.md", held)


def test_holds_nothing_when_hub_never_had_the_pack() -> None:
    assert held_units(RENDERED, {"workflows": FolderEntry()}, ["README.md"]) == frozenset()


def test_holds_nothing_when_pack_folder_holds_only_render_bytes() -> None:
    entries = {
        "workflows/a": FolderEntry(),
        "workflows/a/a.yaml": an_entry(b""),
        "workflows/b": FolderEntry(),
    }

    assert held_units(RENDERED, entries, ()) == frozenset()


@pytest.mark.parametrize(
    "entries",
    [
        {"workflows/a/a.yaml": FileEntry(executable=False, content=None)},
        {"workflows/a/a.yaml": FileEntry(executable=True, content=b"")},
        {"workflows/a/a.yaml": LinkEntry(target="x", outside=False)},
        {"workflows/a/scripts": FolderEntry()},
    ],
    ids=["unread", "executable", "link", "foreign-folder"],
)
def test_holds_unit_when_pack_folder_holds_anything_else(entries: dict[str, TreeEntry]) -> None:
    assert held_units(RENDERED, entries, ()) == frozenset({"workflows/a"})


def test_ignores_managed_files_when_units_found() -> None:
    rendered = RenderedHub(files=(a_file("workflows/m/m.yaml", Ownership.MANAGED),), links=())

    entries = {"workflows/m/x.yaml": an_entry(b"ours")}

    assert held_units(rendered, entries, ()) == frozenset()
