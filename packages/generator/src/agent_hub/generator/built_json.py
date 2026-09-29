"""The JSON files the generator builds from the config (spec Q-9, Q-10).

Each builder returns a JSON value; ``render_hub`` writes it in the JSON byte form
(``json_form.dump_json``). A builder reads only the config: the same config builds the same value.
"""

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.json_form import JsonValue

_PROJECT_MANIFEST_VERSION = "0.1.0"
_PROJECT_MANIFEST_DESCRIPTION = "Project agents, skills and guard extension of this hub."


def project_settings(config: HubConfig) -> JsonValue:
    """The seeded ``.claude/settings.project.json``: empty; the project adds its own settings."""
    return {}


def project_manifest(config: HubConfig) -> JsonValue:
    """The seeded project plugin manifest: the project's name, a first version, a description."""
    return {
        "name": config.project.name,
        "version": _PROJECT_MANIFEST_VERSION,
        "description": _PROJECT_MANIFEST_DESCRIPTION,
    }
