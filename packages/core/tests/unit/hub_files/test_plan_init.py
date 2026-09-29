import re
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

import agent_hub.core
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_init import FileWrite, InitPlan, LinkWrite, plan_init
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

HUB_JSON = b'{"project": "demo"}\n'
FOLDERS = (".claude", ".claude/agents", ".claude/skills", "plugin", "plugin/agents", "scripts")
# AGH-19's purity pattern (spec AC-12.26), verbatim: write, tree-read, clock and environment calls.
PURITY = re.compile(
    r"write_text|write_bytes|\bopen\(|os\.(replace|rename|remove|unlink|mkdir|makedirs|chmod|"
    r"symlink|walk|scandir|lstat|environ)|shutil|Path\.cwd|\bPath\(|"
    r"^\s*(import|from) (datetime|time|random|uuid|getpass|socket)\b"
)
CORE_MODULES = (
    "json_form.py",
    "hub_files/hub_lock.py",
    "hub_files/tree_snapshot.py",
    "hub_files/plan_init.py",
)

type HubFactory = Callable[..., RenderedHub]


@pytest.fixture
def config() -> HubConfig:
    return HubConfig.model_validate(a_hub_document())


def a_tree(entries: Mapping[str, TreeEntry] | None = None) -> TreeSnapshot:
    return TreeSnapshot(entries=dict(entries or {}), git_present=False)


def folders(*paths: str) -> dict[str, TreeEntry]:
    return dict.fromkeys(paths, FolderEntry())


def written_tree(rendered: RenderedHub) -> dict[str, TreeEntry]:
    """The tree a finished init leaves: every folder, file and link, and ``hub.json``."""
    entries = folders(*FOLDERS)
    for file in rendered.files:
        entries[file.path] = FileEntry(executable=file.executable, content=file.content)
    for link in rendered.links:
        entries[link.path] = LinkEntry(target=link.target, outside=False)
    entries[HUB_JSON_PATH] = FileEntry(executable=False, content=HUB_JSON)
    return entries


def planned(rendered: RenderedHub, config: HubConfig, tree: TreeSnapshot) -> InitPlan:
    plan = plan_init(rendered=rendered, config=config, hub_json=HUB_JSON, tree=tree)
    assert isinstance(plan, InitPlan)
    return plan


def written_paths(plan: InitPlan) -> list[str]:
    return [write.path for write in plan.writes]


def test_writes_everything_when_tree_empty(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    rendered = a_rendered_hub()

    plan = planned(rendered, config, a_tree())

    assert plan.folders == FOLDERS
    assert plan.leftovers == ()
    assert plan.lock == build_hub_lock(rendered=rendered, config=config)
    files = [
        FileWrite(path=f.path, content=f.content, executable=f.executable) for f in rendered.files
    ]
    links = [LinkWrite(path=link.path, target=link.target) for link in rendered.links]
    assert plan.writes == (
        *files,
        *links,
        FileWrite(path=HUB_JSON_PATH, content=HUB_JSON, executable=False),
        FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(plan.lock), executable=False),
    )


def test_keeps_file_when_equal_to_render(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = folders(*FOLDERS) | {
        "AGENTS.md": FileEntry(executable=False, content=b"# Rules\n"),
        "scripts/run.sh": FileEntry(executable=True, content=b"#!/bin/sh\n"),
    }

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_equal == ("AGENTS.md", "scripts/run.sh")
    assert "AGENTS.md" not in written_paths(plan)
    assert "scripts/run.sh" not in written_paths(plan)


def test_keeps_link_when_target_equal(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    link = LinkEntry(target="../../plugin/agents/x.md", outside=False)
    tree = folders(*FOLDERS) | {".claude/agents/x.md": link}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_links == (".claude/agents/x.md",)
    assert plan.kept_equal == ()
    assert ".claude/agents/x.md" not in written_paths(plan)
    assert plan.created_links == (".claude/skills/y",)


def test_keeps_seeded_file_when_bytes_differ(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {"README.md": FileEntry(executable=True, content=b"# My own readme\n")}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == ("README.md",)
    assert "README.md" not in written_paths(plan)


def test_keeps_hub_json_when_byte_equal(a_rendered_hub: HubFactory, config: HubConfig) -> None:
    tree = {HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON)}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == (HUB_JSON_PATH,)
    assert HUB_JSON_PATH not in written_paths(plan)
    assert written_paths(plan)[-1] == HUB_LOCK_PATH


def test_creates_only_missing_folders_when_some_exist(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    plan = planned(a_rendered_hub(), config, a_tree(folders(".claude", "plugin")))

    assert plan.folders == (".claude/agents", ".claude/skills", "plugin/agents", "scripts")


def test_builds_same_lock_when_files_kept_or_written(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()

    fresh = planned(rendered, config, a_tree())
    rerun = planned(rendered, config, a_tree(written_tree(rendered)))

    assert rerun.lock == fresh.lock
    assert rerun.folders == ()
    assert rerun.writes == (fresh.writes[-1],)


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

    with pytest.raises(ValueError, match=re.escape(path)):
        plan_init(rendered=rendered, config=config, hub_json=HUB_JSON, tree=a_tree())


def test_counts_created_and_kept_when_planned(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    rendered = a_rendered_hub()
    tree = folders(*FOLDERS) | {
        "AGENTS.md": FileEntry(executable=False, content=b"# Rules\n"),
        "README.md": FileEntry(executable=False, content=b"# Mine\n"),
        ".claude/agents/x.md": LinkEntry(target="../../plugin/agents/x.md", outside=False),
        HUB_JSON_PATH: FileEntry(executable=False, content=HUB_JSON),
    }

    fresh = planned(rendered, config, a_tree())
    rerun = planned(rendered, config, a_tree(tree))

    assert fresh.created_managed == ("AGENTS.md", "plugin/agents/x.md", "scripts/run.sh")
    assert fresh.created_seeded == ("README.md", HUB_JSON_PATH)
    assert fresh.created_links == (".claude/agents/x.md", ".claude/skills/y")
    assert (fresh.kept_seeded, fresh.kept_equal, fresh.kept_links) == ((), (), ())
    assert rerun.created_managed == ("plugin/agents/x.md", "scripts/run.sh")
    assert rerun.created_seeded == ()
    assert rerun.created_links == (".claude/skills/y",)
    assert rerun.kept_seeded == ("README.md", HUB_JSON_PATH)
    assert rerun.kept_equal == ("AGENTS.md",)
    assert rerun.kept_links == (".claude/agents/x.md",)


def test_keeps_link_whatever_ownership_when_target_equal(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    tree = folders(*FOLDERS) | {
        ".claude/agents/x.md": LinkEntry(target="../../plugin/agents/x.md", outside=False),
        ".claude/skills/y": LinkEntry(target="../../plugin/skills/y", outside=False),
    }

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_links == (".claude/agents/x.md", ".claude/skills/y")
    assert (plan.kept_seeded, plan.kept_equal, plan.created_links) == ((), (), ())


@pytest.mark.parametrize("path", ["AGENTS.md", HUB_JSON_PATH])
def test_raises_when_compared_file_content_not_read(
    a_rendered_hub: HubFactory, config: HubConfig, path: str
) -> None:
    tree = {path: FileEntry(executable=False, content=None)}

    with pytest.raises(ValueError, match=re.escape(f"{path}: content was not read")):
        plan_init(rendered=a_rendered_hub(), config=config, hub_json=HUB_JSON, tree=a_tree(tree))


def test_keeps_seeded_file_when_content_not_read(
    a_rendered_hub: HubFactory, config: HubConfig
) -> None:
    tree = {"README.md": FileEntry(executable=False, content=None)}

    plan = planned(a_rendered_hub(), config, a_tree(tree))

    assert plan.kept_seeded == ("README.md",)


def test_calls_no_io_when_core_modules_scanned() -> None:
    core_root = Path(agent_hub.core.__file__).parent
    scanned = [core_root / name for name in CORE_MODULES]
    assert all(path.is_file() for path in scanned)
    assert PURITY.search("    os.replace(a, b)")

    hits = [
        f"{path.name}:{number}: {line}"
        for path in scanned
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if PURITY.search(line)
    ]

    assert hits == []
