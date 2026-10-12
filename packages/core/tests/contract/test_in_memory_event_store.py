from agent_hub.core.testing.contracts import EventReaderContract, EventStoreContract


class TestInMemoryEventStore(EventStoreContract, EventReaderContract):
    """The EventStore contract suites, run against the in-memory fake."""
