from agent_hub.storage.db import metadata


def test_declares_no_tables_when_baseline_schema() -> None:
    assert metadata.tables == {}
