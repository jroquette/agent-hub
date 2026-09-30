import hashlib
import json
import re
from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    LockEntry,
    ManagedFileEntry,
    ManagedLinkEntry,
    SeededEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite, PathProblem
from agent_hub.core.hub_files.plan_sync import (
    ContentConflict,
    SyncChange,
    SyncConflicts,
    SyncPlan,
    Verb,
    plan_sync,
)
from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
)
from agent_hub.core.testing.builders import a_hub_document

type HubFactory = Callable[..., RenderedHub]

FOLDERS = (".claude", ".claude/agents", ".claude/skills", "plugin", "plugin/agents", "scripts")
OLD = b"# Old rules\n"
# The rendered managed file and link of ``a_rendered_hub`` each test changes one thing about.
FILE = "AGENTS.md"
LINK = ".claude/agents/x.md"
LINK_TARGET = "../../plugin/agents/x.md"
OLD_TARGET = "../../plugin/agents/old.md"
SEEDED = "README.md"
SEEDED_LINK = ".claude/skills/y"
LEFTOVER = "plugin/.x.md.hub-tmp-0123abcd"


CONFIG = HubConfig.model_validate(a_hub_document())


@pytest.fixture
def config() -> HubConfig:
    return CONFIG


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def old_file_entry() -> ManagedFileEntry:
    return ManagedFileEntry(ownership="managed", sha256=sha256(OLD), executable=False)


def old_link_entry() -> ManagedLinkEntry:
    return ManagedLinkEntry(ownership="managed", symlink=OLD_TARGET)


def seeded_entry() -> SeededEntry:
    return SeededEntry(ownership="seeded")


def synced_tree(rendered: RenderedHub) -> dict[str, TreeEntry]:
    """The tree a finished sync leaves. Seeded files and ``hub.json`` are not read (no content)."""
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


def a_tree(entries: Mapping[str, TreeEntry]) -> TreeSnapshot:
    return TreeSnapshot(entries=dict(entries), git_present=False)


def a_lock(
    rendered: RenderedHub,
    config: HubConfig,
    *,
    files: Mapping[str, LockEntry | None] | None = None,
    **header: object,
) -> HubLock:
    """The lock of ``rendered``, with entries replaced (``None`` removes one) or header fields."""
    lock = build_hub_lock(rendered=rendered, config=config)
    entries = dict(lock.files)
    for path, entry in (files or {}).items():
        if entry is None:
            entries.pop(path)
        else:
            entries[path] = entry
    return lock.model_copy(update={"files": dict(sorted(entries.items())), **header})


def run(
    rendered: RenderedHub,
    lock: HubLock,
    tree: Mapping[str, TreeEntry],
    *,
    lock_content: bytes | None = None,
) -> SyncPlan | SyncConflicts:
    content = lock_bytes(lock) if lock_content is None else lock_content
    return plan_sync(
        rendered=rendered, config=CONFIG, lock=lock, lock_content=content, tree=a_tree(tree)
    )


def planned(
    rendered: RenderedHub,
    lock: HubLock,
    tree: Mapping[str, TreeEntry],
    *,
    lock_content: bytes | None = None,
) -> SyncPlan:
    plan = run(rendered, lock, tree, lock_content=lock_content)
    assert isinstance(plan, SyncPlan)
    return plan


def written_paths(plan: SyncPlan) -> list[str]:
    return [write.path for write in plan.writes]


def lock_write(lock: HubLock) -> FileWrite:
    return FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(lock), executable=False)


def file_write(rendered: RenderedHub, path: str) -> FileWrite:
    file = next(file for file in rendered.files if file.path == path)
    return FileWrite(path=path, content=file.content, executable=file.executable)


def link_write(rendered: RenderedHub, path: str) -> LinkWrite:
    link = next(link for link in rendered.links if link.path == path)
    return LinkWrite(path=path, target=link.target)


@pytest.mark.parametrize(
    ("path", "old_entry"),
    [
        pytest.param(FILE, None, id="file-no-entry"),
        pytest.param(FILE, seeded_entry(), id="file-seeded-entry"),
        pytest.param(FILE, old_file_entry(), id="file-other-hash"),
        pytest.param(LINK, None, id="link-no-entry"),
        pytest.param(LINK, seeded_entry(), id="link-seeded-entry"),
        pytest.param(LINK, old_link_entry(), id="link-other-target"),
    ],
)
def test_records_path_when_disk_equals_render(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, old_entry: LockEntry | None
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    plan = planned(rendered, lock, synced_tree(rendered))

    assert plan.changes == ()
    assert plan.deletes == ()
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert plan.lock == build_hub_lock(rendered=rendered, config=config)


@pytest.mark.parametrize(
    ("path", "old_entry", "on_disk", "write"),
    [
        pytest.param(
            FILE,
            old_file_entry(),
            FileEntry(executable=False, content=OLD),
            FileWrite(path=FILE, content=b"# Rules\n", executable=False),
            id="file",
        ),
        pytest.param(
            LINK,
            old_link_entry(),
            LinkEntry(target=OLD_TARGET, outside=False),
            LinkWrite(path=LINK, target=LINK_TARGET),
            id="link",
        ),
    ],
)
def test_updates_managed_when_disk_equals_entry(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    old_entry: LockEntry,
    on_disk: TreeEntry,
    write: FileWrite | LinkWrite,
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    plan = planned(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert plan.changes == (SyncChange(path=path, verb=Verb.UPDATED),)
    assert plan.writes == (write, lock_write(plan.lock))


@pytest.mark.parametrize("path", [FILE, LINK])
def test_restores_managed_when_entry_present_and_disk_absent(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config)

    plan = planned(rendered, lock, without(synced_tree(rendered), path))

    assert plan.changes == (SyncChange(path=path, verb=Verb.RESTORED),)
    assert written_paths(plan) == [path]
    assert not plan.lock_written


@pytest.mark.parametrize("path", [FILE, LINK])
@pytest.mark.parametrize("old_entry", [None, seeded_entry()], ids=["no-entry", "seeded-entry"])
def test_creates_managed_when_no_entry_and_disk_absent(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, old_entry: LockEntry | None
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    plan = planned(rendered, lock, without(synced_tree(rendered), path))

    assert plan.changes == (SyncChange(path=path, verb=Verb.CREATED),)
    assert written_paths(plan) == [path, HUB_LOCK_PATH]


@pytest.mark.parametrize(
    ("path", "old_entry", "on_disk"),
    [
        pytest.param(
            "old.md", old_file_entry(), FileEntry(executable=False, content=OLD), id="file"
        ),
        pytest.param(
            ".claude/agents/old.md",
            old_link_entry(),
            LinkEntry(target=OLD_TARGET, outside=False),
            id="link",
        ),
    ],
)
def test_deletes_when_entry_no_longer_rendered_and_disk_equal(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    old_entry: LockEntry,
    on_disk: TreeEntry,
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    plan = planned(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert plan.deletes == (path,)
    assert plan.changes == (SyncChange(path=path, verb=Verb.DELETED),)
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert path not in plan.lock.files


@pytest.mark.parametrize(
    ("path", "old_entry"),
    [
        pytest.param("old.md", old_file_entry(), id="file"),
        pytest.param(".claude/agents/old.md", old_link_entry(), id="link"),
    ],
)
def test_drops_entry_when_no_longer_rendered_and_gone(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, old_entry: LockEntry
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    plan = planned(rendered, lock, synced_tree(rendered))

    assert (plan.changes, plan.deletes) == ((), ())
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert path not in plan.lock.files


@pytest.mark.parametrize("path", [SEEDED, SEEDED_LINK])
def test_creates_seeded_when_absent_and_no_entry(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: None})

    plan = planned(rendered, lock, without(synced_tree(rendered), path))

    assert plan.changes == (SyncChange(path=path, verb=Verb.CREATED),)
    assert written_paths(plan) == [path, HUB_LOCK_PATH]
    assert plan.lock.files[path] == seeded_entry()


@pytest.mark.parametrize(
    ("path", "on_disk"),
    [
        pytest.param(SEEDED, FileEntry(executable=True, content=None), id="file"),
        pytest.param(SEEDED_LINK, LinkEntry(target="../../elsewhere", outside=False), id="link"),
    ],
)
def test_records_seeded_when_present_and_no_entry(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, on_disk: TreeEntry
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: None})

    plan = planned(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert plan.changes == ()
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert plan.lock.files[path] == seeded_entry()


@pytest.mark.parametrize("path", [SEEDED, SEEDED_LINK])
def test_leaves_seeded_when_entry_seeded_and_absent(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config)

    plan = planned(rendered, lock, without(synced_tree(rendered), path))

    assert plan.changes == ()
    assert plan.writes == ()


def test_drops_seeded_entry_when_no_longer_rendered(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={"notes.md": seeded_entry()})
    tree = synced_tree(rendered) | {"notes.md": FileEntry(executable=False, content=None)}

    plan = planned(rendered, lock, tree)

    assert (plan.changes, plan.deletes) == ((), ())
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert "notes.md" not in plan.lock.files


@pytest.mark.parametrize(
    "on_disk",
    [FileEntry(executable=False, content=None), None],
    ids=["present", "absent"],
)
def test_records_seeded_when_managed_entry_now_seeded(
    a_rendered_hub: HubFactory, config: HubConfig, on_disk: TreeEntry | None
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={SEEDED: old_file_entry()})
    tree = without(synced_tree(rendered), SEEDED)
    if on_disk is not None:
        tree[SEEDED] = on_disk

    plan = planned(rendered, lock, tree)

    assert plan.changes == ()
    assert written_paths(plan) == [HUB_LOCK_PATH]
    assert plan.lock.files[SEEDED] == seeded_entry()


@pytest.mark.parametrize(
    "header",
    [{"platform_version": "0.1.0"}, {"schema_version": 2}, {"modules": ("bench",)}],
    ids=["platform_version", "schema_version", "modules"],
)
def test_rewrites_only_lock_when_header_differs(
    a_rendered_hub: HubFactory, config: HubConfig, header: dict[str, object]
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, **header)

    plan = planned(rendered, lock, synced_tree(rendered))

    assert plan.writes == (lock_write(build_hub_lock(rendered=rendered, config=config)),)
    assert (plan.changes, plan.deletes, plan.folders, plan.leftovers) == ((), (), (), ())
    assert plan.lock_written


def test_rewrites_only_lock_when_bytes_differ_but_model_equal(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config)
    reformatted = json.dumps(json.loads(lock_bytes(lock)), indent=4).encode()

    plan = planned(rendered, lock, synced_tree(rendered), lock_content=reformatted)

    assert plan.writes == (lock_write(lock),)
    assert plan.changes == ()


def test_rewrites_only_lock_when_hub_json_entry_missing(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={HUB_JSON_PATH: None})

    plan = planned(rendered, lock, synced_tree(rendered))

    assert plan.writes == (lock_write(build_hub_lock(rendered=rendered, config=config)),)
    assert plan.changes == ()
    assert plan.lock.files[HUB_JSON_PATH] == seeded_entry()


def test_never_deletes_hub_json_when_lock_records_it_managed(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    """``read_hub_lock`` refuses such a lock; the planner does not rely on it (E1)."""
    rendered = a_rendered_hub()
    hub_json = b'{"project": "demo"}\n'
    entry = ManagedFileEntry(ownership="managed", sha256=sha256(hub_json), executable=False)
    lock = a_lock(rendered, config, files={HUB_JSON_PATH: entry})
    tree = synced_tree(rendered) | {HUB_JSON_PATH: FileEntry(executable=False, content=hub_json)}

    plan = planned(rendered, lock, tree)

    assert (plan.changes, plan.deletes) == ((), ())
    assert plan.lock.files[HUB_JSON_PATH] == seeded_entry()


def test_returns_empty_plan_when_nothing_differs(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()

    plan = planned(rendered, a_lock(rendered, config), synced_tree(rendered))

    assert plan == SyncPlan(
        leftovers=(),
        deletes=(),
        folders=(),
        writes=(),
        changes=(),
        lock=build_hub_lock(rendered=rendered, config=config),
        lock_written=False,
    )
    assert not plan.pending


@pytest.mark.parametrize("header", [{}, {"platform_version": "0.1.0"}], ids=["same", "other"])
def test_builds_lock_from_render_when_plan_accepted(
    a_rendered_hub: HubFactory, config: HubConfig, header: dict[str, object]
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, **header)

    plan = planned(rendered, lock, without(synced_tree(rendered), FILE))

    assert plan.lock == build_hub_lock(rendered=rendered, config=config)
    assert plan.lock_written is bool(header)
    assert (plan.writes[-1] == lock_write(plan.lock)) is bool(header)
    assert plan.pending


def test_orders_writes_files_links_then_lock_when_planned(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={SEEDED: None, SEEDED_LINK: None})

    plan = planned(rendered, lock, {})

    assert plan.writes == (
        file_write(rendered, FILE),
        file_write(rendered, SEEDED),
        file_write(rendered, "plugin/agents/x.md"),
        file_write(rendered, "scripts/run.sh"),
        link_write(rendered, LINK),
        link_write(rendered, SEEDED_LINK),
        lock_write(plan.lock),
    )
    assert [change.path for change in plan.changes] == sorted(written_paths(plan)[:-1])


def test_creates_only_missing_folders_when_writing(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    tree = without(
        synced_tree(rendered),
        ".claude/agents",
        LINK,
        "plugin",
        "plugin/agents",
        "plugin/agents/x.md",
        "scripts/run.sh",
    )

    plan = planned(rendered, a_lock(rendered, config), tree)

    # ``scripts`` is there already.
    assert plan.folders == (".claude/agents", "plugin", "plugin/agents")


def test_skips_missing_folder_when_nothing_written_below(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    # The seeded link keeps its entry, so nothing is written under the missing ``.claude/skills``.
    tree = without(synced_tree(rendered), ".claude/skills", SEEDED_LINK, FILE)

    plan = planned(rendered, a_lock(rendered, config), tree)

    assert written_paths(plan) == [FILE]
    assert plan.folders == ()


@pytest.mark.parametrize(
    "on_disk",
    [FileEntry(executable=False, content=None), LinkEntry(target="x.md", outside=False)],
    ids=["file", "link"],
)
def test_cleans_leftover_when_temp_shaped_entry_listed(
    a_rendered_hub: HubFactory, config: HubConfig, on_disk: TreeEntry
) -> None:
    rendered = a_rendered_hub()
    tree = synced_tree(rendered) | {LEFTOVER: on_disk}

    plan = planned(rendered, a_lock(rendered, config), tree)

    assert plan.leftovers == (LEFTOVER,)
    assert (plan.writes, plan.changes) == ((), ())
    assert plan.pending


def test_sorts_leftovers_and_deletes_when_listed_in_reverse(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={"a.md": old_file_entry(), "b.md": old_file_entry()})
    lock = lock.model_copy(update={"files": dict(reversed(lock.files.items()))})
    other = "plugin/.y.md.hub-tmp-89abcdef"
    tree = {
        other: FileEntry(executable=False, content=None),
        LEFTOVER: FileEntry(executable=False, content=None),
        "b.md": FileEntry(executable=False, content=OLD),
        "a.md": FileEntry(executable=False, content=OLD),
        **synced_tree(rendered),
    }

    plan = planned(rendered, lock, tree)

    assert plan.leftovers == (LEFTOVER, other)
    assert plan.deletes == ("a.md", "b.md")


def test_keeps_lock_entry_path_when_named_like_leftover(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    """A path the lock records is planned (a seeded one is kept, not deleted), never a leftover,
    whatever its name."""
    rendered = a_rendered_hub()
    path = ".a.hub-tmp-01234567"
    lock = a_lock(rendered, config, files={path: seeded_entry()})
    tree = synced_tree(rendered) | {path: FileEntry(executable=False, content=None)}

    plan = planned(rendered, lock, tree)

    assert plan.leftovers == ()
    assert plan.deletes == ()


def test_keeps_folder_when_named_like_leftover(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    tree = synced_tree(rendered) | {LEFTOVER: FolderEntry()}

    plan = planned(rendered, a_lock(rendered, config), tree)

    assert plan.leftovers == ()
    assert not plan.pending


@pytest.mark.parametrize("path", [HUB_JSON_PATH, HUB_LOCK_PATH])
@pytest.mark.parametrize("as_link", [False, True], ids=["file", "link"])
def test_raises_when_render_holds_hub_json_or_lock(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, as_link: bool
) -> None:
    common = {"kind": Kind.GENERIC, "ownership": Ownership.MANAGED, "module": None}
    if as_link:
        rendered = a_rendered_hub(links=[RenderedLink(path=path, target="AGENTS.md", **common)])
    else:
        rendered = a_rendered_hub(
            files=[RenderedFile(path=path, content=b"{}\n", executable=False, **common)]
        )
    lock = build_hub_lock(rendered=a_rendered_hub(), config=config)

    with pytest.raises(ValueError, match=re.escape(path)):
        run(rendered, lock, {})


@pytest.mark.parametrize(
    ("path", "old_entry"),
    [
        pytest.param(FILE, None, id="rendered-managed"),
        pytest.param("old.md", old_file_entry(), id="managed-entry-no-longer-rendered"),
    ],
)
def test_raises_when_compared_content_not_read(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, old_entry: LockEntry | None
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry} if old_entry else None)
    tree = synced_tree(rendered) | {path: FileEntry(executable=False, content=None)}

    with pytest.raises(ValueError, match=re.escape(f"{path}: content was not read")):
        run(rendered, lock, tree)


# Conflicts (AC-14.6): each test's input is decided by the one rule it names.

EDITED = b"# Edited rules\n"
RULES = b"# Rules\n"
ELSEWHERE = "../../elsewhere"
OLD_FILE = "old.md"
OLD_LINK = ".claude/agents/old.md"
NO_LONGER_RENDERED = "differs from its hub.lock entry and is no longer rendered"


def conflicts(
    rendered: RenderedHub, lock: HubLock, tree: Mapping[str, TreeEntry]
) -> tuple[PathProblem | ContentConflict, ...]:
    result = run(rendered, lock, tree)
    assert isinstance(result, SyncConflicts)
    return result.problems


def test_carries_contents_when_managed_bytes_differ_from_entry_and_render(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={FILE: old_file_entry()})
    tree = synced_tree(rendered) | {FILE: FileEntry(executable=False, content=EDITED)}

    problems = conflicts(rendered, lock, tree)

    assert problems == (ContentConflict(path=FILE, on_disk=EDITED, render=RULES),)


@pytest.mark.parametrize(
    ("path", "content", "on_disk_bit", "cause"),
    [
        pytest.param(
            FILE, RULES, True, "executable bit differs (on disk +x, render -x)", id="gained-x"
        ),
        pytest.param(
            "scripts/run.sh",
            b"#!/bin/sh\n",
            False,
            "executable bit differs (on disk -x, render +x)",
            id="lost-x",
        ),
    ],
)
def test_names_bit_when_only_executable_bit_differs(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    content: bytes,
    on_disk_bit: bool,
    cause: str,
) -> None:
    rendered = a_rendered_hub()
    tree = synced_tree(rendered) | {path: FileEntry(executable=on_disk_bit, content=content)}

    problems = conflicts(rendered, a_lock(rendered, config), tree)

    assert problems == (PathProblem(path, cause),)


def test_names_targets_when_link_differs_from_entry_and_render(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={LINK: old_link_entry()})
    tree = synced_tree(rendered) | {LINK: LinkEntry(target=ELSEWHERE, outside=False)}

    problems = conflicts(rendered, lock, tree)

    cause = f"link target differs (on disk -> {ELSEWHERE}, render -> {LINK_TARGET})"
    assert problems == (PathProblem(LINK, cause),)


@pytest.mark.parametrize("old_entry", [None, seeded_entry()], ids=["no-entry", "seeded-entry"])
@pytest.mark.parametrize(
    ("path", "on_disk", "expected"),
    [
        pytest.param(
            FILE,
            FileEntry(executable=False, content=OLD),
            ContentConflict(path=FILE, on_disk=OLD, render=RULES),
            id="file",
        ),
        pytest.param(
            LINK,
            LinkEntry(target=OLD_TARGET, outside=False),
            PathProblem(
                LINK, f"link target differs (on disk -> {OLD_TARGET}, render -> {LINK_TARGET})"
            ),
            id="link",
        ),
    ],
)
def test_reports_managed_on_disk_when_no_managed_entry(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    old_entry: LockEntry | None,
    on_disk: TreeEntry,
    expected: PathProblem | ContentConflict,
) -> None:
    """The disk is not what a sync wrote: the old hash or target is not trusted without an entry."""
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    problems = conflicts(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert problems == (expected,)


@pytest.mark.parametrize(
    ("path", "old_entry", "on_disk"),
    [
        pytest.param(
            OLD_FILE, old_file_entry(), FileEntry(executable=False, content=EDITED), id="bytes"
        ),
        pytest.param(OLD_FILE, old_file_entry(), FileEntry(executable=True, content=OLD), id="bit"),
        pytest.param(
            OLD_LINK, old_link_entry(), LinkEntry(target=ELSEWHERE, outside=False), id="target"
        ),
    ],
)
def test_reports_no_longer_rendered_when_disk_differs_from_entry(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    old_entry: LockEntry,
    on_disk: TreeEntry,
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    problems = conflicts(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert problems == (PathProblem(path, NO_LONGER_RENDERED),)


@pytest.mark.parametrize(
    ("path", "old_entry", "on_disk", "cause"),
    [
        pytest.param(
            LINK,
            old_file_entry(),
            FileEntry(executable=False, content=OLD),
            "a file where a link belongs",
            id="file-where-link",
        ),
        pytest.param(
            LINK, None, FolderEntry(), "a folder where a link belongs", id="folder-where-link"
        ),
        pytest.param(
            FILE,
            old_link_entry(),
            LinkEntry(target=OLD_TARGET, outside=False),
            "a link where a file belongs",
            id="link-where-file",
        ),
        pytest.param(
            FILE,
            old_file_entry(),
            OtherEntry(kind="fifo"),
            "not a regular file",
            id="other-where-file",
        ),
    ],
)
def test_reports_type_when_kind_differs_even_if_equal_to_entry(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    old_entry: LockEntry | None,
    on_disk: TreeEntry,
    cause: str,
) -> None:
    """A path whose rendered type changed is never replaced, even when a sync wrote it (Q-16)."""
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})

    problems = conflicts(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert problems == (PathProblem(path, cause),)


def test_restores_when_rendered_type_changed_and_path_absent(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    """Nothing on disk to protect: the managed entry of the old type is restored as the new one."""
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={LINK: old_file_entry()})

    plan = planned(rendered, lock, without(synced_tree(rendered), LINK))

    assert plan.changes == (SyncChange(path=LINK, verb=Verb.RESTORED),)
    assert written_paths(plan) == [LINK, HUB_LOCK_PATH]


@pytest.mark.parametrize(
    ("path", "on_disk", "cause"),
    [
        pytest.param(
            SEEDED,
            LinkEntry(target=ELSEWHERE, outside=False),
            "a link where a file belongs",
            id="link-where-file",
        ),
        pytest.param(SEEDED, FolderEntry(), "a folder where a file belongs", id="folder"),
        pytest.param(SEEDED, OtherEntry(kind="fifo"), "not a regular file", id="fifo"),
        pytest.param(
            SEEDED_LINK,
            FileEntry(executable=False, content=None),
            "a file where a link belongs",
            id="file-where-link",
        ),
    ],
)
def test_reports_type_when_seeded_without_entry_is_not_a_file(
    a_rendered_hub: HubFactory, config: HubConfig, path: str, *, on_disk: TreeEntry, cause: str
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: None})

    problems = conflicts(rendered, lock, synced_tree(rendered) | {path: on_disk})

    assert problems == (PathProblem(path, cause),)


@pytest.mark.parametrize(
    ("path", "link", "old_entry"),
    [
        pytest.param("plugin/agents/x.md", "plugin", None, id="write-created"),
        pytest.param("plugin/agents/x.md", "plugin/agents", old_file_entry(), id="write-restored"),
        pytest.param("old/x.md", "old", old_file_entry(), id="delete"),
        pytest.param(SEEDED_LINK, ".claude/skills", None, id="write-seeded-no-entry"),
    ],
)
def test_reports_symlinked_ancestor_when_ancestor_is_link(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    link: str,
    old_entry: LockEntry | None,
) -> None:
    """The reader never descends into a link: ``path`` itself is absent from the tree."""
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})
    tree = {
        each: entry
        for each, entry in synced_tree(rendered).items()
        if each != link and not each.startswith(f"{link}/")
    }
    tree[link] = LinkEntry(target=ELSEWHERE, outside=False)

    problems = conflicts(rendered, lock, tree)

    assert problems == (PathProblem(path, f"symlinked ancestor {link}"),)


def test_reports_file_ancestor_when_ancestor_planned_for_delete(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    """Q-13: a delete does not clear the way for a write below it; the user deletes and re-runs."""
    base = a_rendered_hub()
    extra = RenderedFile(
        path="docs/x.md",
        content=RULES,
        executable=False,
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )
    rendered = a_rendered_hub(files=[*base.files, extra])
    lock = a_lock(base, config, files={"docs": old_file_entry()})
    tree = synced_tree(base) | {"docs": FileEntry(executable=False, content=OLD)}

    problems = conflicts(rendered, lock, tree)

    assert problems == (PathProblem("docs/x.md", "a file where a folder belongs: docs"),)


@pytest.mark.parametrize(
    ("path", "old_entry", "target"),
    [
        pytest.param(LINK, None, LINK_TARGET, id="managed-no-entry"),
        pytest.param(LINK, old_link_entry(), LINK_TARGET, id="managed-entry"),
        pytest.param(OLD_LINK, old_link_entry(), OLD_TARGET, id="no-longer-rendered"),
        pytest.param(SEEDED_LINK, None, "../../plugin/skills/y", id="seeded-no-entry"),
    ],
)
def test_reports_outside_when_link_on_disk_resolves_outside(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    path: str,
    *,
    target: str,
    old_entry: LockEntry | None,
) -> None:
    """The target is the render's or the entry's own: only ``outside`` makes it a conflict."""
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={path: old_entry})
    tree = synced_tree(rendered) | {path: LinkEntry(target=target, outside=True)}

    problems = conflicts(rendered, lock, tree)

    assert problems == (PathProblem(path, "resolves outside the hub"),)


@pytest.mark.parametrize(
    ("changed", "remove"),
    [
        pytest.param(
            {SEEDED_LINK: LinkEntry(target="../../../../etc", outside=True)}, (), id="outside"
        ),
        pytest.param(
            {".claude/skills": LinkEntry(target=ELSEWHERE, outside=True)},
            (SEEDED_LINK,),
            id="symlinked-ancestor",
        ),
    ],
)
def test_leaves_seeded_when_entry_seeded_and_link_resolves_outside(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    changed: Mapping[str, TreeEntry],
    *,
    remove: tuple[str, ...],
) -> None:
    """Plan erratum E19: a seeded path with an entry is never looked at, so it is no conflict."""
    rendered = a_rendered_hub()
    tree = without(synced_tree(rendered), *remove) | dict(changed)

    plan = planned(rendered, a_lock(rendered, config), tree)

    assert not plan.pending
    assert plan.changes == ()


@pytest.mark.parametrize(
    ("changed", "path", "cause"),
    [
        pytest.param(
            {"plugin": LinkEntry(target=ELSEWHERE, outside=False)},
            "plugin/agents/x.md",
            "symlinked ancestor plugin",
            id="symlinked-ancestor",
        ),
        pytest.param(
            {"plugin/agents": FileEntry(executable=False, content=None)},
            "plugin/agents/x.md",
            "a file where a folder belongs: plugin/agents",
            id="file-ancestor",
        ),
    ],
)
def test_reports_ancestor_first_when_file_below_equals_render(
    a_rendered_hub: HubFactory,
    config: HubConfig,
    changed: Mapping[str, TreeEntry],
    *,
    path: str,
    cause: str,
) -> None:
    """E5: the file below still equals its render (as seen through the link); it is not clean.

    The real reader never lists a path below a link or a file; the fixture pins E5's order in
    case it did.
    """
    rendered = a_rendered_hub()
    tree = synced_tree(rendered) | dict(changed)

    problems = conflicts(rendered, a_lock(rendered, config), tree)

    assert problems == (PathProblem(path, cause),)


def test_returns_every_conflict_sorted_without_writes_when_several(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    lock = a_lock(rendered, config, files={OLD_FILE: old_file_entry(), "gone.md": old_file_entry()})
    tree = without(synced_tree(rendered), "plugin/agents/x.md") | {
        FILE: FileEntry(executable=False, content=EDITED),
        "scripts/run.sh": FileEntry(executable=False, content=b"#!/bin/sh\n"),
        LINK: LinkEntry(target=LINK_TARGET, outside=True),
        OLD_FILE: FileEntry(executable=False, content=EDITED),
        # Would be deleted, like ``plugin/agents/x.md`` would be restored: neither is planned.
        "gone.md": FileEntry(executable=False, content=OLD),
    }

    result = run(rendered, lock, tree)

    assert result == SyncConflicts(
        problems=(
            PathProblem(LINK, "resolves outside the hub"),
            ContentConflict(path=FILE, on_disk=EDITED, render=RULES),
            PathProblem(OLD_FILE, NO_LONGER_RENDERED),
            PathProblem("scripts/run.sh", "executable bit differs (on disk -x, render +x)"),
        )
    )
