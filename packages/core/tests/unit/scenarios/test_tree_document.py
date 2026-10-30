"""The tree format (version 2) of a scenario and its load errors, each at the tree's key path
(AC-507.2; docs/design/scenarios.md § Tree format)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import TypeAdapter

from agent_hub.core.scenarios import tree_document as tree_module
from agent_hub.core.scenarios.tree_document import (
    MAX_CONDITION_CHARS,
    DoStep,
    IfStep,
    RepeatStep,
    TogetherStep,
    TreeDocument,
    WaitUntilStep,
    YouStep,
    parse_tree,
)
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow

TREES = Path(__file__).parents[2] / "data" / "scenarios" / "blocks" / "tree"
DO = {"do": "queue-send", "with": {"message": "demo.fetch-orders"}}
WAIT_UNTIL = {
    "wait_until": "order-state",
    "until": "$self.output.order_id != ''",
    "every": "15s",
    "timeout": "10m",
    "capture": {"order_id": "$self.output.order_id"},
}
YOU = {"you": "Check the order by hand, then approve."}
NINE_ATOMS = " && ".join(f"$CTX.order_id != 'o-{n}'" for n in range(9))


def a_tree(*steps: object, **overrides: object) -> dict[str, Any]:
    stages = [{"name": "Fetch order", "steps": list(steps) or [DO]}]
    tree: dict[str, Any] = {
        "version": 2,
        "kind": "scenario",
        "name": "demo",
        "revision": 1,
        "stages": stages,
    }
    return tree | overrides


def a_stage(name: str, *steps: object) -> dict[str, object]:
    return {"name": name, "steps": list(steps) or [DO]}


def keys_of(content: object) -> list[str]:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)
    return [problem.key for problem in caught.value.problems]


def messages_of(content: object) -> list[str]:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)
    return [problem.message for problem in caught.value.problems]


def test_reads_each_stage_and_step_when_the_reference_tree_loads() -> None:
    content = yaml.safe_load((TREES / "demo-order-roundtrip.yaml").read_text(encoding="utf-8"))

    tree = parse_tree(content)

    assert isinstance(tree, TreeDocument)
    assert [stage.name for stage in tree.stages] == [
        "Fetch order",
        "Review",
        "Switch carrier",
        "Dispatch",
        "Invoice PDF",
        "Send invoice",
        "Approval",
        "Payment",
    ]
    assert [type(step) for step in tree.stages[0].steps] == [DoStep, WaitUntilStep]
    assert isinstance(tree.stages[4].steps[0], YouStep)
    assert tree.stages[0].steps[1].kind == "wait_until"
    assert sum(len(stage.steps) for stage in tree.stages) == 22


def test_reads_the_containers_when_a_tree_holds_if_together_and_repeat() -> None:
    if_else = parse_tree(yaml.safe_load((TREES / "blocks-if-else.yaml").read_text("utf-8")))
    together = parse_tree(yaml.safe_load((TREES / "blocks-together.yaml").read_text("utf-8")))
    repeat = parse_tree(yaml.safe_load((TREES / "blocks-repeat.yaml").read_text("utf-8")))

    branch = if_else.stages[0].steps[1]
    paths = together.stages[0].steps[1]
    group = repeat.stages[0].steps[1]
    assert isinstance(branch, IfStep)
    assert (len(branch.then), len(branch.else_ or ())) == (1, 1)
    assert isinstance(paths, TogetherStep)
    assert [len(path) for path in paths.together] == [1, 2]
    assert isinstance(group, RepeatStep)
    assert (group.repeat.max, len(group.repeat.steps)) == (5, 2)


@pytest.mark.parametrize(
    ("content", "key"),
    [
        (a_tree(nodes=[{"id": "a", "type": "action", "action": "queue-send"}]), "nodes"),
        (a_tree(DO, WAIT_UNTIL | {"depends_on": ["x"]}), "stages[0].steps[1].depends_on"),
        (a_tree(DO, WAIT_UNTIL | {"trigger_rule": "all_done"}), "stages[0].steps[1].trigger_rule"),
        (
            a_tree(
                {
                    "repeat": {
                        "max": 2,
                        "until": "$CTX.order_id != ''",
                        "steps": [
                            {"repeat": {"max": 2, "until": "$CTX.order_id != ''", "steps": [DO]}}
                        ],
                    }
                }
            ),
            "stages[0].steps[0].repeat.steps[0].repeat",
        ),
        (
            a_tree(stages=[a_stage("Fetch order"), a_stage("Review"), a_stage("fetch  ORDER")]),
            "stages[2].name",
        ),
        (a_tree(DO | {"whn": "x"}), "stages[0].steps[0].whn"),
        (
            a_tree(WAIT_UNTIL, {"if": NINE_ATOMS, "then": [DO], "else": [YOU]}),
            "stages[0].steps[1].if",
        ),
    ],
    ids=[
        "nodes",
        "depends-on",
        "trigger-rule",
        "repeat-in-repeat",
        "same-stage",
        "unknown",
        "atoms",
    ],
)
def test_names_the_tree_key_when_a_shape_is_refused(content: dict[str, Any], key: str) -> None:
    assert keys_of(content) == [key]


@pytest.mark.parametrize(
    ("content", "key"),
    [
        (a_tree(DO | {"you": "Approve."}), "stages[0].steps[0]"),
        (a_tree({"with": {"message": "x"}}), "stages[0].steps[0]"),
        (a_tree("do queue-send"), "stages[0].steps[0]"),
        (a_tree({"do": "Queue Send"}), "stages[0].steps[0].do"),
        (
            a_tree({"wait_until": "order-state", "every": "15s", "timeout": "10m"}),
            "stages[0].steps[0].until",
        ),
        (
            a_tree(
                {
                    "wait_until": "order-state",
                    "until": "$self.output.x == 1",
                    "every": "1s",
                    "timeout": "10m",
                }
            ),
            "stages[0].steps[0].every",
        ),
        (a_tree(DO | {"timeout": "2h"}), "stages[0].steps[0].timeout"),
        (a_tree(WAIT_UNTIL, {"if": "$CTX.order_id", "then": [DO]}), "stages[0].steps[1].if"),
        (a_tree(WAIT_UNTIL, {"if": "$CTX.order_id != ''", "then": []}), "stages[0].steps[1].then"),
        (
            a_tree(WAIT_UNTIL, {"if": "$CTX.order_id != ''", "then": [DO], "else": []}),
            "stages[0].steps[1].else",
        ),
        (
            a_tree(WAIT_UNTIL, {"if": "$CTX.order_id != ''", "then": [DO], "id": "x"}),
            "stages[0].steps[1].id",
        ),
        (a_tree(WAIT_UNTIL, {"together": [[DO]]}), "stages[0].steps[1].together"),
        (a_tree(WAIT_UNTIL, {"together": [[DO], []]}), "stages[0].steps[1].together[1]"),
        (
            a_tree({"repeat": {"max": 51, "until": "$CTX.a == 1", "steps": [DO]}}),
            "stages[0].steps[0].repeat.max",
        ),
        (a_tree({"repeat": {"max": 2, "steps": [DO]}}), "stages[0].steps[0].repeat.until"),
        (a_tree(stages=[]), "stages"),
        (a_tree(stages=[{"name": "Fetch order", "steps": []}]), "stages[0].steps"),
        (a_tree(stages=[{"name": "Fetch order", "steps": [DO], "note": "x"}]), "stages[0].note"),
        (
            a_tree(
                stages=[a_stage(f"Stage {chr(97 + n // 26)}{chr(97 + n % 26)}") for n in range(65)]
            ),
            "stages",
        ),
        (a_tree(environment="staging"), "environment"),
        (a_tree(DO | {"id": "Fetch"}), "stages[0].steps[0].id"),
    ],
    ids=[
        "two-kinds",
        "no-kind",
        "not-a-mapping",
        "bad-action",
        "no-until",
        "every-too-short",
        "do-timeout",
        "if-does-not-parse",
        "empty-then",
        "empty-else",
        "id-on-if",
        "one-path",
        "empty-path",
        "repeat-max",
        "repeat-until",
        "no-stage",
        "empty-stage",
        "stage-key",
        "too-many-stages",
        "environment",
        "bad-id",
    ],
)
def test_names_the_tree_key_when_a_step_breaks_its_kind(content: dict[str, Any], key: str) -> None:
    assert keys_of(content) == [key]


def condition_of(length: int) -> str:
    """A one-atom If condition of exactly ``length`` characters."""
    return "$CTX.order_id == '" + "x" * (length - len("$CTX.order_id == ''")) + "'"


def test_refuses_the_condition_when_an_if_holds_more_than_its_characters() -> None:
    assert MAX_CONDITION_CHARS == 1024
    longest = a_tree(WAIT_UNTIL, {"if": condition_of(1024), "then": [DO], "else": [YOU]})
    assert parse_tree(longest)

    content = a_tree(WAIT_UNTIL, {"if": condition_of(1025), "then": [DO], "else": [YOU]})

    assert keys_of(content) == ["stages[0].steps[1].if"]
    assert any("at most 1,024 characters" in message for message in messages_of(content))


@pytest.mark.parametrize(
    ("content", "key"),
    [
        (
            a_tree(inputs={"order": {"required": True, "depends_on": ["x"]}}),
            "inputs.order.depends_on",
        ),
        (
            a_tree(DO | {"retry": {"max_attempts": 2, "trigger_rule": "all_done"}}),
            "stages[0].steps[0].retry.trigger_rule",
        ),
        (
            a_tree(YOU | {"decisions": [{"id": "go", "label": "Go", "depends_on": ["x"]}]}),
            "stages[0].steps[0].decisions[0].depends_on",
        ),
    ],
    ids=["input", "retry", "decision"],
)
def test_says_unknown_key_when_a_graph_key_is_inside_a_block_key(
    content: dict[str, Any], key: str
) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)

    # A refused item also fails its list's length check: only the item's message is read.
    assert {p.key: p.message for p in caught.value.problems}[key] == "unknown key"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (a_tree(nodes=[]), "a version-2 scenario holds stages, not nodes"),
        (a_tree(DO, WAIT_UNTIL | {"depends_on": ["x"]}), "a block runs after the one before it"),
        (a_tree(DO, WAIT_UNTIL | {"trigger_rule": "all_done"}), "no trigger_rule"),
        (a_tree(DO | {"you": "Approve."}), "a step holds exactly one of do, wait_until, you"),
        (a_tree(WAIT_UNTIL, {"if": NINE_ATOMS, "then": [DO]}), "at most 8 atoms"),
    ],
    ids=["nodes", "depends-on", "trigger-rule", "two-kinds", "atoms"],
)
def test_says_why_when_a_graph_key_or_a_kind_is_wrong(
    content: dict[str, Any], message: str
) -> None:
    assert any(message in found for found in messages_of(content))


@pytest.mark.parametrize("kind", [None, "workflow"])
def test_names_version_when_a_version_two_document_is_not_a_scenario(kind: str | None) -> None:
    content = a_tree()
    if kind is None:
        del content["kind"]
    else:
        content["kind"] = kind

    assert keys_of(content) == ["version"]


def test_keeps_the_graph_format_when_the_version_is_one() -> None:
    graph = {
        "version": 1,
        "kind": "scenario",
        "name": "demo",
        "revision": 1,
        "nodes": [{"id": "send", "type": "action", "action": "queue-send"}],
    }

    document = parse_workflow(graph)

    assert (document.version, [node.id for node in document.nodes]) == (1, ["send"])
    assert document.located([]) == []


@pytest.mark.parametrize("version", [1, True, "2"])
def test_names_version_when_the_block_map_reads_another_format(version: object) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_tree(a_tree(version=version))

    assert [(p.key, p.message) for p in caught.value.problems] == [
        ("version", "must be 2, a scenario's tree format")
    ]


@pytest.mark.parametrize("path", sorted(TREES.glob("*.yaml")), ids=lambda path: path.stem)
def test_dumps_the_keys_it_read_when_a_tree_is_written_back(path: Path) -> None:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))

    dumped = parse_tree(content).model_dump(mode="json", by_alias=True, exclude_unset=True)

    assert dumped == content


def test_keeps_schema_and_errors_when_models_are_built(characterization: Any) -> None:
    tree: TypeAdapter[Any] = TypeAdapter(TreeDocument)
    invalid = a_tree(DO, colour="red") | {"revision": 0, "stages": []}

    characterization.check(
        characterization.snapshot(
            tree_module,
            {"valid tree": (tree, a_tree(DO, WAIT_UNTIL, YOU)), "invalid tree": (tree, invalid)},
        )
    )
