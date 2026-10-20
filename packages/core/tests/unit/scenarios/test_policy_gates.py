"""Policy asks as planner-inserted approvals, ``<step>__ask`` (P-4, AM-14, AC-350.5;
docs/design/scenarios.md § Policy)."""

from collections.abc import Mapping

import pytest

from agent_hub.core.scenarios.policy_gates import (
    PolicyAsk,
    PolicyGateError,
    gated_plan,
    with_policy_gates,
)
from agent_hub.core.workflows.document import WorkflowDocument, parse_workflow
from agent_hub.core.workflows.gates import reject_cancels
from agent_hub.core.workflows.nodes import ApprovalNode, LoopGroupNode

GET: dict[str, object] = {"id": "get", "type": "action", "action": "get-order"}
SEND: dict[str, object] = {
    "id": "send",
    "type": "action",
    "action": "send-order",
    "depends_on": ["get"],
    "trigger_rule": "all_done",
    "when": "$INPUTS.go == true",
}
ASK = PolicyAsk(action="demo/send-order", effect="write", environment="staging")


def a_scenario(*nodes: Mapping[str, object]) -> WorkflowDocument:
    return parse_workflow(
        {
            "version": 1,
            "kind": "scenario",
            "name": "demo",
            "revision": 1,
            "inputs": {"go": {"type": "boolean", "default": True}},
            "nodes": list(nodes),
        }
    )


def test_inserts_gate_before_step_when_policy_asks() -> None:
    gated = with_policy_gates(a_scenario(GET, SEND), {"send": ASK})

    assert [node.id for node in gated.nodes] == ["get", "send__ask", "send"]
    gate, step = gated.nodes[1], gated.nodes[2]
    assert isinstance(gate, ApprovalNode)
    # The gate runs exactly when the step would have; the step runs only once it is approved.
    assert (gate.depends_on, gate.trigger_rule, gate.when) == (
        ("get",),
        "all_done",
        "$INPUTS.go == true",
    )
    assert (step.depends_on, step.trigger_rule, step.when) == (
        ("send__ask",),
        "all_success",
        "$INPUTS.go == true",
    )
    assert gate.message == (
        "policy ask: step send runs demo/send-order (write) in staging; approve to run it"
    )
    assert "$" not in gate.message.replace("$INPUTS", "")
    assert reject_cancels(gate, list(gated.nodes))
    plan = gated_plan(a_scenario(GET, SEND), includes=None, asks={"send": ASK})
    assert plan.layers == (("get",), ("send__ask",), ("send",))


def test_inserts_gate_in_body_when_step_in_loop_group() -> None:
    body: dict[str, object] = {"id": "send", "type": "action", "action": "send-order"}
    group: dict[str, object] = {
        "id": "batch",
        "type": "loop_group",
        "depends_on": ["get"],
        "max_iterations": 2,
        "until_when": "$LOOP_PREV.send.output.status == 'done'",
        "nodes": [body],
    }

    gated = with_policy_gates(a_scenario(GET, group), {"batch__send": ASK})
    plan = gated_plan(a_scenario(GET, group), includes=None, asks={"batch__send": ASK})

    assert [node.id for node in gated.nodes] == ["get", "batch"]
    gated_group = gated.nodes[1]
    assert isinstance(gated_group, LoopGroupNode)
    assert [node.id for node in gated_group.nodes] == ["send__ask", "send"]
    assert gated_group.nodes[1].depends_on == ("send__ask",)
    assert plan.bodies["batch"] == (("batch__send__ask",), ("batch__send",))
    assert [node.id for node in plan.all_nodes()] == [
        "get",
        "batch",
        "batch__send__ask",
        "batch__send",
    ]


def test_keeps_document_when_no_ask() -> None:
    document = a_scenario(GET, SEND)

    assert with_policy_gates(document, {}) is document
    assert gated_plan(document, includes=None, asks={}).layers == (("get",), ("send",))


def test_refuses_ask_when_policy_gates_name_no_step() -> None:
    with pytest.raises(PolicyGateError, match="no step missing"):
        with_policy_gates(a_scenario(GET, SEND), {"missing": ASK})
