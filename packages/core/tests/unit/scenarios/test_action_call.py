"""One action call's plan: its typed inputs and each ``service`` input's endpoint (AC-350.8)."""

from typing import Any

import pytest

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.scenarios.action_call import ActionCallError, plan_action_call
from agent_hub.core.scenarios.action_document import ActionDocument, parse_action
from agent_hub.core.testing.builders import a_second_repo, an_environments_document


def an_action(**inputs: dict[str, Any]) -> ActionDocument:
    return parse_action(
        {
            "version": 1,
            "name": "send",
            "description": "Send one demo message",
            "effect": "write",
            "runtime": "sh",
            "script": "scripts/send.sh",
            "inputs": inputs,
            "output_format": {"type": "object"},
        }
    )


def a_view(*, second_api: bool = False) -> EffectiveEnvironments:
    document = an_environments_document()
    if second_api:
        repo = a_second_repo()
        repo["services"] = {"api": {"endpoints": {"staging": {"url": "https://web.example.com"}}}}
        document["repos"].append(repo)
    return effective_environments(HubConfig.model_validate(document), LocalConfig())


def test_resolves_endpoint_when_service_input_named() -> None:
    action = an_action(
        target={"type": "service", "required": True},
        table={"type": "service", "required": True},
        count={"type": "integer", "default": 3},
    )

    plan = plan_action_call(
        action,
        {"target": "api", "table": "demo-api/orders"},
        environment="staging",
        view=a_view(),
    )

    assert plan.inputs == {"target": "api", "table": "demo-api/orders", "count": 3}
    assert plan.endpoint == {
        "target": {"url": "https://api.staging.example.com", "resource": None},
        "table": {"url": None, "resource": "demo-orders-staging"},
    }
    assert plan.services == ("demo-api/api", "demo-api/orders")
    assert [endpoint.resource for endpoint in plan.endpoints] == [None, "demo-orders-staging"]


def test_reports_service_and_environment_when_service_input_has_no_endpoint() -> None:
    action = an_action(table={"type": "service", "required": True})

    with pytest.raises(ActionCallError) as raised:
        plan_action_call(action, {"table": "orders"}, environment="live", view=a_view())

    assert str(raised.value) == "input table: service orders has no endpoint in environment live"


def test_reports_ambiguous_when_service_input_in_two_repos() -> None:
    action = an_action(target={"type": "service", "required": True})
    view = a_view(second_api=True)

    with pytest.raises(ActionCallError) as raised:
        plan_action_call(action, {"target": "api"}, environment="staging", view=view)

    assert str(raised.value) == (
        "input target: service api is in more than one repo (demo-api, demo-web):"
        " name it as <repo>/api"
    )
    plan = plan_action_call(action, {"target": "demo-web/api"}, environment="staging", view=view)
    assert plan.endpoint["target"]["url"] == "https://web.example.com"


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({"count": "three"}, "input count must be of type integer"),
        ({"count": True}, "input count must be of type integer"),
        ({"count": 1, "other": "x"}, "unknown input other"),
        ({}, "input count is required"),
        ({"count": 1, "target": "nope"}, "input target: no service nope in repos[].services"),
    ],
)
def test_refuses_value_when_input_type_mismatch(given: dict[str, Any], message: str) -> None:
    action = an_action(count={"type": "integer", "required": True}, target={"type": "service"})

    with pytest.raises(ActionCallError) as raised:
        plan_action_call(action, given, environment="staging", view=a_view())

    assert str(raised.value) == message
