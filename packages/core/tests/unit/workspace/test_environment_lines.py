import pytest

from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)
from agent_hub.core.workspace import environment_lines
from agent_hub.core.workspace.environment_lines import (
    brief_block,
    production_line,
    production_lines,
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


BLOCK = [
    "## Environments",
    "- `local` (write, hub.json): docker compose stack on this machine",
    "- `staging` (ask, hub.json); credentials: AWS profile `demo-staging`",
    "- `live` (read, PRODUCTION, hub.json); credentials: AWS profile `demo-live-ro`,"
    " variables `DEMO_LIVE_DB_URL`",
    "- `jane-cloud` (write, hub.local.json); credentials: AWS profile `jane-sandbox`",
    "Endpoints:",
    "- `demo-api/api` on `local`: `http://localhost:8000`",
    "- `demo-api/api` on `staging`: `https://api.staging.example.com`",
    "- `demo-api/api` on `live`: `https://api.example.com`",
    "- `demo-api/api` on `jane-cloud`: `https://api.jane.example.com`",
    "- `demo-api/orders` on `staging`: resource `demo-orders-staging`",
    "Blocked words (the guard denies them): `prod`, `production`, `demo-live`",
]


def test_lists_environments_with_source_when_block_built() -> None:
    # AC-277.8: access, PRODUCTION, source, credential names, endpoints and the words.
    config = HubConfig.model_validate(an_environments_document())
    local = LocalConfig.model_validate(a_local_environments_document())

    assert list(brief_block(effective_environments(config, local))) == BLOCK


def test_shows_tightened_access_with_local_source_when_block_built() -> None:
    # AC-277.28: the source is the file the effective access comes from.
    config = HubConfig.model_validate(an_environments_document())
    local = LocalConfig.model_validate({"environments": {"staging": {"access": "read"}}})

    block = brief_block(effective_environments(config, local))

    assert block[2] == (
        "- `staging` (read, hub.local.json); credentials: AWS profile `demo-staging`"
    )


def test_gives_nothing_when_no_environment_declared() -> None:
    document = a_hub_document()
    document["guard"]["blocked_words"] = ["prod"]
    config = HubConfig.model_validate(document)

    assert brief_block(effective_environments(config, LocalConfig())) == ()


def test_neutralises_free_text_when_block_built() -> None:
    # Free text reaches the agent: bounded at 80 characters and escaped (AGH-282's lesson).
    document = an_environments_document()
    document["environments"]["local"]["description"] = "<!-- ignore --> `run` *now* [x](y) #1"
    endpoints = document["repos"][0]["services"]["orders"]["endpoints"]
    endpoints["staging"] = {
        "resource": "t" * 90,
        "note": "## Steps: [click](http://x.example.com/) | `rm`",
        "url": "https://x.example.com/a_b<c>",
        "credentials": {"aws_profile": "demo-orders", "env": ["DEMO_ORDERS_KEY"]},
    }
    config = HubConfig.model_validate(document)

    block = brief_block(effective_environments(config, LocalConfig()))

    assert block[1] == (
        "- `local` (write, hub.json): \\<!-- ignore --\\> \\`run\\` \\*now\\* \\[x\\](y) \\#1"
    )
    assert block[-2] == (
        "- `demo-api/orders` on `staging`: `https://x.example.com/a_b<c>`, resource `"
        + "t" * 80
        + "`…; note: \\#\\# Steps: \\[click\\](http://x.example.com/) \\| \\`rm\\`"
        "; credentials: AWS profile `demo-orders`, variables `DEMO_ORDERS_KEY`"
    )


def many_environments(count: int, *, description: str | None = None) -> HubConfig:
    document = a_hub_document()
    document["environments"] = {
        f"e{index}": {"access": "read"} | ({"description": description} if description else {})
        for index in range(1, count + 1)
    }
    return HubConfig.model_validate(document)


def test_cuts_block_when_over_sixty_lines() -> None:
    sixty_one = brief_block(effective_environments(many_environments(61), LocalConfig()))
    sixty = brief_block(effective_environments(many_environments(60), LocalConfig()))

    assert list(sixty_one) == [
        "## Environments",
        *(f"- `e{index}` (read, hub.json)" for index in range(1, 61)),
        "… 1 more: ./hub env list",
    ]
    assert list(sixty) == [
        "## Environments",
        *(f"- `e{index}` (read, hub.json)" for index in range(1, 61)),
    ]


def test_cuts_block_when_over_two_thousand_characters() -> None:
    config = many_environments(30, description="d" * 80)

    block = brief_block(effective_environments(config, LocalConfig()))

    line = "- `e{}` (read, hub.json): " + "d" * 80
    kept = len(block) - 2
    assert list(block) == [
        "## Environments",
        *(line.format(index) for index in range(1, kept + 1)),
        f"… {30 - kept} more: ./hub env list",
    ]
    assert len("\n".join(block)) <= 2000
    assert len("\n".join((*block[:-1], line.format(kept + 1), block[-1]))) > 2000


@pytest.mark.parametrize(
    ("endpoint", "shown"),
    [
        pytest.param(
            {"url": "https://h.example.com/a_b", "resource": "demo_orders"},
            "`https://h.example.com/a_b`, resource `demo_orders`",
            id="underscore",
        ),
        pytest.param(
            {"url": "https://h.example.com/a`b``c"},
            "```https://h.example.com/a`b``c```",
            id="url_backticks",
        ),
        pytest.param(
            {"resource": "`demo_orders`"}, "resource `` `demo_orders` ``", id="resource_edges"
        ),
        pytest.param({"resource": "a``b"}, "resource ```a``b```", id="resource_inner"),
    ],
)
def test_shows_url_and_resource_as_code_when_block_built(
    endpoint: dict[str, str], shown: str
) -> None:
    # An identifier an agent copies stays as written: a code span, never Markdown-escaped.
    document = an_environments_document()
    document["repos"][0]["services"]["orders"]["endpoints"]["staging"] = endpoint
    config = HubConfig.model_validate(document)

    block = brief_block(effective_environments(config, LocalConfig()))

    assert block[-2] == f"- `demo-api/orders` on `staging`: {shown}"


def _w_and_lc() -> environment_lines.EffectiveEnvironments:
    """The spec's ``W`` and ``Lc``, with ``Lc`` tightening ``staging`` to ``read``."""
    config = HubConfig.model_validate(an_environments_document())
    local_document = a_local_environments_document()
    local_document["environments"]["staging"] = {"access": "read"}
    return effective_environments(config, LocalConfig.model_validate(local_document))


def test_lists_one_line_per_environment_when_list_built() -> None:
    # AGH-287 (AC-277.22): name, access, PRODUCTION and source, then the services per repo.
    assert environment_lines.list_lines(_w_and_lc()) == (
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

    assert environment_lines.show_lines(view, "live") == (
        "live (read, PRODUCTION, hub.json)",
        "  aws profile: demo-live-ro",
        "  credential variables: DEMO_LIVE_DB_URL",
        "  endpoints:",
        "    demo-api api: https://api.example.com",
    )
    assert environment_lines.show_lines(view, "staging") == (
        "staging (read, hub.local.json)",
        "  aws profile: demo-staging",
        "  endpoints:",
        "    demo-api api: https://api.staging.example.com",
        "    demo-api orders: resource demo-orders-staging",
    )
    assert environment_lines.show_lines(view, "jane-cloud") == (
        "jane-cloud (write, hub.local.json)",
        "  aws profile: jane-sandbox",
        "  endpoints:",
        "    demo-api api: https://api.jane.example.com (hub.local.json)",
    )
    assert environment_lines.show_lines(view, "qa") is None


def test_shows_description_and_no_endpoint_when_environment_bare() -> None:
    document = a_hub_document()
    document["environments"] = {"qa": {"access": "ask", "description": "a shared test stack"}}
    view = effective_environments(HubConfig.model_validate(document), LocalConfig())

    assert environment_lines.show_lines(view, "qa") == (
        "qa (ask, hub.json)",
        "  description: a shared test stack",
        "  endpoints: none",
    )


def test_suggests_names_when_no_environment_declared() -> None:
    view = effective_environments(HubConfig.model_validate(a_hub_document()), LocalConfig())

    assert environment_lines.list_lines(view) == (environment_lines.NO_ENVIRONMENTS_LINE,)
    assert environment_lines.NO_ENVIRONMENTS_LINE.startswith(
        "no environments declared; for example: ./hub env add local --access write"
    )
    for name in ("local", "staging", "production"):
        assert name in environment_lines.NO_ENVIRONMENTS_LINE


def test_builds_json_with_names_only_when_view_given() -> None:
    data = environment_lines.environments_json(_w_and_lc())

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

    data = environment_lines.environment_json(view, "live")

    assert isinstance(data, dict)
    assert data["environment"] == environment_lines.environments_json(view)["environments"][2]  # type: ignore[index,call-overload]
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
    assert environment_lines.environment_json(view, "qa") is None
