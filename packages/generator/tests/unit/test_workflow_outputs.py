"""Output contracts: JSON Schema 2020-12 behind core's ``OutputValidator`` port."""

import socket
from typing import Any, NoReturn

import pytest

from agent_hub.core.workflows.document import WorkflowProblem, parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.ports import OutputValidator
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs, output_format_problems

REPORT = {
    "type": "object",
    "properties": {
        "delivery": {"type": "string", "enum": ["delivered", "failed"]},
        "count": {"type": "integer"},
    },
    "required": ["delivery"],
    "additionalProperties": False,
}


def a_validator() -> OutputValidator:
    return JsonSchemaOutputs()


def failure_of(schema: dict[str, Any], value: Any) -> NodeFailedError:
    with pytest.raises(NodeFailedError) as raised:
        a_validator().check(schema, value)
    return raised.value


def test_accepts_value_when_it_matches_the_schema() -> None:
    a_validator().check(REPORT, {"delivery": "delivered", "count": 2})


def test_fails_output_contract_when_value_breaks_the_schema() -> None:
    failure = failure_of(REPORT, {"delivery": "shipped"})

    assert failure.kind == "output_contract"
    assert failure.detail == "delivery: breaks 'enum'"


def test_names_every_broken_rule_when_value_breaks_several() -> None:
    failure = failure_of(REPORT, {"count": "2", "extra": 1})

    assert (
        failure.detail
        == "$: breaks 'additionalProperties'; $: breaks 'required'; count: breaks 'type'"
    )


def test_keeps_the_value_out_of_the_detail_when_value_breaks() -> None:
    secret = "ghp_" + "x" * 36

    failure = failure_of({"type": "integer"}, secret)

    assert secret not in failure.detail
    assert failure.detail == "$: breaks 'type'"


def test_refuses_a_boolean_when_schema_wants_an_integer() -> None:
    assert failure_of({"type": "integer"}, value=True).kind == "output_contract"


def test_follows_the_current_draft_when_schema_uses_prefix_items() -> None:
    schema = {"type": "array", "prefixItems": [{"type": "string"}], "items": False}

    a_validator().check(schema, ["one"])
    assert failure_of(schema, ["one", "two"]).kind == "output_contract"


def test_reads_format_as_an_annotation_when_schema_declares_one() -> None:
    a_validator().check({"type": "string", "format": "email"}, "not an email")


def test_fails_config_when_schema_does_not_compile() -> None:
    failure = failure_of({"type": "nope"}, "x")

    assert failure.kind == "config"
    assert failure.detail.startswith("the output_format is not a valid JSON Schema")


def test_fails_config_without_fetching_when_schema_refers_to_another_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[object] = []

    def record(*args: object, **kwargs: object) -> NoReturn:
        lookups.append(args[0])
        raise OSError

    monkeypatch.setattr(socket, "getaddrinfo", record)

    failure = failure_of({"$ref": "https://example.com/schema.json"}, "x")

    assert lookups == []
    assert failure.kind == "config"
    assert failure.detail.endswith('"https://example.com/schema.json"')


def test_lists_no_problem_when_schema_compiles() -> None:
    assert a_validator().schema_problems(REPORT) == ()


def test_lists_a_problem_when_schema_does_not_compile() -> None:
    problems = a_validator().schema_problems({"properties": {"a": {"minLength": -1}}})

    assert problems == ("properties.a.minLength: breaks 'minimum'",)


def test_lists_a_problem_when_schema_nests_too_deep() -> None:
    schema: dict[str, Any] = {"type": "object"}
    for _ in range(5000):
        schema = {"properties": {"a": schema}}

    assert a_validator().schema_problems(schema) == ("the schema nests too deeply",)


def a_document(output_formats: list[dict[str, Any] | None]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for index, output_format in enumerate(output_formats):
        node: dict[str, Any] = {"id": f"n{index}", "type": "shell", "command": ["true"]}
        if output_format is not None:
            node["output_format"] = output_format
        nodes.append(node)
    return {"version": 1, "name": "demo", "revision": 1, "nodes": nodes}


def test_names_each_bad_output_format_when_document_checked() -> None:
    document = parse_workflow(a_document([REPORT, None, {"type": 3}, {"required": "a"}]))

    problems = output_format_problems(document, a_validator())

    assert problems == [
        WorkflowProblem(("nodes", 2, "output_format", "type"), "breaks 'anyOf'"),
        WorkflowProblem(("nodes", 3, "output_format", "required"), "breaks 'type'"),
    ]


def test_finds_no_problem_when_every_output_format_compiles() -> None:
    document = parse_workflow(a_document([REPORT, None]))

    assert output_format_problems(document, a_validator()) == []
