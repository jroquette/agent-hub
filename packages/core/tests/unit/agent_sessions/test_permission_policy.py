from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import PermissionDecision
from agent_hub.core.agent_sessions.driver import Allow, Deny
from agent_hub.core.agent_sessions.errors import InvalidDecisionError
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.permission_policy import (
    CLOSED_MESSAGE,
    TIMEOUT_MESSAGE,
    closed_answer,
    deadline,
    expired,
    timeout_answer,
    validate,
)
from agent_hub.core.testing.read_model_builders import (
    SUGGESTIONS,
    a_permission_request,
    an_open_permission,
)

ASKED = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
QUESTIONS: dict[str, JsonValue] = {
    "questions": [{"question": "Which runner?", "options": [{"label": "pytest"}]}]
}


def test_allows_once_when_decision_allow() -> None:
    answer = validate(a_permission_request(), PermissionDecision(decision="allow"))

    assert answer == Allow()


def test_denies_with_message_when_decision_deny() -> None:
    answer = validate(
        a_permission_request(), PermissionDecision(decision="deny", message="not now")
    )

    assert answer == Deny(message="not now")


def test_allows_suggestion_when_destination_local_settings() -> None:
    answer = validate(a_permission_request(), PermissionDecision(decision="always", suggestion=0))

    assert answer == Allow(updated_permissions=(SUGGESTIONS[0],))


def test_refuses_always_when_destination_session() -> None:
    with pytest.raises(InvalidDecisionError):
        validate(a_permission_request(), PermissionDecision(decision="always", suggestion=1))


def test_refuses_always_when_suggestion_not_offered() -> None:
    with pytest.raises(InvalidDecisionError):
        validate(a_permission_request(), PermissionDecision(decision="always", suggestion=7))


def test_refuses_answers_when_tool_request() -> None:
    with pytest.raises(InvalidDecisionError):
        validate(
            a_permission_request(),
            PermissionDecision(decision="allow", answers={"Which runner?": "pytest"}),
        )


def test_puts_answers_in_input_when_ask_user_question_answered() -> None:
    request = a_permission_request(
        tool="AskUserQuestion", input=QUESTIONS, request_kind="ask_user_question", suggestions=()
    )

    answer = validate(
        request, PermissionDecision(decision="allow", answers={"Which runner?": "pytest"})
    )

    assert answer == Allow(updated_input=QUESTIONS | {"answers": {"Which runner?": "pytest"}})


def test_refuses_mode_when_not_plan_approval() -> None:
    with pytest.raises(InvalidDecisionError):
        validate(a_permission_request(), PermissionDecision(decision="allow", mode="acceptEdits"))


def test_allows_plan_with_mode_when_plan_approval() -> None:
    request = a_permission_request(
        tool="ExitPlanMode",
        input={"plan": "1. Add the test"},
        request_kind="plan_approval",
        suggestions=(),
    )

    answer = validate(request, PermissionDecision(decision="allow", mode="acceptEdits"))

    assert answer == Allow()


def test_sets_deadline_when_request_asked() -> None:
    limits = SessionLimits(permission_timeout_seconds=90)

    assert deadline(ASKED, limits) == ASKED + timedelta(seconds=90)


def test_denies_when_deadline_passes() -> None:
    open_request = an_open_permission(asked_at=ASKED, deadline_at=ASKED + timedelta(seconds=1))

    assert not expired(open_request, ASKED + timedelta(milliseconds=999))
    assert expired(open_request, ASKED + timedelta(seconds=1))
    assert timeout_answer() == Deny(message=TIMEOUT_MESSAGE)


def test_denies_with_closed_message_when_session_closes() -> None:
    assert closed_answer() == Deny(message=CLOSED_MESSAGE)
