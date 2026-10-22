"""The built-in ``doc-drift`` pack (AGH-491): the workflow loads and plans, its fixtures pass, the
judge is read-only and fresh, nothing writes the tracker (ADR 0030), and every branch, commit,
push and PR comes after the owner's approval.
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

PACK = BUILTIN_WORKFLOWS / "doc-drift"
FIXTURES = ("drift-adr-only", "drift-declined", "drift-none", "drift-renamed-command")


def nodes_of(name: str) -> dict[str, Any]:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == name]
    document = parse_workflow(workflow.document)
    return {node.id: node for node in document.nodes}


def document_of(name: str) -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == name]
    return parse_workflow(workflow.document)


def test_validates_and_passes_every_fixture_when_doc_drift_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "doc-drift")
    tested = run_command(demo_workspace.hub, "workflow", "test", "doc-drift")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "doc-drift: valid (9 nodes in 9 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/doc-drift/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning:" not in tested.stdout
    assert tested.stdout.endswith("4 fixtures: 4 passed, 0 failed\n")


def test_declares_read_only_judge_and_no_tracker_step_when_document_loaded() -> None:
    document = document_of("doc-drift")
    nodes = nodes_of("doc-drift")
    judge = nodes["judge"]
    shells = [node.command for node in nodes.values() if node.type == "shell"]

    assert set(document.inputs) == {"repo", "sha"}
    assert (judge.context, judge.mutates_checkout) == ("fresh", False)
    assert (judge.retry.max_attempts, judge.timeout) == (0, "30m")
    for name in ("contract", "mentions", "plan"):
        assert nodes[name].mutates_checkout is False, name
    assert [list(command[:3]) for command in shells] == [
        ["hub", "step", "commits"],
        ["hub", "step", "pr"],
    ]
    assert list(shells[1][3:5]) == ["--issue", "doc-drift"]
    assert (document.returns, document.outcome_field) == ("plan", "verdict")
    assert nodes["approve"].capture_response is True
    assert document.name != "issue-to-pr"


def test_puts_the_pr_behind_the_approval_when_doc_drift_loaded() -> None:
    nodes = nodes_of("doc-drift")

    def upstream(node_id: str) -> set[str]:
        found: set[str] = set()
        pending = list(nodes[node_id].depends_on)
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(nodes[current].depends_on)
        return found

    for node_id in ("branch", "apply", "commits", "pr"):
        assert "approve" in upstream(node_id), node_id
    assert nodes["branch"].when == "$approve.output.decision == 'approve'"
