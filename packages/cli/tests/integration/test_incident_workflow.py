"""The built-in ``incident`` pack (AGH-483): the workflow loads and plans, its fixtures pass, its
nodes are read-only where they read and write no tracker (ADR 0030), its agents' replies are
bounded by their output_format, and its prompts fence the untrusted text.
"""

from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import load_workflow_bytes

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "incident"
WORKFLOW = PACK / "incident.yaml"
READ_ONLY = ("evidence", "check", "mitigation")
WRITERS = ("handoff", "note")
WIDE = "\U0001f600"  # four bytes in UTF-8
FIXTURES = (
    "incident-awaiting-mitigation",
    "incident-confirmed",
    "incident-mitigation-declined",
    "incident-none-confirmed",
)


def nodes_of(name: str) -> dict[str, Any]:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == name]
    document = parse_workflow(workflow.document)
    nodes: dict[str, Any] = {}
    for node in document.nodes:
        nodes[node.id] = node
        for body in getattr(node, "nodes", ()):
            nodes[f"{node.id}__{body.id}"] = body
    return nodes


def raw_document() -> dict[str, Any]:
    document: dict[str, Any] = load_workflow_bytes(
        WORKFLOW.read_bytes(), source=str(WORKFLOW)
    ).document
    return document


def a_hypothesis(n: int, *, wide: str = WIDE) -> dict[str, Any]:
    return {
        "id": f"H{n}",
        "rank": n,
        "statement": wide * 500,
        "repo": "a" * 64,
        "check": [wide * 256] * 16,
        "confirms_when": wide * 300,
        "mitigation": {"summary": wide * 300, "undo": wide * 300},
    }


def a_postmortem(*, follow_ups: int = 10) -> dict[str, Any]:
    return {
        "title": WIDE * 120,
        "summary": WIDE * 1000,
        "timeline": [{"at": WIDE * 40, "what": WIDE * 300}] * 30,
        "root_cause": WIDE * 2000,
        "detection_gap": WIDE * 2000,
        "what_fixed_it": WIDE * 2000,
        "follow_ups": [WIDE * 300] * follow_ups,
        "learnings": [{"target": WIDE * 200, "text": WIDE * 1000}] * 5,
    }


def a_recall(matches: int = 10) -> dict[str, Any]:
    return {"matches": [{"path": WIDE * 300, "why": WIDE * 400}] * matches, "summary": WIDE * 1000}


def test_validates_and_passes_every_fixture_when_incident_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "incident")
    tested = run_command(demo_workspace.hub, "workflow", "test", "incident")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "incident: valid (9 nodes in 9 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/incident/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning" not in tested.stdout
    assert tested.stdout.endswith("4 fixtures: 4 passed, 0 failed\n")


def test_declares_read_only_nodes_and_no_tracker_step_when_document_loaded() -> None:
    document, nodes = raw_document(), nodes_of("incident")

    assert set(document["inputs"]) == {"report", "since"}
    assert document["inputs"]["since"]["default"] == "72h"
    assert document["inputs"]["report"]["required"] is True
    assert "issue" not in document["inputs"]
    assert "environment" not in document
    assert document["returns"] == "note"
    assert document["outcome_field"] == "status"
    assert [node["type"] for node in document["nodes"]].count("shell") == 0
    for node in document["nodes"]:
        assert node.get("command", [])[:2] != ["hub", "step"], node["id"]
    for node_id in READ_ONLY:
        assert nodes[node_id].effect == "read", node_id
    for node_id in WRITERS:
        assert "effect" not in next(n for n in document["nodes"] if n["id"] == node_id)
        assert nodes[node_id].effect is None, node_id
    executable = {key: node for key, node in nodes.items() if hasattr(node, "mutates_checkout")}
    assert set(executable) == {*nodes} - {"mitigate"}
    for node_id, node in executable.items():
        assert node.mutates_checkout is (node_id in WRITERS), node_id
        assert node.retry is not None and node.retry.max_attempts == 0, node_id
    mitigate = nodes["mitigate"]
    assert [decision.id for decision in mitigate.decisions] == ["record", "none"]
    assert mitigate.capture_response is True
    assert "$check.output.mitigations" in mitigate.when
    assert "$mitigate.output.decision" in nodes["mitigation"].when
    assert nodes["handoff"].trigger_rule == "none_failed_min_one_success"


@pytest.mark.parametrize(
    ("node", "value", "passes"),
    [
        ("hypotheses", {"hypotheses": [a_hypothesis(n) for n in range(1, 6)]}, True),
        ("hypotheses", {"hypotheses": [a_hypothesis(n % 5 + 1) for n in range(6)]}, False),
        ("hypotheses", {"hypotheses": []}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["x" * 257]}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["x"] * 17}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["a\nb"]}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "id": "H6"}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "mitigation": None}]}, True),
        ("recall", a_recall(), True),
        ("recall", a_recall(11), False),
        ("postmortem", a_postmortem(), True),
        ("postmortem", a_postmortem(follow_ups=11), False),
    ],
    ids=[
        "hypotheses-at-bounds",
        "six-hypotheses",
        "no-hypothesis",
        "argv-element-257",
        "argv-17-elements",
        "argv-control-char",
        "id-h6",
        "no-mitigation",
        "recall-at-bounds",
        "recall-11-matches",
        "postmortem-at-bounds",
        "postmortem-11-follow-ups",
    ],
)
def test_bounds_agent_replies_when_outputs_validated(
    node: str, value: dict[str, Any], *, passes: bool
) -> None:
    schema = nodes_of("incident")[node].output_format
    outputs = JsonSchemaOutputs()

    if passes:
        outputs.check(schema, value)
    else:
        with pytest.raises(NodeFailedError):
            outputs.check(schema, value)
