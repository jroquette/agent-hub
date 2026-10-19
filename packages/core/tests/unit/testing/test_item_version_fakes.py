import pytest

from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.testing.hub_fakes import FakeHub
from agent_hub.core.testing.item_version_fakes import FakeHubItemWriter

HUB = "/hubs/demo-hub"
SKILL = "plugin/demo/skills/alpha"


def test_leaves_hub_unchanged_when_write_fails_on_unit() -> None:
    hub = FakeHub(skill_files={f"{SKILL}/SKILL.md": b"# old\n", f"{SKILL}/r.md": b"r\n"})
    writer = FakeHubItemWriter({HUB: hub}, fail_on={SKILL})
    new = UnitContent(files=(UnitFile(path="SKILL.md", content=b"# new\n"),))

    with pytest.raises(HubItemWriteError) as raised:
        writer.write_unit(HUB, SKILL, new, kind=UnitKind.SKILL)

    assert hub.skill_files == {f"{SKILL}/SKILL.md": b"# old\n", f"{SKILL}/r.md": b"r\n"}
    assert writer.writes == []
    assert SKILL not in str(raised.value)
