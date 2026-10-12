from datetime import UTC, datetime
from pathlib import Path

from agent_hub.api.settings import DEFAULT_PORT, ApiSettings


def test_uses_aware_utc_clock_when_no_clock_given(tmp_path: Path) -> None:
    settings = ApiSettings(
        db_path=tmp_path / "a.db",
        registry_path=tmp_path / "hubs.json",
        port=DEFAULT_PORT,
        running_version="0.8.0",
    )

    now = settings.clock()

    assert now.tzinfo == UTC
    assert abs((datetime.now(UTC) - now).total_seconds()) < 60
    assert DEFAULT_PORT == 7420
