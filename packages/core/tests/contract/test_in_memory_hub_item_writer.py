"""The ``HubItemWriter`` contract against the in-memory fake."""

from agent_hub.core.testing.hub_item_writer_contract import HubItemWriterContract


class TestInMemoryHubItemWriter(HubItemWriterContract):
    """The fake honours the contract."""
