from datetime import date
from typing import Any

from agent_hub.core.readmodels.settings_view import SettingsView


def test_maps_settings_when_settings_requested(wired: Any) -> None:
    wired.hubs.settings_view = SettingsView(
        db_path="/home/demo/agent-hub.db",
        registry_path="/home/demo/hubs.json",
        port=7420,
        running_version="0.8.0",
        redaction_kinds=("github token",),
        prices_as_of=date(2026, 10, 11),
    )

    response = wired.client.get("/api/v1/settings")

    assert response.json()["redaction_ruleset"] == "r1"
    assert response.json()["port"] == 7420
