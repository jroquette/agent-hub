"""The shipped templates are versionable (AGH-295, D9, research risk 9): rendered into the demo
hub, every skill, agent and hook unit reads whole and holds no secret match, so the secret gate
never silently turns off versioning of ``hub-workflow`` or the seeded project plugin."""

from collections.abc import Callable
from pathlib import Path

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.item_versions.item_units import ItemUnit, SourceIndex, unit_of_item
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent
from agent_hub.core.skills.skill_catalog import build_catalog, catalog_reads
from agent_hub.core.skills.skill_sources import MAX_SKILL_JSON_BYTES, CatalogInputs
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.registered_hub_files import HubFileSystem

BASE_PLUGIN_ROOT = "plugin/hub-workflow/"


def _units(reader: HubFileSystem, hub: str, project: str) -> set[ItemUnit]:
    sources = reader.skill_sources(hub)
    texts = {
        path: reader.read_skill_file(hub, path, max_bytes=MAX_SKILL_JSON_BYTES)
        for path in catalog_reads(sources)
    }
    inputs = CatalogInputs(
        project=project,
        project_plugin=project,
        sources=sources,
        texts=texts,
        lock=reader.read_lock(hub),
    )
    index = SourceIndex(sources)
    items = build_catalog(inputs).catalog.items
    found = (unit_of_item(item, index, project=project) for item in items)
    return {unit for unit in found if unit is not None}


def test_finds_no_secret_match_when_demo_hub_rendered(
    rendered_hub: Callable[[HubConfig], Path],
) -> None:
    config = HubConfig.model_validate(a_hub_document())
    hub = str(rendered_hub(config))
    reader = HubFileSystem()

    units = _units(reader, hub, config.project.name)
    reads = {unit: reader.read_unit(hub, unit.unit_path, kind=unit.kind) for unit in units}

    assert {unit.kind for unit in units} == {UnitKind.SKILL, UnitKind.AGENT, UnitKind.HOOK}
    assert any(unit.unit_path.startswith(BASE_PLUGIN_ROOT) for unit in units)
    unread = {
        unit.unit_path: read for unit, read in reads.items() if not isinstance(read, UnitContent)
    }
    assert unread == {}
    matched = sorted(
        unit.unit_path
        for unit, read in reads.items()
        if isinstance(read, UnitContent) and has_secret_match(read)
    )
    assert matched == []
