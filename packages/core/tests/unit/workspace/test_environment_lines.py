from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)
from agent_hub.core.workspace.environment_lines import (
    NO_ENVIRONMENTS_LINE,
    environment_json,
    environments_json,
    list_lines,
    production_line,
    production_lines,
    show_lines,
)


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


def _w_and_lc() -> EffectiveEnvironments:
    """The spec's ``W`` and ``Lc``, with ``Lc`` tightening ``staging`` to ``read``."""
    config = HubConfig.model_validate(an_environments_document())
    local_document = a_local_environments_document()
    local_document["environments"]["staging"] = {"access": "read"}
    return effective_environments(config, LocalConfig.model_validate(local_document))


def test_lists_one_line_per_environment_when_list_built() -> None:
    # AGH-287 (AC-277.22): name, access, PRODUCTION and source, then the services per repo.
    assert list_lines(_w_and_lc()) == (
        "local (write, hub.json): docker compose stack on this machine",
        "staging (read, hub.local.json)",
        "live (read, PRODUCTION, hub.json)",
        "jane-cloud (write, hub.local.json)",
        "services:",
        "  demo-api api (api): local, staging, live, jane-cloud",
        "  demo-api orders (dynamodb): staging",
        "blocked words: prod, production, demo-live",
        "blocked files: config/*.json, serverless.yml, deploy/*.tfvars",
    )


def test_shows_credentials_and_endpoints_when_show_built() -> None:
    view = _w_and_lc()

    assert show_lines(view, "live") == (
        "live (read, PRODUCTION, hub.json)",
        "  aws profile: demo-live-ro",
        "  credential variables: DEMO_LIVE_DB_URL",
        "  endpoints:",
        "    demo-api api: https://api.example.com",
    )
    assert show_lines(view, "staging") == (
        "staging (read, hub.local.json)",
        "  aws profile: demo-staging",
        "  endpoints:",
        "    demo-api api: https://api.staging.example.com",
        "    demo-api orders: resource demo-orders-staging",
    )
    assert show_lines(view, "jane-cloud") == (
        "jane-cloud (write, hub.local.json)",
        "  aws profile: jane-sandbox",
        "  endpoints:",
        "    demo-api api: https://api.jane.example.com (hub.local.json)",
    )
    assert show_lines(view, "qa") is None


def test_shows_description_and_no_endpoint_when_environment_bare() -> None:
    document = a_hub_document()
    document["environments"] = {"qa": {"access": "ask", "description": "a shared test stack"}}
    view = effective_environments(HubConfig.model_validate(document), LocalConfig())

    assert show_lines(view, "qa") == (
        "qa (ask, hub.json)",
        "  description: a shared test stack",
        "  endpoints: none",
    )


def test_suggests_names_when_no_environment_declared() -> None:
    view = effective_environments(HubConfig.model_validate(a_hub_document()), LocalConfig())

    assert list_lines(view) == (NO_ENVIRONMENTS_LINE,)
    assert NO_ENVIRONMENTS_LINE.startswith(
        "no environments declared; for example: ./hub env add local --access write"
    )
    for name in ("local", "staging", "production"):
        assert name in NO_ENVIRONMENTS_LINE


def test_builds_json_with_names_only_when_view_given() -> None:
    data = environments_json(_w_and_lc())

    assert isinstance(data, dict)
    assert list(data) == [
        "environments",
        "services",
        "blocked_words",
        "blocked_files",
        "blocked_env",
    ]
    assert data["environments"][2] == {
        "name": "live",
        "access": "read",
        "production": True,
        "source": "hub.json",
        "description": None,
        "credentials": {"aws_profile": "demo-live-ro", "env": ["DEMO_LIVE_DB_URL"]},
    }
    assert data["services"][1] == {
        "repo": "demo-api",
        "name": "orders",
        "kind": "dynamodb",
        "description": None,
        "endpoints": [
            {
                "environment": "staging",
                "url": None,
                "resource": "demo-orders-staging",
                "note": None,
                "credentials": None,
                "source": "hub.json",
            }
        ],
    }
    assert data["blocked_words"][2] == {"value": "demo-live", "layer": "hub.local.json"}
    assert data["blocked_env"] == []


def test_builds_show_json_when_name_declared() -> None:
    view = _w_and_lc()

    data = environment_json(view, "live")

    assert isinstance(data, dict)
    assert data["environment"] == environments_json(view)["environments"][2]  # type: ignore[index,call-overload]
    assert data["endpoints"] == [
        {
            "repo": "demo-api",
            "service": "api",
            "environment": "live",
            "url": "https://api.example.com",
            "resource": None,
            "note": None,
            "credentials": None,
            "source": "hub.json",
        }
    ]
    assert environment_json(view, "qa") is None
