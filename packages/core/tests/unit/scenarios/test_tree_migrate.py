"""A graph scenario (version 1) written as a tree (version 2) and the graphs that cannot be
(AC-507.20, .21; docs/design/scenarios.md § Tree format)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_hub.core.scenarios.tree_migrate import MigrationError, MigrationProblem, migrate_graph
from agent_hub.core.scenarios.tree_translate import translate_tree
from agent_hub.core.workflows.document import WorkflowDocument, parse_workflow

BLOCKS = Path(__file__).parents[2] / "data" / "scenarios" / "blocks"
REFERENCE = "demo-order-roundtrip"
ON_HOLD = "$CTX.order_status == 'ON_HOLD'"
NOT_ON_HOLD = "$CTX.order_status != 'ON_HOLD'"
JOIN = "none_failed_min_one_success"


def tree(name: str, folder: str = "tree") -> dict[str, Any]:
    content = yaml.safe_load((BLOCKS / folder / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def a_graph(*nodes: dict[str, Any], **overrides: object) -> dict[str, Any]:
    content: dict[str, Any] = {
        "version": 1,
        "kind": "scenario",
        "name": "walk",
        "revision": 2,
        "nodes": list(nodes),
    }
    return content | overrides


def do(node_id: str, *depends_on: str, **keys: object) -> dict[str, Any]:
    node: dict[str, Any] = {"id": node_id, "type": "action", "action": "queue-send"}
    if depends_on:
        node["depends_on"] = list(depends_on)
    return node | keys


def problems_of(content: object) -> list[tuple[str | None, str]]:
    with pytest.raises(MigrationError) as caught:
        migrate_graph(content)
    return [(problem.node, problem.message) for problem in caught.value.problems]


def shape(document: WorkflowDocument) -> dict[str, Any]:
    """Each node by id, its ``depends_on`` as a set: the graph's nodes, edges and conditions."""
    out: dict[str, Any] = {}
    for node in document.nodes:
        data = node.model_dump(mode="json", by_alias=True)
        data["depends_on"] = sorted(data["depends_on"])
        if isinstance(data.get("nodes"), list):
            body = {
                item["id"]: item | {"depends_on": sorted(item["depends_on"])}
                for item in data["nodes"]
            }
            data["nodes"] = body
        out[node.id] = data
    return out


def test_writes_the_reference_scenario_in_one_stage_when_its_graph_is_migrated() -> None:
    graph = json.loads((BLOCKS / "graph" / f"{REFERENCE}.json").read_text(encoding="utf-8"))

    migrated = migrate_graph(graph)

    assert migrated == tree(REFERENCE, folder="migrated")
    translated = translate_tree(migrated).document
    original = parse_workflow(graph)
    assert translated.nodes == original.nodes
    header = {"exclude": {"nodes", "version"}}
    assert translated.model_dump(**header) == original.model_dump(**header)


def test_takes_its_header_and_parsed_document_when_given_a_document() -> None:
    graph = json.loads((BLOCKS / "graph" / f"{REFERENCE}.json").read_text(encoding="utf-8"))

    assert migrate_graph(parse_workflow(graph)) == migrate_graph(graph)


@pytest.mark.parametrize(
    "name",
    ["blocks-if-else", "blocks-repeat", "blocks-together", "blocks-wait-include", REFERENCE],
)
def test_translates_to_the_same_graph_when_a_translated_tree_is_migrated(name: str) -> None:
    graph = translate_tree(tree(name)).document

    migrated = migrate_graph(graph)

    assert shape(translate_tree(migrated).document) == shape(graph)
    assert [stage["name"] for stage in migrated["stages"]] == [name]


WAIT_UNTIL = {
    "wait_until": "order-state",
    "until": "$self.output.order_id != ''",
    "every": "15s",
    "timeout": "10m",
    "capture": {"order_id": "$self.output.order_id", "order_status": "$self.output.status"},
}
DO = {"do": "queue-send", "with": {"message": "demo.poll"}}
YOU = {"you": "Check the order by hand, then approve."}
BRANCH = {"if": ON_HOLD, "then": [DO], "else": [YOU]}


def a_tree(*steps: object) -> dict[str, Any]:
    stages = [{"name": "Fix order", "steps": [WAIT_UNTIL, *steps, DO]}]
    return {"version": 2, "kind": "scenario", "name": "fix", "revision": 1, "stages": stages}


@pytest.mark.parametrize(
    "content",
    [
        a_tree({"together": [[BRANCH], [DO]]}),
        a_tree({"together": [[BRANCH], [BRANCH], [DO, YOU]]}),
        a_tree({"together": [[BRANCH, DO], [YOU]]}),
        a_tree({"if": ON_HOLD, "then": [{"together": [[DO], [YOU, DO]]}, YOU]}),
        a_tree({"if": ON_HOLD, "then": [{"together": [[DO], [YOU]]}], "else": [YOU]}),
        a_tree(
            {"repeat": {"max": 3, "until": ON_HOLD, "steps": [DO, {"if": ON_HOLD, "then": [YOU]}]}}
        ),
    ],
    ids=[
        "path-is-an-if",
        "paths-are-ifs",
        "path-opens-with-an-if",
        "if-opens-with-a-together",
        "branch-opens-with-a-together",
        "if-in-a-repeat",
    ],
)
def test_translates_to_the_same_graph_when_paths_and_branches_open_with_containers(
    content: dict[str, Any],
) -> None:
    graph = translate_tree(content).document

    migrated = migrate_graph(graph)

    assert shape(translate_tree(migrated).document) == shape(graph)


def test_maps_each_shape_when_a_graph_is_series_parallel() -> None:
    wait_until = {
        "id": "walk--1",
        "type": "expect",
        "action": "order-state",
        "every": "15s",
        "timeout": "10m",
        "until_when": "$self.output.order_id != ''",
        "capture": {"order_id": "$self.output.order_id", "order_status": "$self.output.status"},
    }
    loop = {
        "id": "poll-loop",
        "type": "loop_group",
        "description": "Poll until approved",
        "depends_on": ["held", "not-held"],
        "trigger_rule": JOIN,
        "max_iterations": 5,
        "until_when": "$poll.output.review_status == 'APPROVED'",
        "nodes": [
            do("send"),
            {
                "id": "poll",
                "type": "expect",
                "action": "order-state",
                "depends_on": ["send"],
                "every": "15s",
                "timeout": "10m",
                "until_when": "$self.output.review_status != ''",
            },
        ],
    }
    graph = a_graph(
        wait_until,
        do("carrier", "walk--1", action="order-set-carrier", description="Switch carrier"),
        do("regen", "walk--1", action="shipments-regenerate", retry={"max_attempts": 2}),
        do("transit", "regen", action="shipments-mark-in-transit", timeout="1m"),
        do("held", "carrier", "transit", when=ON_HOLD, action="order-tasks-resolve"),
        {
            "id": "not-held",
            "type": "approval",
            "depends_on": ["carrier", "transit"],
            "when": NOT_ON_HOLD,
            "message": "Not on hold: check it by hand.",
            "capture_response": True,
        },
        loop,
        do("extra", "poll-loop", when="$CTX.order_id != ''", **{"with": {"message": "demo.poll"}}),
        {
            "id": "settle",
            "type": "wait",
            "depends_on": ["extra", "poll-loop"],
            "trigger_rule": JOIN,
            "duration": "1m",
        },
        {
            "id": "walk--7",
            "type": "include",
            "depends_on": ["settle"],
            "include": "other-walk",
            "with": {"order_id": "$CTX.order_id"},
        },
        description="A walk with every block",
        inputs={"ref": {"type": "string", "required": True}},
    )

    migrated = migrate_graph(graph)

    assert migrated == {
        "version": 2,
        "kind": "scenario",
        "name": "walk",
        "revision": 2,
        "description": "A walk with every block",
        "inputs": {"ref": {"type": "string", "required": True}},
        "stages": [
            {
                "name": "walk",
                "steps": [
                    {
                        "wait_until": "order-state",
                        "until": "$self.output.order_id != ''",
                        "every": "15s",
                        "timeout": "10m",
                        "capture": wait_until["capture"],
                    },
                    {
                        "together": [
                            [
                                {
                                    "do": "order-set-carrier",
                                    "id": "carrier",
                                    "description": "Switch carrier",
                                }
                            ],
                            [
                                {
                                    "do": "shipments-regenerate",
                                    "id": "regen",
                                    "retry": {"max_attempts": 2},
                                },
                                {
                                    "do": "shipments-mark-in-transit",
                                    "id": "transit",
                                    "timeout": "1m",
                                },
                            ],
                        ]
                    },
                    {
                        "if": ON_HOLD,
                        "then": [{"do": "order-tasks-resolve", "id": "held"}],
                        "else": [
                            {
                                "you": "Not on hold: check it by hand.",
                                "id": "not-held",
                                "capture_response": True,
                            }
                        ],
                    },
                    {
                        "repeat": {
                            "max": 5,
                            "until": "$poll.output.review_status == 'APPROVED'",
                            "steps": [
                                {"do": "queue-send", "id": "send"},
                                {
                                    "wait_until": "order-state",
                                    "id": "poll",
                                    "until": "$self.output.review_status != ''",
                                    "every": "15s",
                                    "timeout": "10m",
                                },
                            ],
                        },
                        "id": "poll-loop",
                        "description": "Poll until approved",
                    },
                    {
                        "if": "$CTX.order_id != ''",
                        "then": [
                            {"do": "queue-send", "id": "extra", "with": {"message": "demo.poll"}}
                        ],
                    },
                    {"wait": {"duration": "1m"}, "id": "settle"},
                    {"include": "other-walk", "with": {"order_id": "$CTX.order_id"}},
                ],
            }
        ],
    }
    assert shape(translate_tree(migrated).document) == shape(parse_workflow(graph))


def test_names_the_stage_with_a_letter_when_the_scenario_name_starts_with_a_digit() -> None:
    migrated = migrate_graph(a_graph(do("send"), name="1-walk"))

    assert migrated["stages"][0]["name"] == "scenario 1-walk"
    assert migrated["stages"][0]["steps"] == [{"do": "queue-send", "id": "send"}]


NESTED = translate_tree(tree("blocks-nested")).document
NESTED_ENTRIES = (
    "route-order--2-then-1-then-1",
    "route-order--2-then-1-else-1",
    "route-order--2-else-1",
)
STARTS_TOGETHER = (
    "starts together with {others}, each with a when of its own: migrate reads nodes that start"
    " together with a when only as an If with an else (a condition, and its exact complement on"
    " the else's first block), and does not split the conditions of nested Ifs joined on one node"
)


def _starts_together(node: str) -> str:
    others = ", ".join(json.dumps(other) for other in NESTED_ENTRIES if other != node)
    return STARTS_TOGETHER.format(others=others)


# ``c1``, ``c2`` with a when, ``c3`` and ``c4`` each after the one before with a when: an If
# whose then holds the next If, three deep; a container after ``c4`` would be the fourth.
THREE_IFS = (do("c1"), *(do(f"c{n}", f"c{n - 1}", when=ON_HOLD) for n in range(2, 5)))
TOO_DEEP = (
    "as a block it would not load: stages[0].steps[1].then[1].then[1].then[1].{kind}:"
    " containers nest at most 3 deep"
)
BRANCHES_MEET = (
    "starts a branch that meets the other branch before the block after the If: the graph is"
    " not series-parallel"
)


@pytest.mark.parametrize(
    ("content", "problems"),
    [
        (
            a_graph(do("a"), do("b", "a", trigger_rule="one_success")),
            [
                (
                    "b",
                    "has trigger_rule one_success: a tree joins with all_success, or with"
                    " none_failed_min_one_success after an If; no block gives one_success",
                )
            ],
        ),
        (
            a_graph(
                do("a"),
                do("b", "a", trigger_rule="all_done"),
                do("c", "b", trigger_rule="one_success"),
            ),
            [
                (
                    "b",
                    "has trigger_rule all_done: a tree joins with all_success, or with"
                    " none_failed_min_one_success after an If; no block gives all_done",
                ),
                (
                    "c",
                    "has trigger_rule one_success: a tree joins with all_success, or with"
                    " none_failed_min_one_success after an If; no block gives one_success",
                ),
            ],
        ),
        (
            a_graph(do("a"), do("b"), do("c"), do("d", "a", "b"), do("e", "b", "c")),
            [
                (
                    node,
                    f"starts together with {others}, but their paths meet before the block after"
                    " them: the graph is not series-parallel",
                )
                for node, others in (("a", '"b", "c"'), ("b", '"a", "c"'), ("c", '"a", "b"'))
            ],
        ),
        (
            a_graph(do("a"), do("b"), do("c", "a"), do("d", "a", "b")),
            [
                (
                    "d",
                    'depends on "a", "b", but a block there depends on the ends of the block'
                    ' before it, "c", "b": the graph is not series-parallel',
                )
            ],
        ),
        (
            a_graph(do("a"), do("b", "a"), do("c", "a"), do("d", "b", "c", trigger_rule=JOIN)),
            [
                (
                    "d",
                    "has trigger_rule none_failed_min_one_success, which a tree gives only to"
                    " the block after an If (or after a Together a path of which ends with one)",
                )
            ],
        ),
        (
            a_graph(
                do("a"),
                do("b", "a", when=ON_HOLD),
                do("c", "a", when=NOT_ON_HOLD),
                do("d", "b", "c"),
            ),
            [
                (
                    "d",
                    "follows an If (or a Together a path of which ends with one), so a tree"
                    " gives it trigger_rule none_failed_min_one_success, not all_success",
                )
            ],
        ),
        (
            a_graph(do("a", when=ON_HOLD), do("b", "a")),
            [
                (
                    "a",
                    "has a when, which a tree writes as an If with no else, and such an If"
                    " cannot open a step list (the scenario's start, a branch, a path or a"
                    " Repeat body)",
                )
            ],
        ),
        (
            a_graph(do("a"), do("b", "a", when=ON_HOLD), do("c", "a", when="$CTX.order_id != ''")),
            [
                (
                    "c",
                    'its when is not the exact complement of the when of "b", so the two are'
                    " no If with an else: the else of $CTX.order_status == 'ON_HOLD' is"
                    " $CTX.order_status != 'ON_HOLD'",
                )
            ],
        ),
        (
            NESTED,
            [(node, _starts_together(node)) for node in NESTED_ENTRIES],
        ),
        (
            a_graph(
                do("a"),
                {
                    "id": "loop",
                    "type": "loop_group",
                    "depends_on": ["a"],
                    "max_iterations": 3,
                    "until_bash": ["test", "-f", "done"],
                    "fresh_context": True,
                    "nodes": [do("b")],
                },
            ),
            [
                ("loop", "has until_bash: a Repeat ends only on its until condition"),
                ("loop", "has fresh_context: a Repeat has no fresh_context"),
            ],
        ),
        (
            a_graph(do("a"), returns="a"),
            [
                (
                    None,
                    "returns: the tree format has no returns (an include reads an included"
                    " tree's output from its single last node)",
                )
            ],
        ),
        (
            a_graph(do("a"), outcome_field="status"),
            [(None, "outcome_field: the tree format has no outcome_field")],
        ),
        (
            a_graph(do("s"), do("a", "s", "b"), do("b", "a")),
            [
                ("a", "depends on a node that depends on it: the graph has a cycle"),
                ("b", "depends on a node that depends on it: the graph has a cycle"),
            ],
        ),
        (
            a_graph(do("a"), do("b", "a", when="$CTX.order_id == '" + "x" * 1_100 + "'")),
            [("b", "its when holds 1,119 characters: an If's condition holds at most 1,024")],
        ),
        (
            a_graph(do("a"), do("b", "a", when=" && ".join(f"$CTX.v{n} == 'x'" for n in range(9)))),
            [("b", "its when holds 9 atoms: an If's condition holds at most 8")],
        ),
        (
            a_graph(do("a"), do("b", "a", when="$CTX.order_id ==")),
            [
                (
                    "b",
                    'its when cannot be an If\'s condition: "$CTX.order_id ==": each atom is'
                    " <reference> <operator> <literal>",
                )
            ],
        ),
        (
            # ``b`` and ``c`` (a condition and its complement) meet at ``x``; ``d`` meets nothing.
            a_graph(
                do("a"),
                do("b", "a", when=ON_HOLD),
                do("c", "a", when=NOT_ON_HOLD),
                do("d", "a", when=ON_HOLD),
                do("x", "b", "c", trigger_rule=JOIN),
                do("z", "x", "d"),
            ),
            [("b", BRANCHES_MEET), ("c", BRANCHES_MEET)],
        ),
        (
            a_graph(
                *THREE_IFS,
                {
                    "id": "loop",
                    "type": "loop_group",
                    "depends_on": ["c4"],
                    "max_iterations": 2,
                    "until_when": ON_HOLD,
                    "nodes": [do("e")],
                },
            ),
            [("loop", TOO_DEEP.format(kind="repeat"))],
        ),
        (
            a_graph(*THREE_IFS, do("e", "c4"), do("f", "c4"), do("h", "e", "f")),
            [("e", TOO_DEEP.format(kind="together"))],
        ),
        (
            # A Together of two Ifs with an else; in the first, the Ifs of ``d`` and ``e``: the
            # fourth container is refused as such, not as entries that are no Together.
            a_graph(
                do("a"),
                do("b", "a", when=ON_HOLD),
                do("b2", "a", when=NOT_ON_HOLD),
                do("c", "a", when="$CTX.order_id != ''"),
                do("c2", "a", when="$CTX.order_id == ''"),
                do("d", "b", when="$CTX.order_id != ''"),
                do("e", "d", when="$CTX.order_id != ''"),
                do("z", "e", "b2", "c", "c2", trigger_rule=JOIN),
            ),
            [
                (
                    "e",
                    "as a block it would not load:"
                    " stages[0].steps[1].together[0][0].then[1].then[1].if: containers nest at"
                    " most 3 deep",
                )
            ],
        ),
    ],
    ids=[
        "one-success",
        "each-node",
        "paths-meet",
        "not-series-parallel",
        "join-without-if",
        "if-without-join",
        "when-opens",
        "not-a-complement",
        "joined-conditions",
        "until-bash",
        "returns",
        "outcome-field",
        "cycle",
        "long-condition",
        "many-atoms",
        "no-condition",
        "branches-meet",
        "repeat-too-deep",
        "together-too-deep",
        "too-deep-in-a-together",
    ],
)
def test_names_each_node_and_why_when_a_graph_cannot_be_mapped(
    content: object, problems: list[tuple[str | None, str]]
) -> None:
    assert problems_of(content) == problems


@pytest.mark.parametrize("size", [5, 400])
def test_names_only_the_first_container_too_deep_when_ifs_nest_past_the_cap(size: int) -> None:
    # Each node after ``c1`` follows the one before with a when: Ifs nested in turn, so the If
    # of ``c5`` is the fourth; nothing inside it is read, whatever the chain's length.
    chain = (do(f"c{n}", f"c{n - 1}", when=ON_HOLD) for n in range(2, size + 1))

    assert problems_of(a_graph(do("c1"), *chain)) == [("c5", TOO_DEEP.format(kind="if"))]


def test_refuses_the_document_when_it_is_not_a_scenario() -> None:
    shell = {"id": "a", "type": "shell", "command": ["true"]}

    assert problems_of(a_graph(shell, kind="workflow")) == [
        (None, "kind: only a scenario has a tree format")
    ]


def test_refuses_the_document_when_it_is_already_a_tree() -> None:
    assert problems_of(tree("blocks-if-else")) == [
        (None, "version: it is already written as blocks (version 2)")
    ]


def test_shows_the_node_and_message_when_a_problem_is_printed() -> None:
    assert str(MigrationProblem("b", "has a when")) == 'node "b": has a when'
    assert str(MigrationProblem(None, "returns: no returns")) == "returns: no returns"
