import json

import pytest

from agent_hub.core.skills.external_plugins import (
    enabled_plugins,
    external_plugins,
    marketplace_name,
)
from agent_hub.core.skills.skill_view import ExternalPlugin

SHA = "5bf4e78011075bcfc0dc295f0724994cd123ee71"


def _json(document: object) -> bytes:
    return json.dumps(document).encode()


def _marketplace() -> bytes:
    return _json(
        {
            "name": "agent-hub",
            "plugins": [
                {"name": "hub-workflow", "source": "./plugin/hub-workflow"},
                {"name": "superpowers", "source": {"source": "url", "url": "u", "sha": SHA}},
                {"name": "toolkit", "source": {"source": "git-subdir", "ref": "main"}},
            ],
        }
    )


def _settings() -> bytes:
    return _json(
        {
            "enabledPlugins": {
                "superpowers@agent-hub": True,
                "hookify@agent-hub": False,
                "other@claude-plugins-official": True,
                "hub-workflow@agent-hub": False,
            }
        }
    )


def test_lists_pins_and_enabled_when_marketplace_and_settings_given() -> None:
    found = external_plugins(_marketplace(), _settings(), local_plugins=frozenset({"hub-workflow"}))

    assert found.plugins == (
        ExternalPlugin(name="hookify", marketplace="agent-hub", pin=None, enabled=False),
        ExternalPlugin(name="other", marketplace="claude-plugins-official", pin=None, enabled=True),
        ExternalPlugin(name="superpowers", marketplace="agent-hub", pin=SHA, enabled=True),
        ExternalPlugin(name="toolkit", marketplace="agent-hub", pin="main", enabled=False),
    )
    assert all(plugin.content == "not in this hub" for plugin in found.plugins)
    assert found.notices == ()


def test_skips_local_plugins_when_folder_present() -> None:
    marketplace = _json(
        {
            "name": "agent-hub",
            "plugins": [
                {"name": "demo", "source": {"source": "url", "url": "u"}},
                {"name": "local", "source": "./plugin/local"},
            ],
        }
    )
    settings = _json({"enabledPlugins": {"demo@agent-hub": True, "local@agent-hub": True}})

    found = external_plugins(marketplace, settings, local_plugins=frozenset({"demo"}))

    assert found.plugins == ()


def test_lists_nothing_when_files_absent() -> None:
    found = external_plugins(None, None, local_plugins=frozenset())

    assert (found.plugins, found.notices) == ((), ())


def test_drops_pin_when_longer_than_sixty_four_characters() -> None:
    marketplace = _json(
        {"name": "m", "plugins": [{"name": "p", "source": {"sha": "a" * 65, "ref": "v1"}}]}
    )

    (plugin,) = external_plugins(marketplace, None, local_plugins=frozenset()).plugins

    assert plugin.pin == "v1"


def test_reads_enabled_and_name_when_helpers_called() -> None:
    assert enabled_plugins(_settings())["superpowers@agent-hub"] is True
    assert enabled_plugins(_json({"enabledPlugins": {"x@y": "yes"}})) == {"x@y": False}
    assert enabled_plugins(b"not json") == {}
    assert marketplace_name(_marketplace()) == "agent-hub"
    assert marketplace_name(_json({"name": 3})) is None


MALFORMED = {
    "not json": b"{",
    "not an object": b"3",
    "plugins not a list": _json({"name": "m", "plugins": {}}),
    "plugin not an object": _json({"name": "m", "plugins": ["p"]}),
}


@pytest.mark.parametrize("content", MALFORMED.values(), ids=MALFORMED.keys())
def test_reports_notice_when_marketplace_malformed(content: bytes) -> None:
    found = external_plugins(content, _settings(), local_plugins=frozenset({"hub-workflow"}))

    (notice,) = found.notices
    assert notice.startswith(".claude-plugin/marketplace.json: ")
    assert [plugin.name for plugin in found.plugins] == ["hookify", "other", "superpowers"]


def test_reports_notice_when_enabled_plugins_not_object() -> None:
    found = external_plugins(None, _json({"enabledPlugins": []}), local_plugins=frozenset())

    assert found.notices == (".claude/settings.json: enabledPlugins not read (not an object)",)
