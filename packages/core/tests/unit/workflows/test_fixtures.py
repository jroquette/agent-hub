"""Fixtures: a dry run and what it must show (status, outcome, failed and reached sets)."""

from typing import Any

import pytest

from agent_hub.core.testing.workflow_fakes import KeysOutputs, a_plan
from agent_hub.core.workflows.document import WorkflowLoadError
from agent_hub.core.workflows.fixtures import (
    FixtureResult,
    parse_fixture,
    run_fixture,
    skeleton_fixture,
)
from agent_hub.core.workflows.plan import WorkflowPlan

REPORT = {
    "type": "object",
    "properties": {"delivery": {"type": "string", "enum": ["delivered", "failed"]}},
    "required": ["delivery"],
}
PLAN = a_plan(
    {"id": "build", "type": "shell", "command": ["make"]},
    {
        "id": "fix",
        "type": "shell",
        "command": ["fix"],
        "depends_on": ["build"],
        "when": "$INPUTS.mode == 'fix'",
    },
    {
        "id": "report",
        "type": "shell",
        "command": ["report"],
        "depends_on": ["build", "fix"],
        "trigger_rule": "all_done",
        "output_format": REPORT,
    },
    inputs={"mode": {"default": "off"}},
    returns="report",
    outcome_field="delivery",
)


def fixture(**keys: Any) -> dict[str, Any]:
    return {
        "workflow": "demo",
        "stubs": {"build": {"text": "ok"}, "report": {"output": {"delivery": "delivered"}}},
        "expect": {"status": "done", "outcome": "delivered"},
        "reached": ["build", "report"],
    } | keys


def check(content: dict[str, Any], plan: WorkflowPlan = PLAN) -> FixtureResult:
    return run_fixture(plan, parse_fixture(content), outputs=KeysOutputs())


def test_passes_when_the_run_matches_every_expectation() -> None:
    result = check(fixture())

    assert (result.passed, result.problems, result.warnings) == (True, (), ())


def test_passes_with_the_failed_set_when_a_stub_fails_a_node() -> None:
    content = fixture(
        stubs={"build": {"fail": "exec_failed"}, "report": {"output": {"delivery": "failed"}}},
        expect={"status": "failed", "outcome": "failed"},
        failed=["build"],
    )

    assert check(content).problems == ()


def test_uses_the_given_inputs_when_the_fixture_has_inputs() -> None:
    content = fixture(inputs={"mode": "fix"}, reached=["build", "fix", "report"])
    content["stubs"]["fix"] = {"text": "fixed"}

    assert check(content).problems == ()


def test_names_each_mismatch_when_the_run_differs_from_the_expectations() -> None:
    content = fixture(
        expect={"status": "failed", "outcome": "failed"},
        failed=["report"],
        reached=["build"],
    )

    assert check(content).problems == (
        "status: expected failed, got done",
        'outcome: expected "failed", got "delivered"',
        'failed: expected ["report"], got []',
        'reached: expected ["build"], got ["build", "report"]',
    )


def test_fails_the_fixture_when_a_reached_node_has_no_stub() -> None:
    content = fixture(stubs={"report": {"output": {"delivery": "failed"}}})
    content |= {"expect": {"status": "failed", "outcome": "failed"}, "failed": ["build"]}

    assert check(content).problems == ('no stub for the reached node "build"',)


def test_tolerates_the_join_without_a_stub_when_its_rule_is_all_done() -> None:
    content = fixture(stubs={"build": {"text": "ok"}}, expect={"status": "done"})

    assert check(content).problems == ()


def test_warns_without_failing_when_a_stub_is_never_used() -> None:
    content = fixture()
    content["stubs"]["fix"] = {"text": "unused"}

    result = check(content)

    assert (result.passed, result.warnings) == (True, ('the stub of "fix" was never used',))


def test_fails_the_fixture_when_a_stub_names_no_node() -> None:
    content = fixture()
    content["stubs"]["ghost"] = {"text": "boo"}

    assert check(content).problems == ('stubs: no node has the id "ghost"',)


def test_fails_the_fixture_when_it_targets_another_workflow() -> None:
    assert check(fixture(workflow="other")).problems == (
        'workflow: the fixture is for "other", not "demo"',
    )


def test_fails_the_fixture_when_the_engine_refuses_the_inputs() -> None:
    assert check(fixture(inputs={"ghost": 1})).problems == (
        'the run did not start: no input is named "ghost"',
    )


@pytest.mark.parametrize(
    ("content", "key"),
    [
        ({"workflow": "demo", "reached": []}, "expect"),
        (fixture(expect={"status": "paused"}), "expect.status"),
        (fixture(stubs={"build": {"text": "a", "fail": "config"}}), "stubs.build"),
        (fixture(stubs={"build": [{"nope": 1}]}), "stubs.build[0].nope"),
        (fixture(extra=1), "extra"),
    ],
)
def test_names_the_key_when_the_fixture_does_not_parse(content: dict[str, Any], key: str) -> None:
    with pytest.raises(WorkflowLoadError) as raised:
        parse_fixture(content)

    assert key in [problem.key for problem in raised.value.problems]


def test_builds_a_passing_fixture_with_a_stub_per_node_when_a_skeleton_is_asked() -> None:
    plan = a_plan(
        {"id": "build", "type": "shell", "command": ["make", "$INPUTS.target"]},
        {
            "id": "stop",
            "type": "halt",
            "reason": "never",
            "depends_on": ["build"],
            "when": "$INPUTS.n > 1",
        },
        inputs={"target": {"required": True}, "n": {"type": "integer", "required": True}},
    )

    skeleton = skeleton_fixture(plan, outputs=KeysOutputs())

    assert skeleton == {
        "workflow": "demo",
        "inputs": {"target": "TODO", "n": 0},
        "stubs": {"build": {"text": "TODO"}},
        "expect": {"status": "done", "outcome": None},
        "failed": [],
        "reached": ["build"],
    }
    assert check(skeleton, plan).problems == ()
