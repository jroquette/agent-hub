import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.core.agent_sessions.driver import (
    MODEL_ALIASES,
    DriverAnswer,
    DriverEvent,
    PermissionMode,
    PermissionRequest,
    StartSpec,
    TextDelta,
    TurnResult,
    is_valid_model,
)

EVENTS: TypeAdapter[DriverEvent] = TypeAdapter(DriverEvent)
ANSWERS: TypeAdapter[DriverAnswer] = TypeAdapter(DriverAnswer)
MODES: TypeAdapter[PermissionMode] = TypeAdapter(PermissionMode)


def test_refuses_event_when_kind_unknown() -> None:
    with pytest.raises(ValidationError):
        EVENTS.validate_python({"kind": "shell.output", "text": "x"})


def test_parses_event_when_kind_known() -> None:
    event = EVENTS.validate_python({"kind": "text.delta", "block": 0, "index": 2, "text": "Hi"})

    assert event == TextDelta(block=0, index=2, text="Hi")


def test_refuses_event_when_field_unknown() -> None:
    with pytest.raises(ValidationError):
        EVENTS.validate_python({"kind": "thinking", "text": "x", "shell": "rm -rf /"})


def test_keeps_request_kind_apart_when_permission_request_parsed() -> None:
    event = EVENTS.validate_python(
        {
            "kind": "permission.request",
            "request_id": "req-1",
            "tool": "AskUserQuestion",
            "input": {"questions": []},
            "suggestions": [],
            "request_kind": "ask_user_question",
        }
    )

    assert isinstance(event, PermissionRequest)
    assert event.kind == "permission.request"
    assert event.request_kind == "ask_user_question"


@pytest.mark.parametrize(
    "model", [*MODEL_ALIASES, "claude-sonnet-4-5", "claude-opus-4-1[1m]", "x.y_z"]
)
def test_accepts_model_when_alias_or_pattern(model: str) -> None:
    assert is_valid_model(model)
    assert StartSpec(cwd="/hub", mode="default", model=model).model == model


@pytest.mark.parametrize(
    "model", ["", "opus sonnet", "--dangerously-skip-permissions" + "x" * 64, "a/b", "m;rm", "é"]
)
def test_refuses_model_when_pattern_fails(model: str) -> None:
    assert not is_valid_model(model)
    with pytest.raises(ValidationError):
        StartSpec(cwd="/hub", mode="default", model=model)


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "auto", "manual"])
def test_refuses_bypass_when_mode_parsed(mode: str) -> None:
    with pytest.raises(ValidationError):
        MODES.validate_python(mode)
    with pytest.raises(ValidationError):
        StartSpec(cwd="/hub", mode=mode)  # type: ignore[arg-type]


def test_refuses_fork_when_no_resume_given() -> None:
    with pytest.raises(ValidationError):
        StartSpec(cwd="/hub", mode="default", fork=True)


def test_parses_answer_when_decision_given() -> None:
    allow = ANSWERS.validate_python({"decision": "allow"})
    deny = ANSWERS.validate_python({"decision": "deny", "message": "not now"})

    assert allow.decision == "allow"
    assert deny.decision == "deny"


def test_carries_cost_as_money_when_result_dumped() -> None:
    result = TurnResult(subtype="success", terminal_reason="completed", cost_usd="0.01234")

    assert result.model_dump(mode="json")["cost_usd"] == "0.0123"
