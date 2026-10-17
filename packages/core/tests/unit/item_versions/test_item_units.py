"""The unit of a Toolkit item (AGH-295, S1, A4): a skill's folder, an agent's or a hook's file,
never a link's own entry nor ``settings.local.json``; its stat fingerprint; managed per lock."""

from collections.abc import Mapping

from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry
from agent_hub.core.item_versions.item_units import (
    ItemUnit,
    is_managed,
    unit_fingerprint,
    unit_of_item,
)
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.skills.skill_catalog import build_catalog, catalog_reads
from agent_hub.core.skills.skill_sources import CatalogInputs, SkillSources, SourceFile
from agent_hub.core.skills.skill_view import CatalogItem, ItemKind, Origin
from agent_hub.core.testing.hub_fakes import FakeHubFileReader
from agent_hub.core.testing.skill_trees import (
    FIXTURE_PLATFORM_VERSION,
    FIXTURE_PROJECT,
    Link,
    TreeEntry,
    a_skills_fixture_tree,
    fake_hub_of,
)

HUB = "/hubs/demo-hub"
_SHA = "ab" * 32


def _folded(tree: Mapping[str, TreeEntry]) -> tuple[dict[str, CatalogItem], SkillSources]:
    reader = FakeHubFileReader({HUB: fake_hub_of(tree)})
    sources = reader.skill_sources(HUB)
    texts = {
        path: reader.read_skill_file(HUB, path, max_bytes=1_048_576)
        for path in catalog_reads(sources)
    }
    inputs = CatalogInputs(
        project=FIXTURE_PROJECT,
        project_plugin=FIXTURE_PROJECT,
        sources=sources,
        texts=texts,
        lock=reader.read_lock(HUB),
    )
    catalog = build_catalog(inputs).catalog
    return {item.id: item for item in catalog.items}, sources


def _unit(path: str, kind: UnitKind) -> ItemUnit:
    return ItemUnit(project=FIXTURE_PROJECT, unit_path=path, kind=kind)


def test_skill_unit_is_folder_when_skill_listed() -> None:
    items, sources = _folded(a_skills_fixture_tree())

    alpha = items["skill/hub-workflow/alpha"]
    unit = unit_of_item(alpha, sources, project=FIXTURE_PROJECT)

    assert alpha.linked_from == (".claude/skills/alpha",)
    assert unit == _unit("plugin/hub-workflow/skills/alpha", UnitKind.SKILL)


def test_file_unit_when_agent_listed() -> None:
    items, sources = _folded(a_skills_fixture_tree())

    unit = unit_of_item(items["agent/demo/scout"], sources, project=FIXTURE_PROJECT)

    assert unit == _unit("plugin/demo/agents/scout.md", UnitKind.AGENT)


def test_no_unit_when_item_is_link() -> None:
    tree = a_skills_fixture_tree() | {
        ".claude/skills/out": Link("/elsewhere/out"),
        ".claude/agents/away.md": Link("../../../away.md"),
    }
    items, sources = _folded(tree)

    skill, agent = items["skill/claude/out"], items["agent/claude/away"]

    assert unit_of_item(skill, sources, project=FIXTURE_PROJECT) is None
    assert unit_of_item(agent, sources, project=FIXTURE_PROJECT) is None


def test_no_unit_when_skill_md_is_link() -> None:
    tree = a_skills_fixture_tree() | {
        "plugin/demo/skills/linked/SKILL.md": Link("../gamma/SKILL.md"),
    }
    items, sources = _folded(tree)

    assert unit_of_item(items["skill/demo/linked"], sources, project=FIXTURE_PROJECT) is None


def test_no_unit_when_item_entry_not_listed() -> None:
    items, sources = _folded(a_skills_fixture_tree())
    scout = items["agent/demo/scout"]

    assert unit_of_item(scout, SkillSources(files=()), project=FIXTURE_PROJECT) is None


def test_no_unit_when_item_in_local_settings() -> None:
    items, sources = _folded(a_skills_fixture_tree())
    local = items["hook/settings/settings-pretooluse-1"].model_copy(
        update={"source_path": ".claude/settings.local.json"}
    )
    listed = SkillSources(
        files=(
            *sources.files,
            SourceFile(path=".claude/settings.local.json", size=2, mtime_ns=1, regular=True),
        )
    )

    assert unit_of_item(local, listed, project=FIXTURE_PROJECT) is None


def test_hooks_share_unit_when_same_file() -> None:
    items, sources = _folded(a_skills_fixture_tree())

    hooks = [
        unit_of_item(item, sources, project=FIXTURE_PROJECT)
        for item in items.values()
        if item.kind is ItemKind.HOOK and item.source == "settings"
    ]

    assert hooks == [_unit(".claude/settings.json", UnitKind.HOOK)] * 2


def test_lists_entries_at_or_under_unit_when_fingerprint_taken() -> None:
    _, sources = _folded(a_skills_fixture_tree())

    folder = unit_fingerprint(sources, _unit("plugin/hub-workflow/skills/alpha", UnitKind.SKILL))
    file = unit_fingerprint(sources, _unit("plugin/demo/agents/scout.md", UnitKind.AGENT))

    assert [entry[0] for entry in folder] == [
        "plugin/hub-workflow/skills/alpha/SKILL.md",
        "plugin/hub-workflow/skills/alpha/references/r.md",
        "plugin/hub-workflow/skills/alpha/scripts/s.sh",
    ]
    listed = {entry.path: entry for entry in sources.files}["plugin/demo/agents/scout.md"]
    assert file == (
        (listed.path, listed.size, listed.mtime_ns, listed.regular, listed.link_target),
    )


def test_keeps_fingerprint_apart_when_sibling_shares_prefix() -> None:
    tree = a_skills_fixture_tree() | {"plugin/demo/skills/gamma-two/SKILL.md": b"# Two\n"}
    _, sources = _folded(tree)

    gamma = unit_fingerprint(sources, _unit("plugin/demo/skills/gamma", UnitKind.SKILL))

    assert [entry[0] for entry in gamma] == ["plugin/demo/skills/gamma/SKILL.md"]


def test_managed_when_lock_lists_skill_md() -> None:
    entry = ManagedFileEntry(ownership="managed", sha256=_SHA, executable=False)
    lock = HubLock(
        lock_version=1,
        platform_version=FIXTURE_PLATFORM_VERSION,
        schema_version=1,
        modules=(),
        files={"plugin/demo/skills/gamma/SKILL.md": entry},
    )

    assert is_managed(lock, _unit("plugin/demo/skills/gamma", UnitKind.SKILL))
    assert not is_managed(lock, _unit("plugin/demo/skills/gamma", UnitKind.AGENT))


def test_managed_when_lock_lists_hook_file() -> None:
    items, sources = _folded(a_skills_fixture_tree())
    pre_tool_use = items["hook/settings/settings-pretooluse-1"]
    unit = unit_of_item(pre_tool_use, sources, project=FIXTURE_PROJECT)

    assert unit is not None
    assert pre_tool_use.origin is Origin.MANAGED
    assert is_managed(_folded_lock(), unit)


def test_not_managed_when_lock_seeds_or_misses_path() -> None:
    lock = _folded_lock()

    assert not is_managed(lock, _unit(".claude/settings.project.json", UnitKind.HOOK))
    assert not is_managed(lock, _unit("plugin/demo/agents/scout.md", UnitKind.AGENT))
    assert not is_managed(None, _unit(".claude/settings.json", UnitKind.HOOK))


def _folded_lock() -> HubLock:
    reader = FakeHubFileReader({HUB: fake_hub_of(a_skills_fixture_tree())})
    lock = reader.read_lock(HUB)
    assert isinstance(lock, HubLock)
    return lock
