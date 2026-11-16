from agent_hub.core.testing.knowledge_index_contract import (
    KnowledgeIndexContract,
    KnowledgeLinksContract,
)


class TestSqliteKnowledgeIndex(KnowledgeIndexContract, KnowledgeLinksContract):
    """The KnowledgeIndex contract suite, run against the SQLite adapter."""
