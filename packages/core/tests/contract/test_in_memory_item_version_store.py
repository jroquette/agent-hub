"""The ``ItemVersionStore`` contract against the in-memory fake."""

from agent_hub.core.testing.item_version_store_contract import ItemVersionStoreContract


class TestInMemoryItemVersionStore(ItemVersionStoreContract):
    """The fake honours the contract."""
