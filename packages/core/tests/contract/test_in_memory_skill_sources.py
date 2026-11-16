"""The skill source contract against the in-memory fake (AC-164.3)."""

from agent_hub.core.testing.skill_sources_contract import SkillSourcesContract


class TestInMemorySkillSources(SkillSourcesContract):
    """The fake honours the contract."""
