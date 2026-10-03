import hashlib
from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import NO_EXTENSIONS, ExtensionInputs
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    ManagedFileEntry,
    SeededEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_adopt import (
    AdoptPlan,
    ContentDifference,
    LinkDifference,
    ListedKind,
    plan_adopt,
)
from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite, PathProblem
from agent_hub.core.hub_files.plan_sync import ContentConflict, SyncChange, SyncProblem, Verb
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
MINE = b"# My rules\n"
# The paths of ``a_rendered_hub`` the tests change one thing about.
FILE = "AGENTS.md"
SCRIPT = "scripts/run.sh"
LINK = ".claude/agents/x.md"
LINK_TARGET = "../../plugin/agents/x.md"
MY_TARGET = "../../plugin/agents/mine.md"
GONE = "docs/old.md"
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
    extensions: ExtensionInputs = NO_EXTENSIONS,
) -> AdoptPlan:
    plan = plan_adopt(
        rendered=rendered,
        config=CONFIG,
        lock=lock,
        lock_content=None if lock is None else lock_bytes(lock),
        tree=TreeSnapshot(entries=dict(tree), git_present=False),
        extensions=extensions,
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


def changed_paths(plan: AdoptPlan) -> set[str]:
    return {change.path for change in plan.changes}


def lock_without(rendered: RenderedHub, *paths: str) -> HubLock:
    """The lock of ``rendered`` without ``paths``: what adopt saves when they are unsettled."""
    lock = build_hub_lock(rendered=rendered, config=CONFIG)
    files = {path: entry for path, entry in lock.files.items() if path not in paths}
    return lock.model_copy(update={"files": files})


@pytest.mark.parametrize(
    ("path", "on_disk", "difference"),
    [
        pytest.param(
            FILE,
            FileEntry(executable=False, content=MINE),
            ContentDifference(
                path=FILE,
                on_disk=MINE,
                render=b"# Rules\n",
                on_disk_executable=False,
                render_executable=False,
            ),
            id="bytes",
        ),
        pytest.param(
            SCRIPT,
            FileEntry(executable=False, content=b"#!/bin/sh\n"),
            ContentDifference(
                path=SCRIPT,
                on_disk=b"#!/bin/sh\n",
                render=b"#!/bin/sh\n",
                on_disk_executable=False,
                render_executable=True,
            ),
            id="executable-bit-only",
        ),
        pytest.param(
            LINK,
            LinkEntry(target=MY_TARGET, outside=False),
            LinkDifference(path=LINK, on_disk_target=MY_TARGET, render_target=LINK_TARGET),
            id="link-target",
        ),
    ],
)
def test_lists_difference_when_managed_file_differs(
    a_rendered_hub: HubFactory,
    path: str,
    *,
    on_disk: TreeEntry,
    difference: ContentDifference | LinkDifference,
) -> None:
    rendered = a_rendered_hub()

    plan = adopted(rendered, hand_made_tree(rendered) | {path: on_disk})

    assert plan.listed == (difference,)
    assert plan.conflicts == ()
    assert not plan.settled
    assert path not in changed_paths(plan)
    assert written_paths(plan) == [HUB_LOCK_PATH]


@pytest.mark.parametrize(
    ("listed", "kind"),
    [
        pytest.param(ContentDifference, ListedKind.CONTENT, id="content"),
        pytest.param(LinkDifference, ListedKind.LINK, id="link"),
    ],
)
def test_names_kind_when_difference_listed(
    listed: type[ContentDifference | LinkDifference], kind: ListedKind
) -> None:
    assert listed.kind is kind


def test_keeps_listed_path_out_of_lock_when_differs(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()
    tree = hand_made_tree(rendered) | {
        FILE: FileEntry(executable=False, content=MINE),
        LINK: LinkEntry(target=MY_TARGET, outside=False),
    }

    plan = adopted(rendered, tree)

    assert FILE not in plan.lock.files
    assert LINK not in plan.lock.files
    assert plan.lock == lock_without(rendered, FILE, LINK)


# The conflicts adopt cannot settle, each with sync's cause. ``held`` is the path the conflict
# keeps from being written and recorded; ``created`` the absent paths still created.
NOT_ADOPTABLE = [
    pytest.param(
        {LINK: FileEntry(executable=False, content=b"agent x\n")},
        (),
        NO_EXTENSIONS,
        PathProblem(LINK, "a file where a link belongs"),
        (),
        id="file-where-link-rendered",
    ),
    pytest.param(
        {FILE: LinkEntry(target="docs/AGENTS.md", outside=False)},
        (),
        NO_EXTENSIONS,
        PathProblem(FILE, "a link where a file belongs"),
        (),
        id="link-where-file-rendered",
    ),
    pytest.param(
        {"scripts": LinkEntry(target="../tools", outside=False)},
        (SCRIPT,),
        NO_EXTENSIONS,
        PathProblem(SCRIPT, "symlinked ancestor scripts"),
        (),
        id="symlinked-ancestor-not-link-folder",
    ),
    pytest.param(
        {LINK: LinkEntry(target="../../../../etc/x.md", outside=True)},
        (),
        NO_EXTENSIONS,
        PathProblem(LINK, "resolves outside the hub"),
        (),
        id="link-resolves-outside",
    ),
    # An exact name clash holds the base link back, even though it would be created.
    pytest.param(
        {},
        (LINK,),
        ExtensionInputs(project_json={}, agents=("x.md",), skills=()),
        PathProblem(LINK, "in both plugins (plugin/agents/x.md and plugin/demo/agents/x.md)"),
        (),
        id="name-in-both-plugins",
    ),
    # Current behaviour: a clash by case or Unicode form names the project's path, which is not
    # rendered (``project_links``), so the base link stays settled and is created.
    pytest.param(
        {},
        (LINK,),
        ExtensionInputs(project_json={}, agents=("X.md",), skills=()),
        PathProblem(
            ".claude/agents/X.md",
            "in both plugins (plugin/agents/x.md and plugin/demo/agents/X.md)",
        ),
        (LINK,),
        id="name-in-both-plugins-by-case",
    ),
]


@pytest.mark.parametrize(("changed", "removed", "extensions", "conflict", "created"), NOT_ADOPTABLE)
def test_lists_conflict_when_kind_not_adoptable(
    a_rendered_hub: HubFactory,
    changed: Mapping[str, TreeEntry],
    *,
    removed: tuple[str, ...],
    extensions: ExtensionInputs,
    conflict: SyncProblem,
    created: tuple[str, ...],
) -> None:
    rendered = a_rendered_hub()
    tree = without(hand_made_tree(rendered), *removed) | dict(changed)

    plan = adopted(rendered, tree, extensions=extensions)

    assert plan.conflicts == (conflict,)
    assert plan.listed == ()
    held = conflict.path
    assert held not in written_paths(plan)
    assert held not in changed_paths(plan)
    assert held not in plan.lock.files
    assert [change for change in plan.changes if change.verb is not Verb.RECORDED] == [
        SyncChange(path=path, verb=Verb.CREATED) for path in created
    ]
    assert written_paths(plan) == [*created, HUB_LOCK_PATH]
    held_by_lock = {held, *removed} - set(created)
    assert plan.lock == lock_without(rendered, *held_by_lock)


def test_lists_only_conflict_when_differing_link_also_clashes(a_rendered_hub: HubFactory) -> None:
    """A conflict wins over a difference: ``--accept`` takes only what is listed."""
    rendered = a_rendered_hub()
    tree = hand_made_tree(rendered) | {LINK: LinkEntry(target=MY_TARGET, outside=False)}
    extensions = ExtensionInputs(project_json={}, agents=("x.md",), skills=())

    plan = adopted(rendered, tree, extensions=extensions)

    assert plan.listed == ()
    assert [problem.path for problem in plan.conflicts] == [LINK]
    assert plan.lock == lock_without(rendered, LINK)


def test_saves_settled_lock_when_something_listed(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()
    tree = without(hand_made_tree(rendered), SCRIPT) | {
        FILE: FileEntry(executable=False, content=MINE)
    }

    plan = adopted(rendered, tree)

    assert [listed.path for listed in plan.listed] == [FILE]
    assert plan.lock == lock_without(rendered, FILE)
    assert plan.writes == (file_write(rendered, SCRIPT), lock_write(plan.lock))
    assert plan.lock_written
    assert SyncChange(path=SCRIPT, verb=Verb.CREATED) in plan.changes


def gone_entry() -> ManagedFileEntry:
    return ManagedFileEntry(
        ownership="managed", sha256=hashlib.sha256(OLD).hexdigest(), executable=False
    )


@pytest.mark.parametrize(
    ("path", "on_disk", "conflict"),
    [
        pytest.param(
            FILE,
            FileEntry(executable=False, content=MINE),
            ContentConflict(path=FILE, on_disk=MINE, render=b"# Rules\n"),
            id="rendered",
        ),
        pytest.param(
            GONE,
            FileEntry(executable=False, content=MINE),
            PathProblem(GONE, "differs from its hub.lock entry and is no longer rendered"),
            id="no-longer-rendered",
        ),
    ],
)
def test_keeps_previous_entry_when_locked_path_conflicts(
    a_rendered_hub: HubFactory, path: str, *, on_disk: TreeEntry, conflict: SyncProblem
) -> None:
    rendered = a_rendered_hub()
    old_lock = locked_with_old_file(rendered)
    lock = old_lock.model_copy(update={"files": {**old_lock.files, GONE: gone_entry()}})
    tree = without(hand_made_tree(rendered), SCRIPT) | {
        FILE: FileEntry(executable=False, content=OLD),
        GONE: FileEntry(executable=False, content=OLD),
        "docs": FolderEntry(),
        path: on_disk,
    }

    plan = adopted(rendered, tree, lock=lock)

    assert plan.conflicts == (conflict,)
    assert plan.lock.files[path] == lock.files[path]
    settled = build_hub_lock(rendered=rendered, config=CONFIG).files
    expected = {k: v for k, v in settled.items() if k != path} | {path: lock.files[path]}
    assert plan.lock.files == dict(sorted(expected.items()))
    assert SyncChange(path=SCRIPT, verb=Verb.RESTORED) in plan.changes
    assert SCRIPT in written_paths(plan)
    assert written_paths(plan)[-1] == HUB_LOCK_PATH


def test_plans_nothing_when_hub_adopted_and_clean(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()
    lock = build_hub_lock(rendered=rendered, config=CONFIG)

    plan = adopted(rendered, hand_made_tree(rendered), lock=lock)

    assert not plan.pending
    assert not plan.lock_written
    assert plan.writes == ()
    assert plan.changes == ()
    assert plan.settled
    assert plan.lock == lock


def test_returns_same_plan_when_inputs_repeat(a_rendered_hub: HubFactory) -> None:
    rendered = a_rendered_hub()
    tree = without(hand_made_tree(rendered), SCRIPT) | {
        FILE: FileEntry(executable=False, content=MINE),
        LINK: LinkEntry(target=MY_TARGET, outside=False),
        SEEDED_LINK: LinkEntry(target="../../../../etc", outside=True),
    }
    extensions = ExtensionInputs(project_json={}, agents=("X.md",), skills=())

    first = adopted(rendered, tree, extensions=extensions)
    again = adopted(rendered, dict(reversed(tree.items())), extensions=extensions)

    assert first == again
    assert [listed.path for listed in first.listed] == [LINK, FILE]
    assert [problem.path for problem in first.conflicts] == [".claude/agents/X.md", SEEDED_LINK]
