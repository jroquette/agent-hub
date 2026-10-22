"""The built-in ``spike`` pack (AGH-492): the workflow loads and plans, its agents are read-only
and only its ``draft`` step writes, it declares no tracker side (ADR 0030), and its rework loop
is bounded by the same number of rounds ``settle`` counts.
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

PACK = BUILTIN_WORKFLOWS / "spike"
AGENTS = {
    "recall": ("20m", 30, 1.5),
    "research": ("60m", 60, 4.0),
    "choose__options": ("20m", 20, 1.5),
    "premortem": ("20m", 20, 1.5),
}


def document() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "spike"]
    return parse_workflow(workflow.document)


def nodes_of() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    for node in document().nodes:
        nodes[node.id] = node
        for body in getattr(node, "nodes", ()):
            nodes[f"{node.id}__{body.id}"] = body
    return nodes


def test_validates_and_passes_every_fixture_when_spike_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "spike")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "spike: valid (8 nodes in 8 layers)\n"


def test_keeps_agents_read_only_and_writes_only_in_draft_when_document_loaded() -> None:
    nodes = nodes_of()

    for name, (timeout, turns, cost) in AGENTS.items():
        node = nodes[name]
        assert node.type == "agent", name
        assert node.mutates_checkout is False, name
        assert node.timeout == timeout, name
        assert node.retry is not None and node.retry.max_attempts == 0, name
        assert (node.limits.max_turns, node.limits.max_cost_usd) == (turns, cost), name
    agents = {name for name, node in nodes.items() if node.type == "agent"}
    assert agents == set(AGENTS)
    assert not [name for name, node in nodes.items() if node.type == "shell"]
    scripts = {name: node for name, node in nodes.items() if node.type == "script"}
    assert {name: node.script for name, node in scripts.items()} == {
        "setup": "budget.py",
        "t_recall": "budget.py",
        "t_research": "budget.py",
        "choose__t_options": "budget.py",
        "choose__settle": "budget.py",
        "draft": "draft.py",
    }
    # The budget steps compute and print; only draft writes, and only where its slug points.
    assert all(node.cwd is None for node in scripts.values())
    draft = list(scripts["draft"].args)
    assert draft[draft.index("--slug") + 1] == "$setup.output.slug"
    assert all(node.retry is not None and node.retry.max_attempts == 0 for node in scripts.values())


def test_declares_no_tracker_side_when_document_loaded() -> None:
    spike = document()

    assert spike.name == "spike"
    assert set(spike.inputs) == {"question", "timebox", "slug"}
    assert spike.inputs["question"].required is True
    assert spike.inputs["timebox"].default == "2h"
    assert spike.inputs["slug"].default == ""
    assert (spike.returns, spike.outcome_field) == ("draft", "result")
    commands = [node.command for node in nodes_of().values() if hasattr(node, "command")]
    assert not [command for command in commands if list(command[:2]) == ["hub", "step"]]


def test_matches_loop_bound_and_settle_rounds_when_document_loaded() -> None:
    nodes = nodes_of()
    settle = list(nodes["choose__settle"].args)
    pick = nodes["choose__pick"]

    assert nodes["choose"].max_iterations == 3
    assert settle[settle.index("--max-rounds") + 1] == str(nodes["choose"].max_iterations)
    assert nodes["choose"].until_when == "$settle.output.done == true"
    assert [decision.id for decision in pick.decisions] == ["a", "b", "c", "more"]
    assert pick.capture_response is True
    assert nodes["research"].when == "$t_recall.output.over == false"
    assert nodes["choose__options"].when == "$t_research.output.over == false"
    assert nodes["choose__pick"].when == "$t_options.output.over == false"
    assert nodes["premortem"].when == "$choose.output.settle.go == true"
