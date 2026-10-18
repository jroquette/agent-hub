from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)
from agent_hub.core.workspace.environment_lines import production_line, production_lines


def test_names_access_and_file_when_environment_production() -> None:
    # AGH-282 (spec D-prodflag): one explicit line per production environment.
    assert production_line("live", "read", "hub.json") == (
        "production environment: live (access read, hub.json)"
    )
    assert production_line("jane-cloud", "write", "hub.local.json") == (
        "production environment: jane-cloud (access write, hub.local.json)"
    )


def test_lists_production_environments_in_order_when_view_built() -> None:
    config = HubConfig.model_validate(an_environments_document())
    local_document = a_local_environments_document()
    local_document["environments"]["jane-cloud"]["production"] = True
    local = LocalConfig.model_validate(local_document)

    assert production_lines(effective_environments(config, LocalConfig())) == (
        "production environment: live (access read, hub.json)",
    )
    assert production_lines(effective_environments(config, local)) == (
        "production environment: live (access read, hub.json)",
        "production environment: jane-cloud (access write, hub.local.json)",
    )


def test_lists_nothing_when_no_environment_production() -> None:
    # A name is never a flag: an environment named production without it gives no line.
    document = a_hub_document()
    document["environments"] = {"production": {"access": "write"}}
    config = HubConfig.model_validate(document)

    assert production_lines(effective_environments(config, LocalConfig())) == ()
    plain = HubConfig.model_validate(a_hub_document())
    assert production_lines(effective_environments(plain, LocalConfig())) == ()
