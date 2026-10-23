from typing import Any

import pytest

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig, check_local_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.environment_values import with_environment_values
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.engine import start_inputs
from agent_hub.core.workflows.launch import RunInputError
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow


def a_plan(inputs: dict[str, Any]) -> WorkflowPlan:
    document = parse_workflow(
        {
            "version": 1,
            "kind": "scenario",
            "name": "credit-order",
            "revision": 1,
            "inputs": inputs,
            "nodes": [{"id": "pause", "type": "wait", "duration": "1s"}],
        }
    )
    return plan_workflow(document)


def a_view(values: dict[str, str], *, local: dict[str, Any] | None = None) -> EffectiveEnvironments:
    document = an_environments_document()
    document["environments"]["staging"]["values"] = values
    checked = check_local_document(local or {})
    assert isinstance(checked, LocalConfig), checked
    return effective_environments(HubConfig.model_validate(document), checked)


PLAN = a_plan(
    {
        "personal_name": {"type": "string", "default": "nobody"},
        "aws_account_id": {"type": "string", "default": "000000000000"},
        "order_count": {"type": "integer", "default": 1},
        "dry": {"type": "boolean", "default": False},
        "ratio": {"type": "number", "default": 0.5},
        "ref": {"type": "string", "required": True},
    }
)


def test_takes_environment_value_when_input_not_given() -> None:
    view = a_view(
        {
            "personal_name": "jose-personal",
            "order_count": "3",
            "dry": "true",
            "ratio": "1.5",
            "ref": "T-9",
            "not_declared": "ignored",
        }
    )

    filled = with_environment_values(PLAN, {}, view=view, environment="staging")

    assert filled == {
        "personal_name": "jose-personal",
        "order_count": 3,
        "dry": True,
        "ratio": 1.5,
        "ref": "T-9",
    }


def test_orders_given_then_environment_then_default_when_inputs_filled() -> None:
    view = a_view({"personal_name": "jose-personal", "aws_account_id": "123456789012"})
    given: dict[str, JsonValue] = {"personal_name": "asked", "ref": "T-1"}

    effective = start_inputs(
        PLAN, with_environment_values(PLAN, given, view=view, environment="staging")
    )

    assert effective == {
        "personal_name": "asked",
        "aws_account_id": "123456789012",
        "order_count": 1,
        "dry": False,
        "ratio": 0.5,
        "ref": "T-1",
    }


def test_prefers_local_value_when_both_files_set_it() -> None:
    view = a_view(
        {"personal_name": "team", "aws_account_id": "111111111111"},
        local={"environments": {"staging": {"values": {"personal_name": "jose-personal"}}}},
    )

    filled = with_environment_values(PLAN, {}, view=view, environment="staging")

    assert filled == {"personal_name": "jose-personal", "aws_account_id": "111111111111"}


@pytest.mark.parametrize("environment", ["local", "qa"], ids=["no_values", "undeclared"])
def test_gives_inputs_back_when_environment_has_no_values(environment: str) -> None:
    view = a_view({"personal_name": "jose-personal"})

    assert with_environment_values(PLAN, {"ref": "T-1"}, view=view, environment=environment) == {
        "ref": "T-1"
    }


@pytest.mark.parametrize(
    ("name", "text", "kind"),
    [
        ("order_count", "three", "integer"),
        ("order_count", "1.5", "integer"),
        ("ratio", "nan", "number"),
        ("ratio", "x", "number"),
        ("dry", "yes", "boolean"),
    ],
    ids=["integer_word", "integer_fraction", "number_nan", "number_word", "boolean_yes"],
)
def test_refuses_value_when_it_does_not_read_as_input_type(name: str, text: str, kind: str) -> None:
    view = a_view({name: text})

    with pytest.raises(RunInputError) as raised:
        with_environment_values(PLAN, {}, view=view, environment="staging")

    assert str(raised.value) == (
        f'the value of "{name}" in environment "staging" must be of type {kind}'
    )
