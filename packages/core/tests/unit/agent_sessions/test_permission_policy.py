from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from agent_hub.core.agent_sessions.agent_session import PermissionDecision
from agent_hub.core.agent_sessions.driver import Allow, Deny, PermissionSuggestion
from agent_hub.core.agent_sessions.errors import InvalidDecisionError
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.permission_policy import (
    CLOSED_MESSAGE,
    TIMEOUT_MESSAGE,
    closed_answer,
    deadline,
    expired,
    offered_suggestions,
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


LOCAL_ALLOW: dict[str, JsonValue] = {
    "type": "addRules",
    "rules": [{"toolName": "Bash", "ruleContent": "npm test"}],
    "behavior": "allow",
    "destination": "localSettings",
}
UNSAFE_RULES: list[dict[str, JsonValue]] = [
    {"type": "setMode", "mode": "bypassPermissions", "destination": "localSettings"},
    {"type": "addDirectories", "directories": ["/"], "destination": "localSettings"},
    LOCAL_ALLOW | {"behavior": "deny"},
    LOCAL_ALLOW | {"behavior": "ask"},
    LOCAL_ALLOW | {"type": "replaceRules"},
    LOCAL_ALLOW | {"destination": "userSettings"},
    {key: value for key, value in LOCAL_ALLOW.items() if key != "behavior"},
]


def _offering(rule: JsonValue, destination: str = "localSettings") -> PermissionSuggestion:
    return PermissionSuggestion(index=0, destination=destination, rule=rule)


@pytest.mark.parametrize("rule", UNSAFE_RULES)
def test_refuses_always_when_suggestion_not_local_allow_rule(rule: JsonValue) -> None:
    request = a_permission_request(suggestions=(_offering(rule),))

    with pytest.raises(InvalidDecisionError):
        validate(request, PermissionDecision(decision="always", suggestion=0))


def test_refuses_always_when_rule_not_object() -> None:
    request = a_permission_request(suggestions=(_offering("addRules"),))

    with pytest.raises(InvalidDecisionError):
        validate(request, PermissionDecision(decision="always", suggestion=0))


def test_keeps_only_local_allow_rules_when_suggestions_filtered() -> None:
    suggestions = (
        PermissionSuggestion(index=0, destination="localSettings", rule=UNSAFE_RULES[0]),
        PermissionSuggestion(index=1, destination="localSettings", rule=LOCAL_ALLOW),
        PermissionSuggestion(index=2, destination="localSettings", rule=UNSAFE_RULES[1]),
        PermissionSuggestion(index=3, destination="session", rule=LOCAL_ALLOW),
    )

    assert offered_suggestions(suggestions) == (suggestions[1],)
