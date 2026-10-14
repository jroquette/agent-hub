"""The document's top level and its load errors, each at a key path (AC-213.1)."""

import pytest

from agent_hub.core.workflows.document import (
    WorkflowLoadError,
    WorkflowProblem,
    parse_workflow,
)
from agent_hub.core.workflows.nodes import ShellNode


def a_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "version": 1,
        "name": "lint-and-test",
        "revision": 1,
        "nodes": [{"id": "test", "type": "shell", "command": ["make", "check"]}],
    }
    return document | overrides


def problems_of(content: object) -> list[tuple[str, str]]:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(content)
    return [(problem.key, problem.message) for problem in caught.value.problems]


def test_returns_the_frozen_document_when_content_matches_the_model() -> None:
    document = parse_workflow(a_document(description="Lint, then test."))

    assert document.name == "lint-and-test"
    assert isinstance(document.nodes[0], ShellNode)
    assert document.inputs == {}
    assert (document.returns, document.outcome_field) == (None, None)


def test_names_the_key_when_top_level_key_is_unknown() -> None:
    assert problems_of(a_document(effort="high")) == [("effort", "unknown key")]


def test_drops_the_type_tag_from_key_when_node_key_is_unknown() -> None:
    nodes = [{"id": "test", "type": "shell", "command": ["true"], "promt": "x"}]

    assert problems_of(a_document(nodes=nodes)) == [("nodes[0].promt", "unknown key")]


def test_lists_every_problem_when_several_nodes_are_wrong() -> None:
    nodes = [
        {"id": "a", "type": "shell"},
        {"id": "b", "type": "halt"},
        "not a node",
    ]

    assert [key for key, _ in problems_of(a_document(nodes=nodes))] == [
        "nodes[0].command",
        "nodes[1].reason",
        "nodes[2]",
    ]


@pytest.mark.parametrize("content", [[], "text", None, 3])
def test_refuses_content_when_it_is_not_a_mapping(content: object) -> None:
    assert problems_of(content) == [("$", "must be a mapping")]


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"version": 2}, "version"),
        ({"version": True}, "version"),
        ({"name": "Lint_Test"}, "name"),
        ({"revision": 0}, "revision"),
        ({"nodes": []}, "nodes"),
        ({"inputs": {"Issue": {}}}, "inputs.Issue"),
        ({"returns": "a__b"}, "returns"),
    ],
)
def test_names_the_key_when_top_level_value_is_wrong(
    overrides: dict[str, object], key: str
) -> None:
    assert problems_of(a_document(**overrides))[0][0] == key


@pytest.mark.parametrize("missing", ["version", "name", "revision", "nodes"])
def test_names_the_key_when_a_required_key_is_missing(missing: str) -> None:
    content = a_document()
    del content[missing]

    assert problems_of(content) == [(missing, "Field required")]


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"required": True, "default": "x"}, "a required input takes no 'default'"),
        ({"type": "integer", "default": "3"}, "'default' must be of type integer"),
        ({"type": "integer", "default": True}, "'default' must be of type integer"),
        ({"type": "boolean", "default": 1}, "'default' must be of type boolean"),
    ],
)
def test_refuses_input_when_default_breaks_its_rule(spec: dict[str, object], message: str) -> None:
    assert problems_of(a_document(inputs={"issue": spec})) == [("inputs.issue", message)]


@pytest.mark.parametrize(
    "spec",
    [{}, {"type": "number", "default": 2}, {"type": "boolean", "default": False}],
)
def test_loads_input_when_default_fits_its_type(spec: dict[str, object]) -> None:
    assert "issue" in parse_workflow(a_document(inputs={"issue": spec})).inputs


def test_names_every_problem_when_the_error_is_printed() -> None:
    error = WorkflowLoadError(
        [WorkflowProblem(("nodes", 0, "id"), "bad"), WorkflowProblem((), "x")]
    )

    assert str(error) == "nodes[0].id: bad; $: x"


@pytest.mark.parametrize("node", [{"id": "a"}, {"id": "a", "type": "wait"}])
def test_points_at_the_type_key_when_node_type_is_missing_or_unknown(
    node: dict[str, object],
) -> None:
    [(key, _)] = problems_of(a_document(nodes=[node]))

    assert key == "nodes[0].type"


@pytest.mark.parametrize(
    ("keys", "key"),
    [
        ({"context": "stale"}, "nodes[0].context"),
        ({"context": {"resume": "A"}}, "nodes[0].context.resume"),
        ({"limits": {"max_cost_usd": "x"}}, "nodes[0].limits.max_cost_usd"),
        ({"with": {"p": {"from": "x"}}}, "nodes[0].with.p"),
    ],
)
def test_names_document_keys_only_when_a_union_value_is_wrong(
    keys: dict[str, object], key: str
) -> None:
    node = {"id": "a", "type": "agent", "prompt": "x"} | keys

    assert {found for found, _ in problems_of(a_document(nodes=[node]))} == {key}


@pytest.mark.parametrize("default", [float("nan"), float("-inf")])
def test_refuses_input_default_when_it_is_not_finite(default: float) -> None:
    spec = {"type": "number", "default": default}

    assert [key for key, _ in problems_of(a_document(inputs={"n": spec}))] == ["inputs.n"]


def test_keeps_inputs_read_only_when_document_is_loaded() -> None:
    document = parse_workflow(a_document(inputs={"issue": {}}))

    with pytest.raises(TypeError):
        document.inputs["other"] = document.inputs["issue"]  # type: ignore[index]
    assert '"inputs":{"issue":' in document.model_dump_json()


@pytest.mark.parametrize(
    ("node", "message"),
    [
        (
            {"id": "pr", "type": "shell", "command": ["hub", "step", "pr"], "env": {"A": "1"}},
            "a hub step node takes no 'env': hub step scopes its own environment",
        ),
        ({"id": "a", "type": "agent"}, "give exactly one of 'prompt' or 'prompt_file'"),
        (
            {"id": "a", "type": "loop", "prompt": "x", "max_iterations": 2},
            "give at least one of 'until', 'until_field' or 'until_bash'",
        ),
    ],
)
def test_points_at_the_node_when_a_node_level_rule_fails(
    node: dict[str, object], message: str
) -> None:
    with pytest.raises(WorkflowLoadError) as caught:
        parse_workflow(a_document(nodes=[node]))

    assert [(p.loc, p.message) for p in caught.value.problems] == [(("nodes", 0), message)]
