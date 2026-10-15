"""``workflows.valid`` (AGH-227, AC-213.16): every workflow the hub has loads and plans."""

from collections.abc import Callable, Iterable
from dataclasses import replace

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.doctor.workflows_rule import WORKFLOWS_VALID
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str, str]

FIX = "fix the workflow file; hub workflow validate lists each problem"


class ListSource:
    def __init__(self, *items: WorkflowFile | LoadProblem) -> None:
        self.items = items

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return self.items


def a_file(name: str, *, stem: str | None = None, **node: object) -> WorkflowFile:
    stem = stem or name
    first = {"id": "a", "type": "shell", "command": ["true"]} | node
    content = {"version": 1, "name": name, "revision": 1, "nodes": [first]}
    lines = {(): 1, ("nodes",): 4, ("nodes", 0): 5}
    return WorkflowFile(f"workflows/demo/{stem}.yaml", stem, content, lines)


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(WORKFLOWS_VALID.check(snapshot))
    assert all(finding.rule == "workflows.valid" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in found]


def with_source(snapshot_of: SnapshotFactory, *items: WorkflowFile | LoadProblem) -> DoctorSnapshot:
    return replace(snapshot_of(), workflows=ListSource(*items))


def test_declares_rule_when_module_loaded() -> None:
    assert WORKFLOWS_VALID.id == "workflows.valid"
    assert WORKFLOWS_VALID.id in RULE_IDS
    assert WORKFLOWS_VALID.module is None
    assert WORKFLOWS_VALID.severity is Severity.ERROR
    assert WORKFLOWS_VALID.reads == frozenset({Read.WORKFLOWS})
    assert WORKFLOWS_VALID.summary == "every workflow of the hub and the built-ins loads and plans"


def test_reports_nothing_when_every_workflow_loads(snapshot_of: SnapshotFactory) -> None:
    snapshot = with_source(snapshot_of, a_file("lint"), a_file("test"))

    assert findings_of(snapshot) == []


def test_reports_nothing_when_no_source_was_read(snapshot_of: SnapshotFactory) -> None:
    assert snapshot_of().workflows is None

    assert findings_of(snapshot_of()) == []


def test_reports_problem_at_file_and_line_when_a_key_is_unknown(
    snapshot_of: SnapshotFactory,
) -> None:
    snapshot = with_source(snapshot_of, a_file("lint", promt="x"), a_file("test"))

    assert findings_of(snapshot) == [
        ("workflows/demo/lint.yaml", 5, "nodes[0].promt: unknown key", FIX)
    ]


def test_reports_refused_file_when_the_loader_could_not_read_it(
    snapshot_of: SnapshotFactory,
) -> None:
    refused = LoadProblem("workflows/demo/bad.yaml", 3, "$", "duplicate key 'name'")

    snapshot = with_source(snapshot_of, refused, a_file("lint"))

    assert findings_of(snapshot) == [("workflows/demo/bad.yaml", 3, "$: duplicate key 'name'", FIX)]


def test_reports_each_problem_when_several_files_fail(snapshot_of: SnapshotFactory) -> None:
    snapshot = with_source(
        snapshot_of, a_file("lint", stem="check"), a_file("test", depends_on=["ghost"])
    )

    assert findings_of(snapshot) == [
        ("workflows/demo/check.yaml", 1, "name: must be the file's stem 'check'", FIX),
        (
            "workflows/demo/test.yaml",
            5,
            'nodes[0].depends_on[0]: no node has the id "ghost"',
            FIX,
        ),
    ]
