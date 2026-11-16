from agent_hub.core.testing.contracts import EventReaderContract, EventStoreContract


class TestSqliteEventStore(EventStoreContract, EventReaderContract):
    """The EventStore contract suites, run against the SQLite adapter."""
