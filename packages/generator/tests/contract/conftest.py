"""The core contract suites run here against the generator's file system adapter."""

from pathlib import Path

import pytest

from agent_hub.core.testing.skill_sources_contract import SkillTree
from agent_hub.core.testing.skill_trees import DiskSkillTree
from agent_hub.generator.registered_hub_files import HubFileSystem


@pytest.fixture
def skill_tree(tmp_path: Path) -> SkillTree:
    hub = tmp_path / "hub"
    hub.mkdir()
    return DiskSkillTree(root=hub, reader=HubFileSystem())
