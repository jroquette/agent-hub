"""The ``KnowledgeIndex`` contract against the in-memory fake."""

from agent_hub.core.testing.knowledge_index_contract import KnowledgeIndexContract


class TestInMemoryKnowledgeIndex(KnowledgeIndexContract):
    """The fake honours the contract."""
