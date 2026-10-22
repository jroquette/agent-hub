"""The built-in ``post-merge-verify`` pack (AGH-490): its workflow loads and plans, its fixtures
pass, its nodes keep the invariants (no retry hides a failure, read-only agents, no tracker
write: ADR 0030).
"""

from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.nodes import ShellNode
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "post-merge-verify"
FIXTURES = (
    "verify-all-green",
    "verify-cannot-run",
    "verify-explain-failed",
    "verify-regression",
)


def loaded() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "post-merge-verify"]
    return parse_workflow(workflow.document)


def nodes_of() -> dict[str, Any]:
    return {node.id: node for node in loaded().nodes}


def test_validates_and_passes_every_fixture_when_post_merge_verify_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "post-merge-verify")
    tested = run_command(demo_workspace.hub, "workflow", "test", "post-merge-verify")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "post-merge-verify: valid (4 nodes in 4 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/post-merge-verify/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning" not in tested.stdout
    assert tested.stdout.endswith("4 fixtures: 4 passed, 0 failed\n")


def test_declares_no_retry_and_read_only_nodes_when_document_loaded() -> None:
    document = loaded()
    nodes = nodes_of()

    assert set(nodes) == {"select", "run", "explain", "report"}
    for node_id in ("select", "run", "explain", "report"):
        assert nodes[node_id].retry is not None
        assert nodes[node_id].retry.max_attempts == 0, node_id
    assert nodes["select"].mutates_checkout is False
    assert nodes["explain"].mutates_checkout is False
    assert nodes["run"].timeout == "12h"
    assert nodes["explain"].when is not None
    assert "$run.output.broken" in nodes["explain"].when
    assert set(document.inputs) == {"repo", "sha", "ref"}
    assert "issue" not in document.inputs
    assert document.name != "issue-to-pr"
    for node in document.nodes:
        if isinstance(node, ShellNode):
            assert list(node.command[:2]) != ["hub", "step"], node.id
    assert document.returns == "report"
    assert document.outcome_field == "verdict"
