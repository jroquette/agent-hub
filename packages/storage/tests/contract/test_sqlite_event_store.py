from agent_hub.core.testing.contracts import EventStoreContract


class TestSqliteEventStore(EventStoreContract):
    """The EventStore contract suite, run against the SQLite adapter."""
