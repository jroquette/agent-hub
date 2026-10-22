"""``workflows.starts`` (AGH-481, AC-4): a schedule or event names a workflow hub web can start."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.doctor.workflow_starts_rule import WORKFLOWS_STARTS
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, str, str]

UNKNOWN_FIX = "name a workflow that hub workflow list shows, or add it under workflows/"
TRACKER_FIX = "start issue-to-pr with hub run, or remove this entry"


class ListSource:
    def __init__(self, *items: WorkflowFile | LoadProblem) -> None:
        self.items = items

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return self.items


def a_file(name: str) -> WorkflowFile:
    first = {"id": "a", "type": "shell", "command": ["true"]}
    content = {"version": 1, "name": name, "revision": 1, "nodes": [first]}
    return WorkflowFile(f"workflows/demo/{name}.yaml", name, content, {(): 1})


def a_config(**starts: list[dict[str, Any]]) -> HubConfig:
    document = a_hub_document()
    document.update(starts)
    return HubConfig.model_validate(document)


def a_snapshot(snapshot_of: SnapshotFactory, config: HubConfig, *names: str) -> DoctorSnapshot:
    source = ListSource(*(a_file(name) for name in names))
    return replace(snapshot_of(config=config), workflows=source)


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(WORKFLOWS_STARTS.check(snapshot))
    assert all(finding.rule == "workflows.starts" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    return [(finding.path, finding.message, finding.fix) for finding in found]


def test_declares_schedule_rule_when_module_loaded() -> None:
    assert WORKFLOWS_STARTS.id == "workflows.starts"
    assert WORKFLOWS_STARTS.id in RULE_IDS
    assert WORKFLOWS_STARTS.module is None
    assert WORKFLOWS_STARTS.reads == frozenset({Read.WORKFLOWS})


def test_reports_schedule_naming_unknown_workflow_when_doctor_runs(
    snapshot_of: SnapshotFactory,
) -> None:
    config = a_config(
        schedules=[
            {"workflow": "retro", "cron": "0 9 * * 1"},
            {"workflow": "nope", "cron": "0 9 * * 1"},
        ]
    )

    assert findings_of(a_snapshot(snapshot_of, config, "retro")) == [
        ("hub.json", "schedules[1].workflow: unknown workflow nope", UNKNOWN_FIX)
    ]


def test_reports_event_schedule_naming_unknown_workflow_when_doctor_runs(
    snapshot_of: SnapshotFactory,
) -> None:
    config = a_config(events=[{"workflow": "verify", "on": "merge", "repo": "demo-api"}])

    assert findings_of(a_snapshot(snapshot_of, config, "retro")) == [
        ("hub.json", "events[0].workflow: unknown workflow verify", UNKNOWN_FIX)
    ]


def test_reports_schedule_naming_issue_to_pr_when_doctor_runs(
    snapshot_of: SnapshotFactory,
) -> None:
    config = a_config(
        schedules=[{"workflow": "issue-to-pr", "cron": "0 9 * * 1"}],
        events=[{"workflow": "issue-to-pr", "on": "pr_opened", "repo": "demo-api"}],
    )
    message = "{}[0].workflow: issue-to-pr writes to the tracker and cannot start from hub web"

    assert findings_of(a_snapshot(snapshot_of, config, "issue-to-pr")) == [
        ("hub.json", message.format("schedules"), TRACKER_FIX),
        ("hub.json", message.format("events"), TRACKER_FIX),
    ]


def test_reports_nothing_when_every_schedule_names_a_known_workflow(
    snapshot_of: SnapshotFactory,
) -> None:
    config = a_config(
        schedules=[{"workflow": "retro", "cron": "0 9 * * 1"}],
        events=[{"workflow": "verify", "on": "ci_red", "repo": "demo-api"}],
    )

    assert findings_of(a_snapshot(snapshot_of, config, "retro", "verify")) == []


def test_reports_nothing_when_no_schedule_source_was_read(snapshot_of: SnapshotFactory) -> None:
    config = a_config(schedules=[{"workflow": "nope", "cron": "0 9 * * 1"}])

    assert findings_of(snapshot_of(config=config)) == []
