from datetime import date

from agent_hub.core.readmodels.settings_view import SettingsView


def test_serializes_settings_with_privacy_rules_when_dumped() -> None:
    settings = SettingsView(
        db_path="/home/demo/.local/share/agent-hub/agent-hub.db",
        registry_path="/home/demo/.local/share/agent-hub/hubs.json",
        port=7420,
        running_version="0.8.0",
        redaction_kinds=("github token", "private key"),
        prices_as_of=date(2026, 10, 11),
    )

    document = settings.model_dump(mode="json")

    assert (document["redaction_ruleset"], document["metadata_only"]) == ("r1", True)
    assert document["prices_as_of"] == "2026-10-11"
