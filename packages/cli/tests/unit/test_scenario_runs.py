"""A scenario run's owed re-asks (AGH-358, R2-1): what a resume asks again, read from the record
by line order, never from attempt numbers."""

import json
from collections.abc import Mapping
from pathlib import Path

import agent_hub.cli.scenario_runs as scenario_runs
from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.access_policy import Effect
from agent_hub.core.workflows.document import WorkflowDocument, parse_workflow
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

type Record = dict[str, JsonValue]

SEND: dict[str, object] = {"id": "send", "type": "action", "action": "send-order"}
LOOP: dict[str, object] = {
    "id": "g",
    "type": "loop_group",
    "max_iterations": 2,
    "until_when": "$send.output.order == 'done'",
    "nodes": [SEND],
}
WRITE = ("demo/send-order", "write")


def a_scenario(*nodes: Mapping[str, object], name: str = "walk") -> WorkflowDocument:
    document = {"version": 1, "kind": "scenario", "name": name, "revision": 1}
    return parse_workflow({**document, "nodes": list(nodes)})


def started(node: str) -> Record:
    return {"event": "action_start", "node": node, "attempt": 1, "poll": 0, "effect": "write"}


def owed_line(node: str) -> Record:
    return {"event": "reask_owed", "node": node}


def gate(node: str) -> Record:
    return {"event": "gate", "node": node, "attempt": 1, "form": "decision"}


def ended(node: str) -> Record:
    return {"event": "step_end", "node": node, "attempt": 1, "status": "ok"}


def owe(
    tmp_path: Path,
    plan: WorkflowPlan,
    records: list[Record],
    *,
    effects: Mapping[str, tuple[str, Effect]],
) -> tuple[set[str], frozenset[str], list[str]]:
    """The owed steps, the reopened gates, and the nodes of the ``reask_owed`` lines written."""
    owed = scenario_runs._owed(
        tmp_path, [{"event": "start"}, *records], plan=plan, effects=effects, environment="local"
    )
    path = tmp_path / "records.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    assert all(step.again for step in owed.steps.values())
    return set(owed.steps), owed.reopen, [line["node"] for line in lines]


def test_keeps_step_owed_when_crash_before_reask_gate(tmp_path: Path) -> None:
    plan = plan_workflow(a_scenario(SEND))
    records = [started("send"), owed_line("send")]

    steps, reopen, written = owe(tmp_path, plan, records, effects={"send": WRITE})

    assert (steps, reopen, written) == ({"send"}, frozenset({"send__ask"}), [])


def test_reuses_approval_when_crash_before_reapproved_step_starts(tmp_path: Path) -> None:
    plan = plan_workflow(a_scenario(SEND))
    records = [started("send"), owed_line("send"), gate("send__ask"), ended("send__ask")]

    steps, reopen, written = owe(tmp_path, plan, records, effects={"send": WRITE})

    assert (steps, reopen, written) == ({"send"}, frozenset(), [])


def test_owes_again_when_crash_after_reapproved_step_starts(tmp_path: Path) -> None:
    plan = plan_workflow(a_scenario(SEND))
    records = [
        started("send"),
        owed_line("send"),
        gate("send__ask"),
        ended("send__ask"),
        started("send"),
    ]

    steps, reopen, written = owe(tmp_path, plan, records, effects={"send": WRITE})

    assert (steps, reopen, written) == ({"send"}, frozenset({"send__ask"}), ["send"])


def test_owes_nothing_when_step_ended_after_its_write(tmp_path: Path) -> None:
    plan = plan_workflow(a_scenario(SEND))
    records = [started("send"), owed_line("send"), started("send"), ended("send")]

    assert owe(tmp_path, plan, records, effects={"send": WRITE}) == (set(), frozenset(), [])


def test_owes_nothing_when_held_group_is_clean_point(tmp_path: Path) -> None:
    plan = plan_workflow(a_scenario(LOOP))
    held: Record = {"event": "held", "groups": {"g": {"attempt": 1, "iteration": 1}}}

    clean = owe(tmp_path, plan, [started("g__send"), held], effects={"g__send": WRITE})
    (tmp_path / "x").mkdir()
    crashed = owe(tmp_path / "x", plan, [started("g__send")], effects={"g__send": WRITE})

    assert clean == (set(), frozenset(), [])
    assert crashed == ({"g__send"}, frozenset(), ["g"])


def test_owes_only_crashed_group_when_two_groups_one_included(tmp_path: Path) -> None:
    other = {**LOOP, "id": "h"}
    document = a_scenario({"id": "blk", "type": "include", "include": "block"}, other)
    block = a_scenario(LOOP, name="block")
    plan = plan_workflow(document, includes=lambda name: block if name == "block" else None)
    effects = {"blk__g__send": WRITE, "h__send": WRITE}

    steps, reopen, written = owe(tmp_path, plan, [started("blk__g__send")], effects=effects)

    assert (steps, reopen, written) == ({"blk__g__send"}, frozenset(), ["blk__g"])
