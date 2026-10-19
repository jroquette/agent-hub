"""An action document and its load errors, each at its key (AC-350.6)."""

from typing import Any

import pytest

from agent_hub.core.scenarios.action_document import ActionDocument, parse_action
from agent_hub.core.workflows.document import WorkflowLoadError


def an_action(**overrides: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "name": "send-queue-message",
        "description": "Send one message to a queue",
        "effect": "write",
        "runtime": "python",
        "script": "scripts/send_queue_message.py",
        "timeout": "1m",
        "inputs": {
            "queue": {"type": "service", "required": True},
            "message_type": {"type": "string", "required": True},
            "ref": {"type": "string"},
        },
        "output_format": {
            "type": "object",
            "required": ["message_id"],
            "properties": {"message_id": {"type": "string"}},
        },
    }
    return document | overrides


def without(key: str) -> dict[str, Any]:
    document = an_action()
    del document[key]
    return document


def test_loads_action_when_document_valid() -> None:
    action = parse_action(an_action())

    assert isinstance(action, ActionDocument)
    assert (action.name, action.effect, action.runtime) == ("send-queue-message", "write", "python")
    assert (action.script, action.timeout) == ("scripts/send_queue_message.py", "1m")
    assert {name: spec.type for name, spec in action.inputs.items()} == {
        "queue": "service",
        "message_type": "string",
        "ref": "string",
    }
    assert action.inputs["queue"].required is True
    assert action.output_format["required"] == ["message_id"]
    assert parse_action(without("timeout")).timeout == "5m"


@pytest.mark.parametrize(
    ("document", "key"),
    [
        pytest.param(an_action(effect="delete"), "effect", id="effect_delete"),
        pytest.param(without("effect"), "effect", id="effect_missing"),
        pytest.param(an_action(script="../x.py"), "script", id="script_parent"),
        pytest.param(
            an_action(inputs={"target": {"type": "url"}}), "inputs.target.type", id="input_url"
        ),
        pytest.param(without("output_format"), "output_format", id="output_format_missing"),
        pytest.param(an_action(auto_approve=True), "auto_approve", id="unknown_key"),
    ],
)
def test_reports_one_problem_when_action_document_fault_given(
    document: dict[str, Any], key: str
) -> None:
    # AC-350.6: each fault gives one load error, at its key.
    with pytest.raises(WorkflowLoadError) as caught:
        parse_action(document)

    assert [problem.key for problem in caught.value.problems] == [key]
