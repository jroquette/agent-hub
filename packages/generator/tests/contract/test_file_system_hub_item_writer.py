"""The ``HubItemWriter`` contract against ``FileSystemHubItemWriter`` on real folders."""

from agent_hub.core.testing.hub_item_writer_contract import HubItemWriterContract


class TestFileSystemHubItemWriter(HubItemWriterContract):
    """The file system writer honours the contract."""
