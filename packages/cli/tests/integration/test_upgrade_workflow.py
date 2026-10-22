"""The built-in ``upgrade`` pack (AGH-484): the workflow loads and plans, its fixtures pass, one
package per run with the ``size`` condition, the adapt loop's three rounds, and every push behind
the ``publish`` approval with no tracker write (ADR 0030).
"""

from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "upgrade"
NAME = "upgrade"


def document() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == NAME]
    return parse_workflow(workflow.document)


def nodes_of() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    for node in document().nodes:
        nodes[node.id] = node
        for body in getattr(node, "nodes", ()):
            nodes[f"{node.id}__{body.id}"] = body
    return nodes


def test_validates_and_passes_every_fixture_when_upgrade_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", NAME)

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "upgrade: valid (15 nodes in 15 layers)\n"


def test_declares_one_package_and_the_size_condition_when_document_loaded() -> None:
    loaded, nodes = document(), nodes_of()

    assert set(loaded.inputs) == {"issue", "repo", "package", "to"}
    assert all(spec.required for spec in loaded.inputs.values())
    adapt = nodes["adapt"]
    assert adapt.max_iterations == 3
    assert adapt.until_when.startswith("$fix.output.status == 'blocked'")
    assert "$recheck.output.round >= 3" in adapt.until_when
    size = nodes["size"]
    for clause in ("$bump.output.major == true", "found == false", "touched > 5"):
        assert clause in size.when
    assert nodes["changelog"].mutates_checkout is False
    for node in nodes.values():
        if node.type in {"agent", "script", "shell"}:
            assert node.retry is not None and node.retry.max_attempts == 0, node.id
    assert nodes["check"].args == ("$gate.output.check_fast",)
    assert nodes["check-full"].args == ("$worktree.output.check",)


def test_reads_the_fast_gate_from_hub_json_in_the_hub_when_document_loaded() -> None:
    gate = nodes_of()["gate"]

    # The pack's own script, in the hub (no cwd), before any agent: hub step worktree's
    # output stays as it is.
    assert (gate.type, gate.script, gate.cwd) == ("script", "fast_gate.py", None)
    assert gate.args == ("--repo", "$INPUTS.repo", "--full", "$worktree.output.check")
    assert gate.depends_on == ("worktree",)


def test_puts_the_push_behind_an_approval_when_document_loaded() -> None:
    loaded, nodes = document(), nodes_of()

    assert nodes["pr"].depends_on == ("publish",)
    publish = nodes["publish"]
    assert publish.type == "approval"
    assert [decision.id for decision in publish.decisions] == ["approve", "reject"]
    assert "decisions" not in publish.model_fields_set
    steps = {
        node.command[2]
        for node in nodes.values()
        if node.type == "shell" and tuple(node.command[:2]) == ("hub", "step")
    }
    assert steps == {"worktree", "commits", "pr", "report"}
    assert (loaded.returns, loaded.outcome_field) == ("report", "delivery")
