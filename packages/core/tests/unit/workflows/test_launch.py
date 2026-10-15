"""Starting, cancelling, resuming and abandoning runs from hub web (AC-213.19)."""

from collections.abc import Iterable, Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.readmodels.filters import RunFilter
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.runs.workflow_run import IssueRef, WorkflowRun
from agent_hub.core.testing.read_model_builders import a_run
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.launch import (
    RUN_ID_PATTERN,
    ControlWorkflowRun,
    LaunchSpec,
    RunConflictError,
    RunInputError,
    StartRunRequest,
    StartWorkflowRun,
    new_run_id,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

FIX = {
    "version": 1,
    "name": "fix",
    "revision": 1,
    "inputs": {
        "issue": {"type": "string", "required": True},
        "tries": {"type": "integer", "default": 2},
        "strict": {"type": "boolean"},
    },
    "nodes": [{"id": "work", "type": "shell", "command": ["make"]}],
}
LINT = {
    "version": 1,
    "name": "lint",
    "revision": 1,
    "nodes": [{"id": "lint", "type": "shell", "command": ["make", "lint"]}],
}


class Plans:
    def __init__(self) -> None:
        self.plans = {name: plan_workflow(parse_workflow(doc)) for name, doc in _docs().items()}

    def workflow_plan(self, project: str, name: str) -> tuple[str, WorkflowPlan]:
        if project != "demo":
            raise EntityNotFoundError(entity="project", entity_id=project)
        if name not in self.plans:
            raise EntityNotFoundError(entity="workflow", entity_id=f"{project}/{name}")
        return "/hubs/demo", self.plans[name]

    def project_hubs(self) -> Iterable[tuple[str, str]]:
        return [("demo", "/hubs/demo")]


def _docs() -> dict[str, Any]:
    return {"fix": FIX, "lint": LINT}


class Runs:
    def __init__(self, *runs: WorkflowRun) -> None:
        self.runs = runs
        self.filters: list[RunFilter] = []

    def list_runs(self, run_filter: RunFilter) -> Page[WorkflowRun]:
        self.filters.append(run_filter)
        items = tuple(
            run for run in self.runs if run.issue is not None and run.issue.key == run_filter.issue
        )
        return Page(items=items, next_cursor=None, total_estimate=len(items))

    def get_run(self, run_id: str) -> WorkflowRun:
        found = next((run for run in self.runs if run.id == run_id), None)
        if found is None:
            raise EntityNotFoundError(entity="run", entity_id=run_id)
        return found


class Launcher:
    def __init__(self, live: Mapping[str, str | None] | None = None) -> None:
        self.live = dict(live or {})
        self.calls: list[tuple[str, Any]] = []
        self.cancels = True

    def start(self, spec: LaunchSpec) -> None:
        self.calls.append(("start", spec))
        self.live[spec.run_id] = spec.issue

    def resume(self, hub_path: str, run_id: str) -> None:
        self.calls.append(("resume", (hub_path, run_id)))

    def abandon(self, hub_path: str, run_id: str) -> None:
        self.calls.append(("abandon", (hub_path, run_id)))

    def cancel(self, hub_path: str, run_id: str) -> bool:
        self.calls.append(("cancel", (hub_path, run_id)))
        return self.cancels

    def live_runs(self, hub_path: str) -> Mapping[str, str | None]:
        return self.live


def start(runs: Runs, launcher: Launcher, **body: Any) -> Any:
    ids = iter(["run-1", "run-2"])
    use_case = StartWorkflowRun(Plans(), runs, launcher, mint=lambda: next(ids))  # type: ignore[arg-type]
    return use_case(StartRunRequest.model_validate({"project": "demo", **body}))


def engine_run(**overrides: object) -> WorkflowRun:
    return a_run(id="run-9", workflow="fix", content_hash="sha256:abc", **overrides)


def test_launches_with_minted_id_and_issue_when_inputs_fit() -> None:
    launcher = Launcher()

    accepted = start(Runs(), launcher, workflow="fix", inputs={"issue": "DEM-7"}, live=True)

    assert accepted.run_id == "run-1"
    assert accepted.action == "start"
    assert launcher.calls == [
        (
            "start",
            LaunchSpec(
                run_id="run-1",
                project="demo",
                hub_path="/hubs/demo",
                workflow="fix",
                inputs={"issue": "DEM-7"},
                live=True,
                issue="DEM-7",
            ),
        )
    ]


def test_launches_without_issue_when_workflow_declares_none() -> None:
    launcher = Launcher()
    runs = Runs()

    start(runs, launcher, workflow="lint")

    assert launcher.calls[0][1].issue is None
    assert runs.filters == []


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({}, 'the input "issue" is required'),
        ({"issue": "DEM-7", "other": 1}, 'no input is named "other"'),
        ({"issue": "DEM-7", "tries": "two"}, 'the input "tries" must be of type integer'),
        ({"issue": "DEM-7", "tries": True}, 'the input "tries" must be of type integer'),
        ({"issue": 7}, 'the input "issue" must be of type string'),
    ],
)
def test_refuses_inputs_when_they_do_not_fit_workflow(inputs: dict[str, Any], message: str) -> None:
    launcher = Launcher()

    with pytest.raises(RunInputError, match=message):
        start(Runs(), launcher, workflow="fix", inputs=inputs)
    assert launcher.calls == []


@pytest.mark.parametrize(
    "inputs",
    [{"issue": "a\x00b"}, {"issue": "x" * 16_385}, {"Bad-Name": "x"}, {"n": float("nan")}],
)
def test_refuses_request_when_input_cannot_travel_as_argv(inputs: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StartRunRequest.model_validate({"project": "demo", "workflow": "fix", "inputs": inputs})


def test_refuses_second_run_when_issue_has_folded_live_run() -> None:
    launcher = Launcher()
    runs = Runs(engine_run(issue=IssueRef(key="DEM-7")))

    with pytest.raises(RunConflictError) as caught:
        start(runs, launcher, workflow="fix", inputs={"issue": "DEM-7"})

    assert (caught.value.code, caught.value.run_id) == ("live_run", "run-9")
    assert runs.filters[0].issue == "DEM-7"
    assert launcher.calls == []


def test_refuses_second_run_when_launched_child_has_no_event_yet() -> None:
    launcher = Launcher()
    start(Runs(), launcher, workflow="fix", inputs={"issue": "DEM-7"})

    with pytest.raises(RunConflictError, match=r"live run \(run-1\)"):
        start(Runs(), launcher, workflow="fix", inputs={"issue": "DEM-7"})


def test_launches_when_issue_runs_all_ended() -> None:
    launcher = Launcher()
    runs = Runs(engine_run(issue=IssueRef(key="DEM-7"), status="failed"))

    start(runs, launcher, workflow="fix", inputs={"issue": "DEM-7"})

    assert [call for call, _ in launcher.calls] == ["start"]


def test_refuses_issue_to_pr_when_started_from_web() -> None:
    launcher = Launcher()

    with pytest.raises(RunConflictError) as caught:
        start(Runs(), launcher, workflow="issue-to-pr", inputs={"issue": "DEM-7"})

    assert caught.value.code == "tracker_workflow"
    assert launcher.calls == []


def test_mints_ids_in_cli_pattern_when_none_given() -> None:
    assert RUN_ID_PATTERN.fullmatch(new_run_id())


def control(launcher: Launcher, *runs: WorkflowRun) -> ControlWorkflowRun:
    return ControlWorkflowRun(Plans(), Runs(*runs), launcher)  # type: ignore[arg-type]


@pytest.mark.parametrize("action", ["resume", "abandon"])
def test_calls_launcher_when_run_is_idle(action: str) -> None:
    launcher = Launcher()

    accepted = getattr(control(launcher, engine_run(status="failed")), action)("run-9")

    assert (accepted.action, accepted.project) == (action, "demo")
    assert launcher.calls == [(action, ("/hubs/demo", "run-9"))]


@pytest.mark.parametrize(
    "case",
    [
        (engine_run(status="done"), {}, "ended"),
        (engine_run(status="cancelled"), {}, "ended"),
        (engine_run(), {"run-9": None}, "in_use"),
        (a_run(id="run-9"), {}, "not_engine_run"),
    ],
)
@pytest.mark.parametrize("action", ["resume", "abandon"])
def test_refuses_command_when_run_is_not_idle(
    action: str, case: tuple[WorkflowRun, dict[str, str | None], str]
) -> None:
    run, live, code = case
    launcher = Launcher(live)

    with pytest.raises(RunConflictError) as caught:
        getattr(control(launcher, run), action)("run-9")

    assert caught.value.code == code
    assert launcher.calls == []


def test_cancels_when_launcher_holds_live_child() -> None:
    launcher = Launcher()

    accepted = control(launcher, engine_run()).cancel("run-9")

    assert accepted.action == "cancel"
    assert launcher.calls == [("cancel", ("/hubs/demo", "run-9"))]


def test_refuses_cancel_when_no_child_of_ours_runs_it() -> None:
    launcher = Launcher()
    launcher.cancels = False

    with pytest.raises(RunConflictError) as caught:
        control(launcher, engine_run()).cancel("run-9")

    assert caught.value.code == "not_running"


def test_answers_not_found_when_run_or_its_hub_unknown() -> None:
    with pytest.raises(EntityNotFoundError):
        control(Launcher()).cancel("run-9")
    with pytest.raises(EntityNotFoundError, match="project"):
        control(Launcher(), engine_run(project="gone")).resume("run-9")
