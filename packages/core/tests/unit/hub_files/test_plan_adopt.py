import hashlib
from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import NO_EXTENSIONS
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    ManagedFileEntry,
    SeededEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_adopt import AdoptPlan, plan_adopt
from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite
from agent_hub.core.hub_files.plan_sync import SyncChange, Verb
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    TreeEntry,
    TreeSnapshot,
)
from agent_hub.core.testing.builders import a_hub_document

type HubFactory = Callable[..., RenderedHub]

FOLDERS = (".claude", ".claude/agents", ".claude/skills", "plugin", "plugin/agents", "scripts")
OLD = b"# Old rules\n"
# The paths of ``a_rendered_hub`` the tests change one thing about.
FILE = "AGENTS.md"
SCRIPT = "scripts/run.sh"
LINK = ".claude/agents/x.md"
SEEDED = "README.md"
SEEDED_LINK = ".claude/skills/y"
PROJECT_AGENTS_KEEP = "plugin/demo/agents/.gitkeep"
PROJECT_SKILLS_KEEP = "plugin/demo/skills/.gitkeep"

CONFIG = HubConfig.model_validate(a_hub_document())


def hand_made_tree(rendered: RenderedHub) -> dict[str, TreeEntry]:
    """A hub built by hand equal to its render, with no ``hub.lock``. Seeded files are not read."""
    entries: dict[str, TreeEntry] = dict.fromkeys(FOLDERS, FolderEntry())
    for file in rendered.files:
        managed = file.ownership is Ownership.MANAGED
        content = file.content if managed else None
        entries[file.path] = FileEntry(executable=file.executable, content=content)
    for link in rendered.links:
        entries[link.path] = LinkEntry(target=link.target, outside=False)
    entries[HUB_JSON_PATH] = FileEntry(executable=False, content=None)
    return entries


def without(entries: Mapping[str, TreeEntry], *paths: str) -> dict[str, TreeEntry]:
    return {path: entry for path, entry in entries.items() if path not in paths}


def adopted(
    rendered: RenderedHub,
    tree: Mapping[str, TreeEntry],
    *,
    lock: HubLock | None = None,
) -> AdoptPlan:
    plan = plan_adopt(
        rendered=rendered,
        config=CONFIG,
        lock=lock,
        lock_content=None if lock is None else lock_bytes(lock),
        tree=TreeSnapshot(entries=dict(tree), git_present=False),
        extensions=NO_EXTENSIONS,
    )
    assert isinstance(plan, AdoptPlan)
    return plan


def written_paths(plan: AdoptPlan) -> list[str]:
    return [write.path for write in plan.writes]


def file_write(rendered: RenderedHub, path: str) -> FileWrite:
    file = next(file for file in rendered.files if file.path == path)
    return FileWrite(path=path, content=file.content, executable=file.executable)


def link_write(rendered: RenderedHub, path: str) -> LinkWrite:
    link = next(link for link in rendered.links if link.path == path)
    return LinkWrite(path=path, target=link.target)


def lock_write(lock: HubLock) -> FileWrite:
    return FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(lock), executable=False)


def seeded_file(path: str) -> RenderedFile:
    return RenderedFile(
        path=path,
        content=b"",
        executable=False,
        kind=Kind.PROJECT_OWNED,
        ownership=Ownership.SEEDED,
        module=None,
    )


@pytest.mark.parametrize("path", [FILE, SCRIPT, LINK])
def test_records_managed_path_when_equal_to_render(a_rendered_hub: HubFactory, path: str) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, hand_made_tree(rendered))

    assert SyncChange(path=path, verb=Verb.RECORDED) in plan.changes
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert plan.lock == build_hub_lock(rendered=rendered, config=CONFIG)
    assert plan.settled


@pytest.mark.parametrize("path", [FILE, SCRIPT])
def test_creates_managed_file_when_absent(a_rendered_hub: HubFactory, path: str) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, without(hand_made_tree(rendered), path))

    assert SyncChange(path=path, verb=Verb.CREATED) in plan.changes
    assert plan.writes == (file_write(rendered, path), lock_write(plan.lock))
    assert isinstance(plan.lock.files[path], ManagedFileEntry)


def test_creates_seeded_file_when_absent(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, without(hand_made_tree(rendered), SEEDED))

    assert SyncChange(path=SEEDED, verb=Verb.CREATED) in plan.changes
    assert plan.writes == (file_write(rendered, SEEDED), lock_write(plan.lock))
    assert plan.lock.files[SEEDED] == SeededEntry(ownership="seeded")


@pytest.mark.parametrize(
    ("path", "on_disk"),
    [
        pytest.param(SEEDED, FileEntry(executable=True, content=b"# Mine\n"), id="file"),
        pytest.param(SEEDED_LINK, LinkEntry(target="../../mine", outside=False), id="link"),
    ],
)
def test_records_seeded_file_when_present(
    a_rendered_hub: HubFactory, path: str, on_disk: TreeEntry
) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, hand_made_tree(rendered) | {path: on_disk})

    assert SyncChange(path=path, verb=Verb.RECORDED) in plan.changes
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert (plan.deletes, plan.leftovers) == ((), ())
    assert plan.lock.files[path] == SeededEntry(ownership="seeded")


def test_writes_gitkeep_when_project_plugin_folder_empty(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub(
        files=[
            *a_rendered_hub().files,
            seeded_file(PROJECT_AGENTS_KEEP),
            seeded_file(PROJECT_SKILLS_KEEP),
        ]
    )
    tree = without(hand_made_tree(rendered), PROJECT_AGENTS_KEEP, PROJECT_SKILLS_KEEP)

    plan = adopted(rendered, tree | {"plugin/demo": FolderEntry()})

    assert plan.folders == ("plugin/demo/agents", "plugin/demo/skills")
    assert written_paths(plan) == [PROJECT_AGENTS_KEEP, PROJECT_SKILLS_KEEP, HUB_LOCK_PATH]
    assert {
        SyncChange(path=PROJECT_AGENTS_KEEP, verb=Verb.CREATED),
        SyncChange(path=PROJECT_SKILLS_KEEP, verb=Verb.CREATED),
    } <= set(plan.changes)


def test_plans_lock_last_when_lock_absent(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, {HUB_JSON_PATH: FileEntry(executable=False, content=None)})

    files = [file_write(rendered, file.path) for file in rendered.files]
    links = [link_write(rendered, link.path) for link in rendered.links]
    assert plan.writes == (*files, *links, lock_write(plan.lock))
    assert plan.lock_written
    assert plan.pending
    assert plan.folders == FOLDERS
    assert [change.verb for change in plan.changes] == [Verb.CREATED] * 6
    assert [change.path for change in plan.changes] == sorted(written_paths(plan)[:-1])


def locked_with_old_file(rendered: RenderedHub) -> HubLock:
    """The lock of ``rendered``, with ``FILE``'s entry recording the older content ``OLD``."""
    lock = build_hub_lock(rendered=rendered, config=CONFIG)
    sha256 = hashlib.sha256(OLD).hexdigest()
    old_entry = ManagedFileEntry(ownership="managed", sha256=sha256, executable=False)
    return lock.model_copy(update={"files": {**lock.files, FILE: old_entry}})


@pytest.mark.parametrize(
    ("on_disk", "changes"),
    [
        pytest.param(
            FileEntry(executable=False, content=OLD),
            (SyncChange(path=FILE, verb=Verb.UPDATED),),
            id="equal-to-entry",
        ),
        pytest.param(None, (SyncChange(path=FILE, verb=Verb.RESTORED),), id="absent"),
        pytest.param(FileEntry(executable=False, content=b"# Rules\n"), (), id="equal-to-render"),
    ],
)
def test_follows_sync_rule_when_path_has_lock_entry(
    a_rendered_hub: HubFactory,
    on_disk: TreeEntry | None,
    changes: tuple[SyncChange, ...],
) -> None:
    rendered = a_rendered_hub()
    lock = locked_with_old_file(rendered)
    tree = without(hand_made_tree(rendered), FILE)
    if on_disk is not None:
        tree[FILE] = on_disk

    plan = adopted(rendered, tree, lock=lock)

    assert [change for change in plan.changes if change.path == FILE] == list(changes)
    written = [FILE] if changes else []
    assert written_paths(plan) == [*written, HUB_LOCK_PATH]
    assert plan.lock == build_hub_lock(rendered=rendered, config=CONFIG)
