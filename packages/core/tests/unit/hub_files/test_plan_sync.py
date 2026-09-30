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
from agent_hub.core.hub_files.plan_init import FileWrite, LinkWrite
from agent_hub.core.hub_files.plan_sync import (
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

    # ``scripts`` is there; ``.claude/skills`` is there but nothing under it is written.
    assert plan.folders == (".claude/agents", "plugin", "plugin/agents")


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
