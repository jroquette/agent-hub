"""Fixtures: a dry run and what it must show (status, outcome, failed and reached sets;
AC-213.11)."""

from typing import Any

import pytest

import agent_hub.core.workflows.dry_run as dry_run_module
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
        (fixture(expect={"status": "running"}), "expect.status"),
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


GATED = a_plan(
    {"id": "build", "type": "shell", "command": ["make"]},
    {"id": "ok", "type": "approval", "message": "Ship?", "depends_on": ["build"]},
    {"id": "nap", "type": "wait", "duration": "1h", "depends_on": ["ok"]},
)


def test_passes_when_a_gate_without_a_stub_pauses_the_run_as_expected() -> None:
    content = {
        "workflow": "demo",
        "stubs": {"build": {"text": "ok"}},
        "expect": {"status": "paused"},
        "reached": ["build", "ok"],
    }

    assert check(content, GATED).problems == ()


def test_answers_each_gate_when_a_skeleton_is_asked_for_a_gated_plan() -> None:
    skeleton = skeleton_fixture(GATED, outputs=KeysOutputs())

    assert skeleton["stubs"] == {
        "build": {"text": "TODO"},
        "ok": {"decision": "approve"},
        "nap": {},
    }
    assert skeleton["expect"] == {"status": "done", "outcome": None}
    assert check(skeleton, GATED).problems == ()


def test_stubs_each_body_node_by_its_recorded_id_when_the_skeleton_has_a_group() -> None:
    group = {
        "id": "g",
        "type": "loop_group",
        "max_iterations": 2,
        "until_when": "$b.output == 'TODO'",
        "nodes": [{"id": "b", "type": "shell", "command": ["true"]}],
    }

    skeleton = skeleton_fixture(a_plan(group), outputs=KeysOutputs())

    assert skeleton["stubs"] == {"g__b": {"text": "TODO"}}
    assert skeleton["reached"] == ["g", "g__b"]
    assert run_fixture(a_plan(group), parse_fixture(skeleton), outputs=KeysOutputs()).passed


SCENARIO = a_plan(
    {"id": "send", "type": "action", "action": "send-queue-message"},
    {
        "id": "wait",
        "type": "expect",
        "action": "get-order",
        "depends_on": ["send"],
        "every": "10s",
        "timeout": "1m",
        "until_when": "$self.output.status == 'ON_HOLD'",
        "capture": {"order_id": "$self.output.order_id"},
    },
    {"id": "use", "type": "action", "action": "x", "depends_on": ["wait"]}
    | {"with": {"id": "$CTX.order_id"}},
    kind="scenario",
)
HELD = {"output": {"status": "ON_HOLD", "order_id": "o-7"}}
PENDING = {"output": {"status": "PENDING"}}


@pytest.mark.parametrize(
    ("polls", "shown"),
    [
        ([PENDING, HELD], {"expect": {"status": "done"}, "reached": ["send", "wait", "use"]}),
        (
            PENDING,
            {"expect": {"status": "failed"}, "failed": ["wait"], "reached": ["send", "wait"]},
        ),
    ],
    ids=["holds", "times-out"],
)
def test_gives_same_path_when_scenario_fixture_deterministic(
    polls: Any, shown: dict[str, Any]
) -> None:
    stubs = {"send": {"output": {"message_id": "m-1"}}, "wait": polls, "use": {"output": {}}}
    scenario_fixture = parse_fixture({"workflow": "demo", "stubs": stubs} | shown)

    runs = [
        dry_run_module.dry_run(SCENARIO, {}, scenario_fixture.stubs, outputs=KeysOutputs())
        for _ in range(3)
    ]

    assert run_fixture(SCENARIO, scenario_fixture, outputs=KeysOutputs()).passed
    assert len({(r.reached, r.run.status, r.captures, r.polls) for r in runs}) == 1
    if shown["expect"]["status"] == "done":
        assert (runs[0].captures, runs[0].polls) == ((("wait", "order_id", "o-7"),), 2)
    else:
        # A single stub answers every poll: 0s to 60s, every 10s.
        assert (runs[0].captures, runs[0].polls) == ((), 7)
    skeleton = skeleton_fixture(SCENARIO, outputs=KeysOutputs())
    assert run_fixture(SCENARIO, parse_fixture(skeleton), outputs=KeysOutputs()).passed
