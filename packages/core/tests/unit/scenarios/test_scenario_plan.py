"""A scenario's plan: one row per action step and the problems that refuse its start
(AC-350.17, AC-350.18, AC-350.42, E-6; docs/design/scenarios.md § Plan and modes)."""

from typing import Any

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.action_catalog import ActionEntry
from agent_hub.core.scenarios.action_document import parse_action
from agent_hub.core.scenarios.scenario_plan import ScenarioPlan, plan_scenario
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.plan import plan_workflow

HASH = "sha256:" + "0" * 64


def an_entry(name: str, effect: str, *, draft: bool = False) -> ActionEntry:
    document = parse_action(
        {
            "version": 1,
            "name": name,
            "description": "A demo action",
            "effect": effect,
            "runtime": "sh",
            "script": f"scripts/{name}.sh",
            "inputs": {
                "target": {"type": "service", "required": True},
                "ref": {"type": "string"},
                "count": {"type": "integer", "default": 1},
            },
            "output_format": {
                "type": "object",
                "properties": {"order": {"type": "string"}, "status": {"type": "string"}},
            },
        }
    )
    return ActionEntry(
        pack="demo",
        document=document,
        document_path=f"actions/demo/{name}.yaml",
        script_path=f"actions/demo/scripts/{name}.sh",
        content_hash=HASH,
        draft=draft,
    )


ACTIONS = (an_entry("get-order", "read"), an_entry("send-order", "write"))


def a_view() -> EffectiveEnvironments:
    document = an_environments_document()
    document["environments"]["review"] = {"access": "read"}
    endpoints = document["repos"][0]["services"]["api"]["endpoints"]
    endpoints["review"] = {"url": "https://api.review.example.com"}
    return effective_environments(HubConfig.model_validate(document), LocalConfig())


def a_walk(*extra: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "send-order",
            "type": "action",
            "action": "send-order",
            "with": {"target": "api", "ref": "$INPUTS.ref"},
        },
        {
            "id": "order-held",
            "type": "expect",
            "depends_on": ["send-order"],
            "action": "demo/get-order",
            "with": {"target": "api", "ref": "$INPUTS.ref", "count": 2},
            "every": "10s",
            "timeout": "5m",
            "until_when": "$self.output.status == 'ON_HOLD'",
            "capture": {"order_id": "$self.output.order"},
        },
        {
            "id": "check-order",
            "type": "action",
            "depends_on": ["order-held"],
            "action": "get-order",
            "with": {"target": "api", "ref": "order $CTX.order_id"},
        },
        *extra,
    ]


def planned(
    nodes: list[dict[str, Any]],
    *,
    environment: str = "local",
    actions: tuple[ActionEntry, ...] = ACTIONS,
    inputs: dict[str, JsonValue] | None = None,
) -> ScenarioPlan:
    document = parse_workflow(
        {
            "version": 1,
            "kind": "scenario",
            "name": "order-walk",
            "revision": 1,
            "inputs": {"ref": {"type": "string", "required": True}},
            "nodes": nodes,
        }
    )
    return plan_scenario(
        plan_workflow(document),
        pack="demo",
        actions=actions,
        view=a_view(),
        environment=environment,
        inputs={"ref": "T-1"} if inputs is None else inputs,
    )


def test_lists_rows_when_scenario_planned() -> None:
    plan = planned(a_walk())

    assert plan.problems == ()
    assert not plan.denied
    assert (plan.environment, plan.access, plan.production) == ("local", "write", False)
    rows = [
        (row.step, row.type, row.action, row.effect, row.decision, row.draft, row.known)
        for row in plan.rows
    ]
    assert rows == [
        ("send-order", "action", "demo/send-order", "write", "allow", False, True),
        ("order-held", "expect", "demo/get-order", "read", "allow", False, True),
        ("check-order", "action", "demo/get-order", "read", "allow", False, False),
    ]
    send, held, _ = plan.rows
    assert send.args == {"target": "api", "ref": "T-1", "count": "1"}
    assert send.content_hash == HASH
    assert send.call is not None
    assert send.call.inputs == {"target": "api", "ref": "T-1", "count": 1}
    assert send.call.endpoint == {"target": {"url": "http://localhost:8000", "resource": None}}
    assert send.call.services == ("demo-api/api",)
    assert (send.every, send.timeout) == (None, None)
    assert held.args == {"target": "api", "ref": "T-1", "count": "2"}
    assert (held.every, held.timeout) == ("10s", "5m")


def test_shows_ctx_placeholder_when_arg_known_at_run_time() -> None:
    plan = planned(a_walk())

    check = plan.rows[2]
    assert check.args == {
        "target": "api",
        "ref": "order <$CTX.order_id from order-held>",
        "count": "1",
    }
    # Its service is a literal, so its endpoint is known; its call is not.
    assert check.call is None
    assert check.endpoints == {"target": ("demo-api/api", "http://localhost:8000", None)}


def test_denies_write_rows_when_deny_refuses_start_access_read() -> None:
    plan = planned(a_walk(), environment="review")

    assert [(row.step, row.decision, row.reason_kind) for row in plan.rows] == [
        ("send-order", "deny", "table"),
        ("order-held", "allow", "table"),
        ("check-order", "allow", "table"),
    ]
    assert plan.denied
    assert plan.problems == ()
    draft = planned(a_walk(), actions=(ACTIONS[0], an_entry("send-order", "write", draft=True)))
    assert (draft.rows[0].decision, draft.rows[0].reason_kind, draft.rows[0].draft) == (
        "deny",
        "draft",
        True,
    )


def test_reports_undeclared_when_environment_unknown() -> None:
    plan = planned(a_walk(), environment="qa")

    assert plan.problems == ("environment qa is not declared",)
    assert plan.access is None
    assert {(row.decision, row.reason_kind) for row in plan.rows} == {("deny", "undeclared")}
    assert all(row.call is None and row.endpoints == {} for row in plan.rows)
    assert plan.denied


def test_reports_both_steps_when_unordered_gates_needed() -> None:
    other = {
        "id": "send-again",
        "type": "action",
        "action": "send-order",
        "with": {"target": "api"},
    }

    on_ask = planned(a_walk(other), environment="staging")
    on_write = planned(a_walk(other), environment="local")
    with_approval = planned(
        [*a_walk(), {"id": "confirm", "type": "approval", "message": "Go on?"}],
        environment="staging",
    )

    assert on_ask.problems == (
        "steps send-order and send-again both need a gate and have no order between them:"
        " one must depend on the other",
    )
    assert on_ask.denied
    assert on_write.problems == ()
    assert with_approval.problems == (
        "steps send-order and confirm both need a gate and have no order between them:"
        " one must depend on the other",
    )


def test_reports_path_when_scenario_plan_reads_path_outside_output() -> None:
    nodes = a_walk()
    nodes[1]["capture"] = {"order_id": "$self.output.order_ref"}
    nodes[2]["with"] = {"target": "api", "ref": "$order-held.output.missing", "count": 1}
    nodes[2]["when"] = "$send-order.output.status == 'SENT'"

    plan = planned(nodes)

    assert plan.problems == (
        'step order-held: capture.order_id: the path "order_ref" is not in the output'
        " of demo/get-order",
        'step check-order: with.ref: the path "missing" is not in the output of demo/get-order',
    )
    assert plan.denied


def test_reports_action_and_service_when_scenario_plan_cannot_resolve_them() -> None:
    nodes = a_walk()
    nodes[0]["action"] = "billing/send-order"
    nodes[1]["with"] = {"target": "orders", "ref": "$INPUTS.ref"}

    plan = planned(nodes, environment="local")

    assert plan.problems == (
        "step send-order: unknown action 'billing/send-order'",
        "step order-held: input target: service orders has no endpoint in environment local",
    )
    assert [row.step for row in plan.rows] == ["order-held", "check-order"]


def test_reports_nothing_when_unordered_gates_check_long_reverse_chain() -> None:
    # 1500 asking steps declared in reverse dependency order: a0 depends on a1, ... a1499.
    count = 1500
    nodes = [
        {
            "id": f"a{index}",
            "type": "action",
            "action": "send-order",
            "with": {"target": "api"},
            **({"depends_on": [f"a{index + 1}"]} if index + 1 < count else {}),
        }
        for index in range(count)
    ]

    plan = planned(nodes, environment="staging")

    assert plan.problems == ()
    assert len(plan.rows) == count
    assert {row.decision for row in plan.rows} == {"ask"}
