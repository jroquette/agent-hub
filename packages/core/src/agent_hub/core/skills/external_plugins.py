"""The third-party plugins a hub names, listed by name and pin only (AGH-164, D1, P7).

The union of the ``enabledPlugins`` keys of ``.claude/settings.json`` and the marketplace's
plugins whose ``source`` is not a local ``./plugin/…`` folder, minus the hub's own plugin
folders and the plugins the marketplace declares local. Their content is not in the hub and is
never fetched: nothing here opens a connection.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.core.redaction.redact import clip
from agent_hub.core.skills.skill_hooks import HubJsonContent, load_hub_json
from agent_hub.core.skills.skill_sources import MARKETPLACE_PATH, SETTINGS_PATH
from agent_hub.core.skills.skill_view import ExternalPlugin

ENABLED_PLUGINS: Final = "enabledPlugins"
LOCAL_SOURCE_PREFIX: Final = "./plugin/"
MAX_PIN_CHARS: Final = 64
MAX_PLUGIN_NAME_CHARS: Final = 128
_PIN_KEYS: Final = ("sha", "ref")


@dataclass(frozen=True, kw_only=True, slots=True)
class ExternalPlugins:
    """The external plugins by name then marketplace, and the notices of the files not read."""

    plugins: tuple[ExternalPlugin, ...] = ()
    notices: tuple[str, ...] = ()


def _enabled_object(settings: HubJsonContent) -> JsonValue:
    document = load_hub_json(SETTINGS_PATH, settings).document
    return None if document is None else document.get(ENABLED_PLUGINS)


def enabled_plugins(settings: HubJsonContent) -> dict[str, bool]:
    """``enabledPlugins`` of ``settings`` (``.claude/settings.json``): each key and whether its
    value is ``true``; empty when the file or the key is absent or malformed."""
    found = _enabled_object(settings)
    if not isinstance(found, dict):
        return {}
    return {key: value is True for key, value in found.items()}


def marketplace_name(marketplace: HubJsonContent) -> str | None:
    """The ``name`` of ``.claude-plugin/marketplace.json``, or None."""
    document = load_hub_json(MARKETPLACE_PATH, marketplace).document
    name = None if document is None else document.get("name")
    return name if isinstance(name, str) and name else None


def _pin(source: JsonValue) -> str | None:
    if not isinstance(source, dict):
        return None
    for key in _PIN_KEYS:
        value = source.get(key)
        if isinstance(value, str) and 0 < len(value) <= MAX_PIN_CHARS:
            return value
    return None


def _is_local(source: JsonValue) -> bool:
    return isinstance(source, str) and source.startswith(LOCAL_SOURCE_PREFIX)


def _shown(text: str) -> str:
    return clip(" ".join(text.split()), MAX_PLUGIN_NAME_CHARS)


class _Listing:
    def __init__(self, enabled: Mapping[str, bool], local_plugins: frozenset[str]) -> None:
        self.enabled = enabled
        self.local_plugins = local_plugins
        self.found: dict[tuple[str, str | None], ExternalPlugin] = {}
        self.declared_local: set[tuple[str, str | None]] = set()
        self.notices: list[str] = []

    def add(self, name: str, marketplace: str | None, pin: str | None) -> None:
        listed = (name, marketplace)
        if not name or name in self.local_plugins or listed in self.found:
            return
        if listed in self.declared_local:
            return
        key = f"{name}@{marketplace}" if marketplace is not None else name
        self.found[(name, marketplace)] = ExternalPlugin(
            name=_shown(name),
            marketplace=None if marketplace is None else _shown(marketplace),
            pin=pin,
            enabled=self.enabled.get(key, False),
        )

    def marketplace(self, content: HubJsonContent) -> None:
        loaded = load_hub_json(MARKETPLACE_PATH, content)
        if loaded.notice is not None:
            self.notices.append(loaded.notice)
        if loaded.document is None:
            return
        name = loaded.document.get("name")
        market = name if isinstance(name, str) and name else None
        plugins = loaded.document.get("plugins", [])
        if not isinstance(plugins, list):
            self.notices.append(f"{MARKETPLACE_PATH}: plugins not read (not a list)")
            return
        malformed = False
        for plugin in plugins:
            plugin_name = plugin.get("name") if isinstance(plugin, dict) else None
            if not isinstance(plugin, dict) or not isinstance(plugin_name, str):
                malformed = True
                continue
            source = plugin.get("source")
            if _is_local(source):
                self.declared_local.add((plugin_name, market))
            else:
                self.add(plugin_name, market, _pin(source))
        if malformed:
            self.notices.append(f"{MARKETPLACE_PATH}: some plugins not read (not a named object)")

    def settings(self, content: HubJsonContent) -> None:
        found = _enabled_object(content)
        if found is not None and not isinstance(found, dict):
            self.notices.append(f"{SETTINGS_PATH}: {ENABLED_PLUGINS} not read (not an object)")
            return
        for key in found or {}:
            name, at, market = key.rpartition("@")
            self.add(name if at else key, market if at and market else None, None)


def external_plugins(
    marketplace: HubJsonContent, settings: HubJsonContent, *, local_plugins: frozenset[str]
) -> ExternalPlugins:
    """The plugins ``marketplace`` (``.claude-plugin/marketplace.json``) and ``settings``
    (``.claude/settings.json`` ``enabledPlugins``) name that are not in ``local_plugins`` (the
    hub's plugin folders): name, marketplace, pin (``source.sha`` or ``source.ref``, at most 64
    characters) and whether ``enabledPlugins`` sets them ``true``."""
    listing = _Listing(enabled_plugins(settings), local_plugins)
    listing.marketplace(marketplace)
    listing.settings(settings)
    plugins = sorted(
        listing.found.values(), key=lambda plugin: (plugin.name, plugin.marketplace or "")
    )
    return ExternalPlugins(plugins=tuple(plugins), notices=tuple(listing.notices))
