"""A version-2 scenario translated to the node graph, its block map, and its problems put back on
the tree's key paths (AC-507.1, .3, .4, .5; docs/design/scenarios.md § Tree format)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_hub.core.scenarios.policy_gates import PolicyAsk, gated_plan
from agent_hub.core.scenarios.tree_translate import (
    MAX_TREE_NODES,
    block_map,
    complement,
    condition_text,
    translate_tree,
)
from agent_hub.core.workflows.conditions import parse_condition
from agent_hub.core.workflows.document import (
    WorkflowDocument,
    WorkflowLoadError,
    WorkflowProblem,
    parse_workflow,
)
from agent_hub.core.workflows.nodes import (
    ActionNode,
    ApprovalNode,
    ExpectNode,
    IncludeNode,
    LoopGroupNode,
    Node,
    WaitNode,
)
from agent_hub.core.workflows.plan import plan_workflow

BLOCKS = Path(__file__).parents[2] / "data" / "scenarios" / "blocks"
DO = {"do": "queue-send", "with": {"message": "FETCH_ORDERS"}}
WAIT_UNTIL = {
    "wait_until": "order-state",
    "until": "$self.output.order_id != ''",
    "every": "15s",
    "timeout": "10m",
    "capture": {"order_id": "$self.output.order_id", "order_status": "$self.output.status"},
}
YOU = {"you": "Check the order by hand, then approve."}
ON_HOLD = "$CTX.order_status == 'ON_HOLD'"
ASK = PolicyAsk(action="fixture/queue-send", effect="write", environment="staging")


def tree(name: str) -> dict[str, Any]:
    content = yaml.safe_load((BLOCKS / "tree" / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def a_tree(*steps: object, **overrides: object) -> dict[str, Any]:
    stages = [{"name": "Fetch order", "steps": list(steps) or [DO]}]
    content: dict[str, Any] = {
        "version": 2,
        "kind": "scenario",
        "name": "demo",
        "revision": 1,
        "stages": stages,
    }
    return content | overrides


def by_id(document: WorkflowDocument) -> dict[str, Node]:
    return {node.id: node for node in document.nodes}


def problems_of(content: object) -> list[tuple[str, str]]:
    with pytest.raises(WorkflowLoadError) as caught:
        plan_workflow(parse_workflow(content))
    return [(problem.key, problem.message) for problem in caught.value.problems]


def test_translates_to_its_graph_when_the_reference_scenario_loads() -> None:
    graph = json.loads((BLOCKS / "graph" / "b2b-credit-order.json").read_text(encoding="utf-8"))
    expected = parse_workflow(graph)

    document = parse_workflow(tree("b2b-credit-order"))

    assert document.nodes == expected.nodes
    header = {"exclude": {"nodes", "version"}}
    assert document.model_dump(**header) == expected.model_dump(**header)
    assert len(document.nodes) == 22
    for before, node in zip(document.nodes, document.nodes[1:], strict=False):
        assert node.depends_on == (before.id,)
    assert plan_workflow(document).layers == tuple((node.id,) for node in document.nodes)


def test_puts_the_complement_on_the_else_branch_when_an_if_has_an_else() -> None:
    nodes = by_id(parse_workflow(tree("blocks-if-else")))

    then, otherwise, after = nodes["check--2-then-1"], nodes["check--2-else-1"], nodes["check--3"]
    assert (type(then), type(otherwise)) == (ActionNode, ApprovalNode)
    assert then.when == "$CTX.order_status == 'ON_HOLD' && $CTX.order_id != ''"
    assert otherwise.when == "$CTX.order_status != 'ON_HOLD' || $CTX.order_id == ''"
    assert then.depends_on == otherwise.depends_on == ("check--1",)
    assert after.depends_on == ("check--2-then-1", "check--2-else-1")
    assert after.trigger_rule == "none_failed_min_one_success"
    assert "trigger_rule" not in then.model_fields_set


@pytest.mark.parametrize(
    ("condition", "complement"),
    [
        ("$CTX.a == 'x'", "$CTX.a != 'x'"),
        ("$CTX.a != 'it''s'", "$CTX.a == 'it''s'"),
        ("$CTX.n < 3 && $CTX.n >= -1.50", "$CTX.n >= 3 || $CTX.n < -1.50"),
        ("$CTX.n > 0.0000001 || $CTX.n <= 2", "$CTX.n <= 0.0000001 && $CTX.n > 2"),
        (
            "$CTX.paid == true || $CTX.a == 'x' && $CTX.b == 'y'",
            ("$CTX.paid != true && $CTX.a != 'x' || $CTX.paid != true && $CTX.b != 'y'"),
        ),
    ],
    ids=["one-atom", "quote", "and", "or", "mixed"],
)
def test_writes_the_complement_in_the_grammar_when_an_else_is_translated(
    condition: str, complement: str
) -> None:
    capture = {"wait_until": "order-state", "until": "$self.output.n > 0", "every": "15s"}
    capture |= {"timeout": "10m", "capture": {"a": "$self.output.a", "b": "$self.output.b"}}
    capture["capture"] |= {"n": "$self.output.n", "paid": "$self.output.paid"}
    content = a_tree(capture, {"if": condition, "then": [DO], "else": [YOU]})

    nodes = by_id(parse_workflow(content))

    assert nodes["fetch-order--2-then-1"].when == condition
    assert nodes["fetch-order--2-else-1"].when == complement


def test_joins_every_path_when_a_together_is_followed_by_a_step() -> None:
    nodes = by_id(parse_workflow(tree("blocks-together")))

    assert nodes["fix-shipping--2-p1-1"].depends_on == ("fix-shipping--1",)
    assert nodes["fix-shipping--2-p2-1"].depends_on == ("fix-shipping--1",)
    assert nodes["fix-shipping--2-p2-2"].depends_on == ("fix-shipping--2-p2-1",)
    after = nodes["fix-shipping--3"]
    assert after.depends_on == ("fix-shipping--2-p1-1", "fix-shipping--2-p2-2")
    assert after.trigger_rule == "all_success"


def test_becomes_one_loop_group_when_a_step_is_a_repeat() -> None:
    document = parse_workflow(tree("blocks-repeat"))

    first, group = document.nodes
    assert isinstance(first, ExpectNode)
    assert isinstance(group, LoopGroupNode)
    assert (group.id, group.depends_on) == ("poll-cover--2", ("poll-cover--1",))
    assert (group.max_iterations, group.until_when) == (
        5,
        "$poll.output.cover_status == 'ACTIVATED'",
    )
    send, poll = group.nodes
    assert isinstance(send, ActionNode)
    assert isinstance(poll, ExpectNode)
    assert (send.id, send.depends_on) == ("poll-cover--2-1", ())
    assert (poll.id, poll.depends_on) == ("poll", ("poll-cover--2-1",))
    plan = plan_workflow(document)
    assert plan.bodies["poll-cover--2"] == (
        ("poll-cover--2__poll-cover--2-1",),
        ("poll-cover--2__poll",),
    )


def test_distributes_the_branch_condition_when_conditions_nest() -> None:
    nodes = by_id(parse_workflow(tree("blocks-nested")))

    pending = "$CTX.cover_status == 'PENDING'"
    quoted = "$CTX.cover_status == 'QUOTED'"
    assert nodes["route-order--2-then-1-then-1"].when == (
        f"{ON_HOLD} && {pending} || {ON_HOLD} && {quoted}"
    )
    assert nodes["route-order--2-then-1-else-1"].when == (
        f"{ON_HOLD} && $CTX.cover_status != 'PENDING' && $CTX.cover_status != 'QUOTED'"
    )
    fedex = nodes["route-order--2-then-2"]
    assert fedex.when is None
    assert fedex.depends_on == ("route-order--2-then-1-then-1", "route-order--2-then-1-else-1")
    assert fedex.trigger_rule == "none_failed_min_one_success"
    assert nodes["route-order--2-then-3-then-1"].when == quoted
    assert nodes["route-order--2-else-1"].when == "$CTX.order_status != 'ON_HOLD'"
    assert nodes["route-order--2-else-1"].depends_on == ("route-order--1",)


def test_exits_through_the_branch_and_the_block_before_when_an_if_has_no_else() -> None:
    nodes = by_id(parse_workflow(tree("blocks-nested")))

    regenerate = nodes["route-order--2-then-3-then-1"]
    assert regenerate.depends_on == ("route-order--2-then-2",)
    assert "trigger_rule" not in regenerate.model_fields_set
    after = nodes["route-order--3"]
    assert after.depends_on == (
        "route-order--2-then-3-then-1",
        "route-order--2-then-2",
        "route-order--2-else-1",
    )
    assert after.trigger_rule == "none_failed_min_one_success"


def test_joins_after_the_together_when_a_path_ends_with_an_if() -> None:
    branch = {"if": ON_HOLD, "then": [DO], "else": [YOU]}
    content = a_tree(WAIT_UNTIL, {"together": [[branch], [DO]]}, DO)

    nodes = by_id(parse_workflow(content))

    after = nodes["fetch-order--3"]
    assert after.depends_on == (
        "fetch-order--2-p1-1-then-1",
        "fetch-order--2-p1-1-else-1",
        "fetch-order--2-p2-1",
    )
    assert after.trigger_rule == "none_failed_min_one_success"


def test_waits_and_includes_when_the_steps_are_wait_and_include() -> None:
    included = parse_workflow(tree("blocks-repeat"))

    document = parse_workflow(tree("blocks-wait-include"))

    wait, include = document.nodes
    assert isinstance(wait, WaitNode)
    assert (wait.id, wait.duration) == ("settle--1", "1m")
    assert isinstance(include, IncludeNode)
    assert (include.id, include.include, include.depends_on) == (
        "settle--2",
        "blocks-repeat",
        ("settle--1",),
    )
    plan = plan_workflow(document, includes={"blocks-repeat": included}.get)
    assert [node.id for node in plan.document.nodes] == [
        "settle--1",
        "settle--2__poll-cover--1",
        "settle--2__poll-cover--2",
    ]


def test_derives_ids_from_the_stage_slug_when_blocks_have_no_id() -> None:
    content = a_tree(
        stages=[
            {"name": "Switch to FedEx", "steps": [DO, DO | {"id": "send-again"}]},
            {"name": "Invoice: PDF (by hand)", "steps": [YOU]},
        ]
    )

    document = parse_workflow(content)

    assert [node.id for node in document.nodes] == [
        "switch-to-fedex--1",
        "send-again",
        "invoice-pdf-by-hand---1",
    ]


@pytest.mark.parametrize(
    ("content", "key"),
    [
        (a_tree({"if": ON_HOLD, "then": [DO]}), "stages[0].steps[0].if"),
        (
            a_tree(
                WAIT_UNTIL, {"if": ON_HOLD, "then": [{"if": ON_HOLD, "then": [DO]}], "else": [DO]}
            ),
            "stages[0].steps[1].then[0].if",
        ),
        (
            a_tree(WAIT_UNTIL, {"together": [[{"if": ON_HOLD, "then": [DO]}], [DO]]}),
            "stages[0].steps[1].together[0][0].if",
        ),
        (
            a_tree(
                WAIT_UNTIL,
                {"repeat": {"max": 2, "until": ON_HOLD, "steps": [{"if": ON_HOLD, "then": [DO]}]}},
            ),
            "stages[0].steps[1].repeat.steps[0].if",
        ),
        (
            a_tree({"repeat": {"max": 2, "until": ON_HOLD, "steps": [{"include": "other"}]}}),
            "stages[0].steps[0].repeat.steps[0].include",
        ),
        (
            a_tree(
                {
                    "repeat": {
                        "max": 2,
                        "until": ON_HOLD,
                        "steps": [
                            DO,
                            {
                                "if": ON_HOLD,
                                "then": [{"repeat": {"max": 2, "until": ON_HOLD, "steps": [DO]}}],
                            },
                        ],
                    }
                }
            ),
            "stages[0].steps[0].repeat.steps[1].then[0].repeat",
        ),
        (a_tree(DO | {"id": "fetch-order--2"}, DO), "stages[0].steps[0].id"),
        (a_tree(DO | {"id": "send"}, DO | {"id": "send"}), "stages[0].steps[1].id"),
        (a_tree(stages=[{"name": "1. Fetch", "steps": [DO]}]), "stages[0].name"),
        (a_tree(stages=[{"name": "Étape", "steps": [DO]}]), "stages[0].name"),
        (a_tree(DO | {"id": "self"}), "stages[0].steps[0].id"),
    ],
    ids=[
        "if-opens-the-scenario",
        "if-opens-a-branch",
        "if-opens-a-path",
        "if-opens-a-body",
        "include-in-repeat",
        "repeat-in-a-branch-of-a-repeat",
        "id-equals-a-derived-id",
        "ids-equal",
        "slug-digit",
        "slug-accent",
        "self",
    ],
)
def test_names_the_tree_key_when_a_block_breaks_a_translation_rule(
    content: dict[str, Any], key: str
) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)

    assert key in [problem.key for problem in caught.value.problems]


def nested(depth: int) -> dict[str, object]:
    step: dict[str, object] = DO
    for _ in range(depth):
        step = {"together": [[step], [DO]]}
    return step


def test_refuses_the_fourth_container_when_containers_nest_too_deep() -> None:
    assert parse_workflow(a_tree(WAIT_UNTIL, nested(3)))
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(a_tree(WAIT_UNTIL, nested(4)))

    key = "stages[0].steps[1].together[0][0].together[0][0].together[0][0].together"
    assert [problem.key for problem in caught.value.problems] == [key]


def test_refuses_the_block_that_passes_the_cap_when_a_tree_has_too_many_nodes() -> None:
    stages = [{"name": f"Stage {number}", "steps": [DO] * 16} for number in range(33)]

    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(a_tree(stages=stages))

    assert MAX_TREE_NODES == 512
    assert [problem.key for problem in caught.value.problems] == ["stages[32].steps[0]"]


def test_refuses_the_join_when_a_nested_condition_passes_sixty_four_terms() -> None:
    clauses = [range(3), range(3, 6), range(6, 8)]
    wide = " || ".join(" && ".join(f"$CTX.order_id == 'o-{n}'" for n in c) for c in clauses)
    inner = {"if": wide, "then": [DO], "else": [YOU]}
    content = a_tree(WAIT_UNTIL, {"if": wide, "then": [DO], "else": [inner]})

    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)

    assert [problem.key for problem in caught.value.problems] == ["stages[0].steps[1].if"]
    assert "64 terms" in caught.value.problems[0].message


@pytest.mark.parametrize(
    ("steps", "key"),
    [
        (
            [{"do": "queue-send", "with": {"order_id": "$CTX.order_id"}}],
            "stages[0].steps[0].with.order_id",
        ),
        ([DO, {"if": "$CTX.nope == 'x'", "then": [DO], "else": [YOU]}], "stages[0].steps[1].if"),
        ([WAIT_UNTIL, {"together": [[YOU], [YOU]]}], "stages[0].steps[1].together[1][0]"),
        (
            [{"repeat": {"max": 2, "until": "$nope.output == 'x'", "steps": [DO]}}],
            "stages[0].steps[0].repeat.until",
        ),
        (
            [
                {
                    "repeat": {
                        "max": 2,
                        "until": "$fetch-order--1-1.output.ok == true",
                        "steps": [DO | {"with": {"x": "$CTX.nope"}}],
                    }
                }
            ],
            "stages[0].steps[0].repeat.steps[0].with.x",
        ),
        (
            [
                {
                    "wait_until": "order-state",
                    "until": "$CTX.nope == 'x'",
                    "every": "15s",
                    "timeout": "1m",
                }
            ],
            "stages[0].steps[0].until",
        ),
        ([YOU | {"you": "Pay $CTX.nope by hand."}], "stages[0].steps[0].you"),
    ],
    ids=["with", "if", "unordered-gates", "repeat-until", "body", "until", "you"],
)
def test_puts_a_plan_problem_on_the_tree_key_when_a_generated_node_has_it(
    steps: list[object], key: str
) -> None:
    assert [found for found, _ in problems_of(a_tree(*steps))] == [key]


def test_puts_an_included_problem_on_the_include_when_the_included_tree_breaks() -> None:
    broken = a_tree({"do": "queue-send", "with": {"order_id": "$INPUTS.nope"}}, name="broken")
    content = a_tree(DO, {"include": "broken"})

    with pytest.raises(WorkflowLoadError) as caught:
        plan_workflow(parse_workflow(content), includes={"broken": None}.get)
    assert [p.key for p in caught.value.problems] == ["stages[0].steps[1].include"]

    included = {"broken": parse_workflow(broken)}
    with pytest.raises(WorkflowLoadError) as caught:
        plan_workflow(parse_workflow(content), includes=included.get)
    assert [p.key for p in caught.value.problems] == ["stages[0].steps[1].include"]


def test_puts_a_gated_plan_problem_on_the_tree_key_when_the_step_is_gated() -> None:
    content = a_tree(DO, {"together": [[YOU], [DO]]})

    with pytest.raises(WorkflowLoadError) as caught:
        gated_plan(parse_workflow(content), includes=None, asks={"fetch-order--2-p2-1": ASK})

    keys = [problem.key for problem in caught.value.problems]
    assert keys == ["stages[0].steps[1].together[1][0]"]


def test_gives_each_block_its_address_and_nodes_when_the_block_map_is_read() -> None:
    blocks = {block.address: block for block in block_map(tree("blocks-if-else")).blocks}

    assert list(blocks) == ["1", "1.1", "1.2", "1.2.then.1", "1.2.else.1", "1.3"]
    stage, branch = blocks["1"], blocks["1.2"]
    assert (stage.kind, stage.label, stage.key) == ("stage", "Check", ("stages", 0))
    assert stage.nodes == ("check--1", "check--2-then-1", "check--2-else-1", "check--3")
    assert (stage.entry_nodes, stage.exit_nodes) == (("check--1",), ("check--3",))
    assert (branch.kind, branch.key) == ("if", ("stages", 0, "steps", 1))
    assert branch.label == "$CTX.order_status == 'ON_HOLD' && $CTX.order_id != ''"
    assert branch.entry_nodes == branch.exit_nodes == ("check--2-then-1", "check--2-else-1")
    otherwise = blocks["1.2.else.1"]
    assert (otherwise.kind, otherwise.key) == ("you", ("stages", 0, "steps", 1, "else", 0))
    assert otherwise.label == "The order is not on hold: check it by hand, then approve."


def test_records_body_nodes_by_their_run_ids_when_the_block_map_holds_a_repeat() -> None:
    blocks = {block.address: block for block in block_map(tree("blocks-repeat")).blocks}

    assert list(blocks) == ["1", "1.1", "1.2", "1.2.1", "1.2.2"]
    group = blocks["1.2"]
    assert (group.kind, group.entry_nodes, group.exit_nodes) == (
        "repeat",
        ("poll-cover--2",),
        ("poll-cover--2",),
    )
    assert group.nodes == ("poll-cover--2", "poll-cover--2__poll-cover--2-1", "poll-cover--2__poll")
    assert blocks["1.2.2"].entry_nodes == ("poll-cover--2__poll",)
    assert blocks["1.2.2"].key == ("stages", 0, "steps", 1, "repeat", "steps", 1)


def test_lists_each_path_when_the_block_map_holds_a_together() -> None:
    blocks = {block.address: block for block in block_map(tree("blocks-together")).blocks}

    assert list(blocks) == ["1", "1.1", "1.2", "1.2.p1.1", "1.2.p2.1", "1.2.p2.2", "1.3"]
    paths = blocks["1.2"]
    assert (paths.kind, paths.label) == ("together", "2 paths")
    assert paths.entry_nodes == ("fix-shipping--2-p1-1", "fix-shipping--2-p2-1")
    assert paths.exit_nodes == ("fix-shipping--2-p1-1", "fix-shipping--2-p2-2")
    assert blocks["1.2.p2.2"].key == ("stages", 0, "steps", 1, "together", 1, 1)


def test_counts_the_ask_gate_and_the_included_roots_when_entries_are_read_in_a_plan() -> None:
    content = tree("blocks-wait-include")
    included = {"blocks-repeat": parse_workflow(tree("blocks-repeat"))}
    asks = {"settle--2__poll-cover--1": ASK}
    plan = gated_plan(parse_workflow(content), includes=included.get, asks=asks)

    entries = block_map(content).run_entries(plan)

    assert entries["1.1"] == ("settle--1",)
    assert entries["1.2"] == ("settle--2__poll-cover--1__ask",)

    gated = gated_plan(
        parse_workflow(tree("blocks-together")), includes=None, asks={"fix-shipping--2-p2-1": ASK}
    )
    entries = block_map(tree("blocks-together")).run_entries(gated)
    assert entries["1.2"] == ("fix-shipping--2-p1-1", "fix-shipping--2-p2-1__ask")
    assert entries["1.2.p2.1"] == ("fix-shipping--2-p2-1__ask",)


def test_gives_the_same_graph_and_block_map_when_a_tree_is_translated_twice() -> None:
    first, second = translate_tree(tree("blocks-nested")), translate_tree(tree("blocks-nested"))

    assert first.document.nodes == second.document.nodes
    assert first.blocks == second.blocks


@pytest.mark.parametrize(
    ("step", "key"),
    [
        ({"wait": {"duration": "1m", "attention": "Look."}}, "stages[0].steps[0].wait"),
        ({"wait": {"until": "tomorrow"}}, "stages[0].steps[0].wait.until"),
        (
            YOU | {"decisions": [{"id": "go", "label": "Go"}, {"id": "go", "label": "Again"}]},
            "stages[0].steps[0].decisions",
        ),
        (
            {
                "repeat": {
                    "max": 2,
                    "until": "$w.output.at != ''",
                    "steps": [{"wait": {}, "id": "w"}],
                }
            },
            "stages[0].steps[0].repeat.steps[0].wait",
        ),
    ],
    ids=["two-conditions", "until", "decisions", "body"],
)
def test_names_the_tree_key_when_a_generated_node_breaks_its_own_rule(
    step: dict[str, object], key: str
) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(a_tree(step))

    assert [problem.key for problem in caught.value.problems] == [key]


def test_keeps_a_problem_where_it_is_when_no_block_holds_its_node() -> None:
    document = parse_workflow(a_tree(DO))
    other = document.nodes[0].model_copy(update={"id": "other"})
    grown = document.model_copy(update={"nodes": (*document.nodes, other)})
    problems = [
        WorkflowProblem(("inputs", "x"), "a"),
        WorkflowProblem(("nodes", 1, "with"), "b"),
        WorkflowProblem(("nodes", 9), "c"),
        WorkflowProblem(("nodes", 0, "depends_on", 0), "d"),
    ]

    assert [p.key for p in grown.located(problems)] == [
        "inputs.x",
        "nodes[1].with",
        "nodes[9]",
        "stages[0].steps[0]",
    ]


def test_finds_a_block_by_its_address_when_the_tree_holds_it() -> None:
    blocks = block_map(tree("blocks-nested"))

    found = blocks.block("1.2.then.3.then.1")
    assert found is not None
    assert (found.kind, found.label, found.nodes) == (
        "do",
        "shipments-regenerate",
        ("route-order--2-then-3-then-1",),
    )
    assert blocks.block("1.9") is None


def test_writes_one_opposite_atom_per_clause_when_a_condition_is_complemented() -> None:
    condition = parse_condition("$CTX.a == 1 && $CTX.b == 2 || $CTX.c == 3", scenario=True)

    negated = complement(condition)

    assert condition_text(negated) == "$CTX.a != 1 && $CTX.c != 3 || $CTX.b != 2 && $CTX.c != 3"
    assert condition_text(complement(negated)) == (
        "$CTX.a == 1 && $CTX.b == 2 || $CTX.a == 1 && $CTX.c == 3"
        " || $CTX.c == 3 && $CTX.b == 2 || $CTX.c == 3 && $CTX.c == 3"
    )


def test_puts_a_gated_problem_on_the_include_when_an_included_step_is_gated() -> None:
    included = {"sub": parse_workflow(a_tree(DO, name="sub"))}
    content = a_tree(DO, {"together": [[YOU], [{"include": "sub"}]]})
    asks = {"fetch-order--2-p2-1__fetch-order--1": ASK}

    with pytest.raises(WorkflowLoadError) as caught:
        gated_plan(parse_workflow(content), includes=included.get, asks=asks)

    [problem] = caught.value.problems
    assert problem.key == "stages[0].steps[1].together[1][0].include"
    assert problem.message.startswith('"fetch-order--2-p2-1__fetch-order--1__ask": $: ')


def test_keeps_the_description_on_its_node_when_a_block_has_one() -> None:
    repeat = {"repeat": {"max": 2, "until": "$x.output.ok == true", "steps": [DO | {"id": "x"}]}}
    content = a_tree(DO | {"description": "Send it."}, repeat | {"description": "Again."})

    send, group = parse_workflow(content).nodes

    assert (send.description, group.description) == ("Send it.", "Again.")
