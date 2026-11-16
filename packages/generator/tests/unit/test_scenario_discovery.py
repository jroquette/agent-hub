"""Scenario discovery: ``scenarios/<pack>/`` read as workflows are, and each root refusing the
other kind (AC-350.13; docs/design/scenarios.md § Contract).

TESTING.md: synthetic trees only, written under ``tmp_path``.
"""

from pathlib import Path

import pytest

from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile, check_workflows
from agent_hub.generator.scenario_discovery import DiscoveredScenarioSource, discover_scenarios
from agent_hub.generator.workflow_discovery import discover_workflows

_SCENARIO = """\
version: 1
kind: scenario
name: {name}
revision: 1
nodes:
  - id: read-order
    type: action
    action: get-order
"""
_WORKFLOW = (
    "version: 1\nname: {name}\nrevision: 1\nnodes:\n  - id: a\n    type: shell\n    command: [x]\n"
)


def _write(root: Path, pack: str, name: str, *, text: str) -> Path:
    (root / pack).mkdir(parents=True, exist_ok=True)
    path = root / pack / f"{name}.yaml"
    path.write_text(text.replace("{name}", name))
    return path


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    (tmp_path / "hub").mkdir()
    return tmp_path / "hub"


def test_lists_scenarios_when_packs_hold_scenario_kind(hub: Path, tmp_path: Path) -> None:
    walk = _write(hub / "scenarios", "orders", "order-walk", text=_SCENARIO)
    _write(hub / "scenarios", "billing", "invoice-walk", text=_SCENARIO)
    _write(hub / "workflows", "delivery", "ship", text=_WORKFLOW)

    found = discover_scenarios(hub)

    assert found.problems == ()
    assert [(item.name, item.pack, item.origin) for item in found.workflows] == [
        ("invoice-walk", "billing", "hub"),
        ("order-walk", "orders", "hub"),
    ]
    assert found.workflows[1].path == walk
    assert found.workflows[1].pack_root == hub / "scenarios" / "orders"
    source = DiscoveredScenarioSource(hub)
    catalog = check_workflows(source)
    assert [plan.document.name for plan in catalog.plans] == ["invoice-walk", "order-walk"]
    assert source.found["order-walk"].pack == "orders"
    # The workflows the hub has are none of the scenarios, nor the reverse.
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    assert [item.name for item in discover_workflows(hub, builtin_root=builtin).workflows] == [
        "ship"
    ]


def test_refuses_document_when_kind_differs_from_root(hub: Path, tmp_path: Path) -> None:
    _write(hub / "scenarios", "orders", "plain", text=_WORKFLOW)
    _write(hub / "workflows", "delivery", "walk", text=_SCENARIO)
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    scenarios = discover_scenarios(hub)
    workflows = discover_workflows(hub, builtin_root=builtin)

    assert scenarios.workflows == ()
    [problem] = scenarios.problems
    assert (problem.path.name, problem.line) == ("plain.yaml", None)
    assert problem.reason == "a document in scenarios/ must declare kind: scenario"
    assert workflows.workflows == ()
    [problem] = workflows.problems
    assert (problem.path.name, problem.line) == ("walk.yaml", 2)
    assert problem.reason == "kind: scenario belongs in scenarios/<pack>/, not workflows/"
    items: list[WorkflowFile | LoadProblem] = list(DiscoveredScenarioSource(hub).workflow_files())
    assert items == [
        LoadProblem(
            "scenarios/orders/plain.yaml",
            None,
            "$",
            "a document in scenarios/ must declare kind: scenario",
        )
    ]
