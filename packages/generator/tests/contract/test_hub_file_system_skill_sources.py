"""The skill source contract against ``HubFileSystem`` on real folders (AC-164.3, E2)."""

from agent_hub.core.testing.skill_sources_contract import SkillSourcesContract


class TestHubFileSystemSkillSources(SkillSourcesContract):
    """The file system adapter honours the contract."""
