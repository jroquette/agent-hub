"""The node models: one ``type`` each, carrying only that type's keys (AC-213.1)."""

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    FromBinding,
    HaltNode,
    LoopNode,
    Node,
    Retry,
    ScriptNode,
    ShellNode,
    WaitNode,
)

NODE: TypeAdapter[Any] = TypeAdapter(Node)
DONE_SCHEMA = {"type": "object", "properties": {"done": {"type": "boolean"}}, "required": ["done"]}


def errors_of(raw: dict[str, object]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        NODE.validate_python(raw)
    return [(tuple(error["loc"]), error["msg"]) for error in caught.value.errors()]


@pytest.mark.parametrize(
    ("raw", "model"),
    [
        ({"id": "plan", "type": "agent", "prompt": "Plan $INPUTS.issue"}, AgentNode),
        ({"id": "plan", "type": "agent", "prompt_file": "plan.md"}, AgentNode),
        ({"id": "test", "type": "shell", "command": ["make", "check"]}, ShellNode),
        ({"id": "lint", "type": "script", "runtime": "python", "script": "lint.py"}, ScriptNode),
        (
            {"id": "fix", "type": "loop", "prompt": "Fix", "max_iterations": 3, "until": "DONE"},
            LoopNode,
        ),
        ({"id": "ok", "type": "approval", "message": "Ship it?"}, ApprovalNode),
        ({"id": "stop", "type": "halt", "reason": "Nothing to do"}, HaltNode),
        ({"id": "nap", "type": "wait", "duration": "7d"}, WaitNode),
        ({"id": "nap", "type": "wait", "until": "2026-10-16T09:00:00+02:00"}, WaitNode),
        ({"id": "nap", "type": "wait", "until": "$INPUTS.at"}, WaitNode),
        ({"id": "ask", "type": "wait", "attention": "Colour?"}, WaitNode),
        (
            {
                "id": "ask",
                "type": "wait",
                "attention": "Pick",
                "options": [{"id": "a", "label": "A"}],
            },
            WaitNode,
        ),
    ],
)
def test_loads_the_type_model_when_node_has_its_keys(raw: dict[str, object], model: type) -> None:
    assert isinstance(NODE.validate_python(raw), model)


def test_applies_contract_defaults_when_optional_keys_absent() -> None:
    node = NODE.validate_python({"id": "plan", "type": "agent", "prompt": "Plan"})

    assert node.trigger_rule == "all_success"
    assert node.model == "medium"
    assert (node.limits.max_turns, node.limits.max_cost_usd) == (40, 3.0)
    assert node.context == "fresh"
    assert node.retry is None
    assert node.mutates_checkout is True


def test_defaults_to_approve_and_reject_when_approval_lists_no_decisions() -> None:
    node = NODE.validate_python({"id": "ok", "type": "approval", "message": "Ship?"})

    assert [decision.id for decision in node.decisions] == ["approve", "reject"]


def test_retries_once_on_transient_after_two_seconds_when_retry_is_empty() -> None:
    assert Retry() == Retry(max_attempts=1, delay="2s", on_error="transient")


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "a", "type": "shell", "command": ["true"], "prompt": "x"},
        {"id": "a", "type": "halt", "reason": "x", "retry": {}},
        {"id": "a", "type": "approval", "message": "x", "timeout": "1m"},
        {"id": "a", "type": "shell", "command": ["true"], "retry": {"max_attempts": 1, "x": 1}},
        {"id": "a", "type": "shell", "command": ["true"], "with": {}},
    ],
)
def test_refuses_key_when_it_is_not_in_the_type_row(raw: dict[str, object]) -> None:
    assert any(message == "Extra inputs are not permitted" for _, message in errors_of(raw))


@pytest.mark.parametrize("node_type", ["include", "loop_group", "bash"])
def test_refuses_type_when_it_is_not_a_node_type_yet(node_type: str) -> None:
    [(loc, message)] = errors_of({"id": "a", "type": node_type})

    assert loc == ()
    assert "does not match any of the expected tags" in message


@pytest.mark.parametrize("node_id", ["Plan", "1st", "a.b", "a__b", "", "a b"])
def test_refuses_id_when_it_breaks_the_id_pattern(node_id: str) -> None:
    raw = {"id": node_id, "type": "halt", "reason": "x"}

    assert [loc for loc, _ in errors_of(raw)] == [("halt", "id")]


@pytest.mark.parametrize("extra", [{}, {"prompt": "a", "prompt_file": "a.md"}])
def test_needs_exactly_one_prompt_when_node_is_an_agent(extra: dict[str, object]) -> None:
    [(_, message)] = errors_of({"id": "a", "type": "agent", **extra})

    assert "exactly one of 'prompt' or 'prompt_file'" in message


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret.md", "a/../../b.md", "a\\b.md"])
def test_refuses_pack_path_when_it_leaves_the_pack(path: str) -> None:
    [(loc, _)] = errors_of({"id": "a", "type": "agent", "prompt_file": path})

    assert loc == ("agent", "prompt_file")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("prompt", "   "),
        ("timeout", "10"),
        ("timeout", "0s"),
        ("trigger_rule", "any"),
        ("depends_on", ["a", "a"]),
        ("retry", {"max_attempts": 6}),
        ("retry", {"on_error": "never"}),
        ("limits", {"max_cost_usd": 0}),
        ("model", "huge"),
        ("always_run", "yes"),
    ],
)
def test_refuses_value_when_it_breaks_the_key_rule(key: str, value: object) -> None:
    raw = {"id": "b", "type": "agent", "prompt": "Plan", key: value}

    assert errors_of(raw)[0][0][:2] == ("agent", key)


def test_reads_mapping_as_binding_when_it_holds_from() -> None:
    node = NODE.validate_python(
        {
            "id": "b",
            "type": "agent",
            "prompt": "x",
            "with": {"plan": {"from": "$a.output.steps"}, "raw": {"text": "kept"}},
        }
    )

    assert node.with_["plan"] == FromBinding.model_validate({"from": "$a.output.steps"})
    assert node.with_["raw"] == {"text": "kept"}


@pytest.mark.parametrize(
    "binding", [{"from": "$a.output", "if_skiped": ""}, {"from": "not a reference"}]
)
def test_refuses_binding_when_it_is_malformed(binding: dict[str, object]) -> None:
    raw = {"id": "b", "type": "agent", "prompt": "x", "with": {"plan": binding}}

    [(loc, message)] = errors_of(raw)
    assert loc == ("agent", "with", "plan")
    assert "takes only 'from'" in message


def test_refuses_env_when_node_is_a_hub_step() -> None:
    raw = {"id": "pr", "type": "shell", "command": ["hub", "step", "pr"], "env": {"A": "1"}}

    [(_, message)] = errors_of(raw)
    assert "hub step node takes no 'env'" in message


def test_needs_an_until_channel_when_node_is_a_loop() -> None:
    [(_, message)] = errors_of({"id": "l", "type": "loop", "prompt": "x", "max_iterations": 2})

    assert "at least one of 'until', 'until_field' or 'until_bash'" in message


@pytest.mark.parametrize(
    "output_format",
    [None, {"type": "object", "properties": {"done": {"type": "string"}}, "required": ["done"]}],
)
def test_refuses_until_field_when_it_is_not_a_required_boolean(
    output_format: dict[str, object] | None,
) -> None:
    raw = {
        "id": "l",
        "type": "loop",
        "prompt": "x",
        "max_iterations": 2,
        "until_field": "done",
        "output_format": output_format,
    }

    [(_, message)] = errors_of(raw)
    assert "'until_field' must be a required boolean" in message


def test_loads_loop_when_until_field_is_a_required_boolean() -> None:
    raw = {
        "id": "l",
        "type": "loop",
        "prompt": "x",
        "max_iterations": 50,
        "until_field": "done",
        "output_format": DONE_SCHEMA,
    }

    assert NODE.validate_python(raw).until_field == "done"


def test_refuses_decisions_when_an_id_repeats() -> None:
    decisions = [{"id": "ok", "label": "OK"}, {"id": "ok", "label": "Fine"}]
    raw = {"id": "g", "type": "approval", "message": "x", "decisions": decisions}

    assert [loc for loc, _ in errors_of(raw)] == [("approval", "decisions")]


@pytest.mark.parametrize("cost", [float("nan"), float("inf"), True, "3"])
def test_refuses_cost_when_it_is_not_a_finite_number(cost: object) -> None:
    raw = {"id": "b", "type": "agent", "prompt": "x", "limits": {"max_cost_usd": cost}}

    assert [loc for loc, _ in errors_of(raw)] == [("agent", "limits", "max_cost_usd")]


def test_keeps_mappings_read_only_when_node_is_loaded() -> None:
    agent = NODE.validate_python(
        {"id": "b", "type": "agent", "prompt": "x", "with": {"a": 1}, "output_format": DONE_SCHEMA}
    )
    shell = NODE.validate_python({"id": "s", "type": "shell", "command": ["x"], "env": {"A": "1"}})

    for mapping in (agent.with_, agent.output_format, shell.env):
        with pytest.raises(TypeError):
            mapping["new"] = 1  # type: ignore[index]
    assert agent.model_dump(by_alias=True)["with"] == {"a": 1}
    assert '"env":{"A":"1"}' in shell.model_dump_json()


@pytest.mark.parametrize("duration", ["7d", "168h", "10080m", "604800s", "1s"])
def test_accepts_duration_when_it_is_at_most_seven_days(duration: str) -> None:
    raw = {"id": "a", "type": "shell", "command": ["x"], "timeout": duration}

    assert NODE.validate_python(raw | {"retry": {"delay": duration}}).timeout == duration


@pytest.mark.parametrize("duration", ["8d", "169h", "10081m", "604801s", "1000000s", "999999999d"])
@pytest.mark.parametrize("key", ["timeout", "retry"])
def test_refuses_duration_when_it_is_over_seven_days(duration: str, key: str) -> None:
    value: object = duration if key == "timeout" else {"delay": duration}
    raw = {"id": "a", "type": "shell", "command": ["x"], key: value}

    [(loc, message)] = errors_of(raw)
    assert loc == (("shell", "timeout") if key == "timeout" else ("shell", "retry", "delay"))
    assert "at most 7 days" in message


@pytest.mark.parametrize(
    "keys",
    [
        {},
        {"duration": "1h", "attention": "Now?"},
        {"until": "2026-10-16T09:00:00"},
        {"until": "tomorrow"},
        {"until": "$a.output and more"},
        {"duration": "1h", "options": [{"id": "a", "label": "A"}]},
        {"attention": "Pick", "options": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]},
        {"duration": "8d"},
    ],
)
def test_refuses_the_wait_when_its_condition_is_missing_or_malformed(
    keys: dict[str, object],
) -> None:
    assert errors_of({"id": "nap", "type": "wait"} | keys)
