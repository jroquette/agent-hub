"""``scenarios.graph_format``: a warning per scenario still in the graph format (version 1)."""

from collections.abc import Callable, Iterable
from dataclasses import replace

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.graph_format_rule import SCENARIOS_GRAPH_FORMAT
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str, str]

MESSAGE = "scenario {name} is in the graph format (version 1), which a later release removes"
FIX = "run hub scenario migrate {name} to write it as blocks (version 2)"


class ListSource:
    def __init__(self, *items: WorkflowFile | LoadProblem) -> None:
        self.items = items

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return self.items


def a_graph(name: str, *, version: object = 1) -> WorkflowFile:
    node = {"id": "send", "type": "action", "action": "queue-send"}
    content = {"version": version, "kind": "scenario", "name": name, "revision": 1}
    content["nodes"] = [node]
    lines = {(): 1, ("version",): 1, ("nodes",): 5}
    return WorkflowFile(f"scenarios/shop/{name}.yaml", name, content, lines)


def a_tree(name: str) -> WorkflowFile:
    stage = {"name": "Fetch order", "steps": [{"do": "queue-send"}]}
    content = {"version": 2, "kind": "scenario", "name": name, "revision": 1, "stages": [stage]}
    return WorkflowFile(f"scenarios/shop/{name}.yaml", name, content, {(): 1, ("version",): 1})


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(SCENARIOS_GRAPH_FORMAT.check(snapshot))
    assert all(finding.rule == "scenarios.graph_format" for finding in found)
    assert all(finding.severity is Severity.WARNING for finding in found)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in found]


def with_source(snapshot_of: SnapshotFactory, *items: WorkflowFile | LoadProblem) -> DoctorSnapshot:
    return replace(snapshot_of(), scenarios=ListSource(*items))


def shown(name: str) -> Shown:
    return (
        f"scenarios/shop/{name}.yaml",
        1,
        MESSAGE.format(name=name),
        FIX.format(name=name),
    )


def test_declares_graph_format_rule_when_module_loaded() -> None:
    assert SCENARIOS_GRAPH_FORMAT.id == "scenarios.graph_format"
    assert SCENARIOS_GRAPH_FORMAT.id in RULE_IDS
    assert SCENARIOS_GRAPH_FORMAT.module is None
    assert SCENARIOS_GRAPH_FORMAT.severity is Severity.WARNING
    assert SCENARIOS_GRAPH_FORMAT.reads == frozenset({Read.SCENARIOS})
    assert SCENARIOS_GRAPH_FORMAT.summary == (
        "each scenario still in the graph format (version 1), with its migrate command"
    )


def test_warns_for_each_graph_scenario_when_graph_format_runs(snapshot_of: SnapshotFactory) -> None:
    snapshot = with_source(
        snapshot_of, a_graph("demo-order-roundtrip"), a_tree("checkout"), a_graph("refund")
    )

    assert findings_of(snapshot) == [shown("demo-order-roundtrip"), shown("refund")]


def test_reports_nothing_for_graph_format_when_every_scenario_is_a_tree(
    snapshot_of: SnapshotFactory,
) -> None:
    snapshot = with_source(snapshot_of, a_tree("checkout"), a_tree("refund"))

    assert findings_of(snapshot) == []


def test_reports_nothing_for_graph_format_when_no_scenario_was_read(
    snapshot_of: SnapshotFactory,
) -> None:
    assert snapshot_of().scenarios is None

    assert findings_of(snapshot_of()) == []


def test_skips_graph_format_when_a_file_was_refused_or_has_no_known_version(
    snapshot_of: SnapshotFactory,
) -> None:
    refused = LoadProblem("scenarios/shop/bad.yaml", 3, "$", "duplicate key 'name'")

    snapshot = with_source(
        snapshot_of, refused, a_graph("odd", version=3), a_graph("flag", version=True)
    )

    assert findings_of(snapshot) == []
