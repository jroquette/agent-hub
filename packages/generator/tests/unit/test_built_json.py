import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.built_json import project_manifest, project_settings


def a_config_named(name: str) -> HubConfig:
    document = a_hub_document()
    document["project"]["name"] = name
    return HubConfig.model_validate(document)


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_returns_empty_object_when_project_settings_built(project_name: str) -> None:
    # Spec D2/D5: the project's own settings start empty; AGH-14 merges them into settings.json.
    assert project_settings(a_config_named(project_name)) == {}


@pytest.mark.parametrize("project_name", ["demo", "acme-tools"])
def test_names_project_when_project_manifest_built(project_name: str) -> None:
    # Spec Q-10: the project's name, a first version and a generic description; nothing else.
    assert project_manifest(a_config_named(project_name)) == {
        "name": project_name,
        "version": "0.1.0",
        "description": "Project agents, skills and guard extension of this hub.",
    }
