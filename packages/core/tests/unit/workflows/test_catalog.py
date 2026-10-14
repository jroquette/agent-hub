"""The catalog: every file loaded and planned, each problem with its file, line and key."""

from collections.abc import Iterable

from agent_hub.core.workflows.catalog import (
    LoadProblem,
    WorkflowFile,
    check_workflows,
)


class ListSource:
    def __init__(self, *items: WorkflowFile | LoadProblem) -> None:
        self.items = items

    def workflow_files(self) -> Iterable[WorkflowFile | LoadProblem]:
        return self.items


def content(name: str, **node: object) -> dict[str, object]:
    first = {"id": "a", "type": "shell", "command": ["true"]} | node
    return {"version": 1, "name": name, "revision": 1, "nodes": [first]}


def a_file(name: str, stem: str | None = None, **node: object) -> WorkflowFile:
    stem = stem or name
    return WorkflowFile(f"workflows/demo/{stem}.yaml", stem, content(name, **node))


def test_plans_each_workflow_when_every_file_loads() -> None:
    catalog = check_workflows(ListSource(a_file("lint"), a_file("test")))

    assert [plan.document.name for plan in catalog.plans] == ["lint", "test"]
    assert catalog.problems == ()


def test_places_problem_on_the_line_of_its_key_when_loader_recorded_lines() -> None:
    lines = {(): 1, ("nodes",): 4, ("nodes", 0): 5, ("nodes", 0, "promt"): 8}
    item = WorkflowFile("w/demo/lint.yaml", "lint", content("lint", promt="x"), lines)

    [problem] = check_workflows(ListSource(item)).problems

    assert problem == LoadProblem("w/demo/lint.yaml", 8, "nodes[0].promt", "unknown key")


def test_places_problem_on_the_nearest_key_when_its_own_key_is_missing() -> None:
    item = WorkflowFile("lint.yaml", "lint", content("lint", command=[]), {("nodes", 0): 5})

    [problem] = check_workflows(ListSource(item)).problems

    assert (problem.line, problem.key) == (5, "nodes[0].command")


def test_leaves_the_line_unknown_when_loader_recorded_none() -> None:
    [problem] = check_workflows(ListSource(a_file("lint", depends_on=["ghost"]))).problems

    assert problem == LoadProblem(
        "workflows/demo/lint.yaml", None, "nodes[0].depends_on[0]", "no node has the id 'ghost'"
    )


def test_keeps_loading_the_others_when_a_file_is_refused() -> None:
    refused = LoadProblem("w/demo/bad.yaml", 3, "$", "duplicate key 'name'")

    catalog = check_workflows(ListSource(refused, a_file("lint")))

    assert [plan.document.name for plan in catalog.plans] == ["lint"]
    assert catalog.problems == (refused,)


def test_refuses_the_name_when_it_is_not_the_file_stem() -> None:
    [problem] = check_workflows(ListSource(a_file("lint", stem="check"))).problems

    assert (problem.key, problem.message) == ("name", "must be the file's stem 'check'")


def test_keeps_the_first_when_two_files_share_a_name() -> None:
    first = a_file("lint")
    second = WorkflowFile("workflows/other/lint.yaml", "lint", content("lint"))

    catalog = check_workflows(ListSource(first, second))

    assert len(catalog.plans) == 1
    assert catalog.problems[0].file == "workflows/other/lint.yaml"
    assert "already defined in workflows/demo/lint.yaml" in catalog.problems[0].message
