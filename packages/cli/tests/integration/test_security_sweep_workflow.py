"""The built-in ``security-sweep`` pack (AGH-486): the workflow loads and plans, its nodes are
read-only on code and write no tracker (ADR 0030), and the triage reply is bounded.
"""

from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "security-sweep"
NAME = "security-sweep"
# AC-1 (a first run keeps one, a second lists none), AC-2 (no scanner installed), and a failed
# triage that marks nothing seen.
FIXTURES = ("sweep-findings", "sweep-nothing-new", "sweep-no-scanners", "sweep-triage-failed")


def document() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == NAME]
    return parse_workflow(workflow.document)


def nodes_of() -> dict[str, Any]:
    return {node.id: node for node in document().nodes}


def test_validates_and_passes_every_fixture_when_security_sweep_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", NAME)
    tested = run_command(demo_workspace.hub, "workflow", "test", NAME)

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "security-sweep: valid (5 nodes in 5 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/security-sweep/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning" not in tested.stdout
    assert tested.stdout.endswith("4 fixtures: 4 passed, 0 failed\n")


def test_declares_read_only_nodes_and_no_tracker_step_when_document_loaded() -> None:
    loaded = document()
    nodes = nodes_of()

    assert set(loaded.inputs) == {"repo"}
    assert loaded.inputs["repo"].default == ""
    assert loaded.environment is None
    assert [node.type for node in loaded.nodes] == ["script", "script", "agent", "script", "script"]
    for node in loaded.nodes:
        assert getattr(node, "command", ())[:2] != ("hub", "step")
        assert node.retry is not None
        assert node.retry.max_attempts == 0
    for node_id in ("scan", "new"):
        assert nodes[node_id].effect == "read"
    for node_id in ("scan", "new", "triage"):
        assert nodes[node_id].mutates_checkout is False
    assert nodes["triage"].when is not None
    assert "$new.output.listed" in nodes["triage"].when
    assert nodes["triage"].model == "large"
    assert nodes["report"].trigger_rule == "none_failed_min_one_success"
    assert nodes["mark"].depends_on == ("report",)
    assert loaded.returns == "mark"
    assert loaded.outcome_field == "status"


def a_reply(kept: int = 100, attack: str = "a" * 400) -> dict[str, Any]:
    return {
        "kept": [{"id": f"F{n}", "attack": attack, "fix": "f" * 400} for n in range(1, kept + 1)],
        "unresolved": [{"id": f"F{n}", "why": "w" * 300} for n in range(1, 21)],
        "dropped": 0,
    }


def test_bounds_triage_reply_when_outputs_validated() -> None:
    schema = nodes_of()["triage"].output_format
    outputs = JsonSchemaOutputs()
    outputs.check(schema, a_reply())
    bad_ids = [
        {**a_reply(kept=1), "kept": [{"id": wrong, "attack": "", "fix": ""}]}
        for wrong in ("F0", "G1")
    ]

    for wrong in (a_reply(kept=101), a_reply(attack="a" * 401), *bad_ids):
        with pytest.raises(NodeFailedError):
            outputs.check(schema, wrong)
