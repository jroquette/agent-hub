import pytest

from agent_hub.core.hub_config.effective_environments import effective_environments
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)
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
