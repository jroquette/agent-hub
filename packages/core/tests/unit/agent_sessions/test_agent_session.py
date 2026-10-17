import pytest
from pydantic import ValidationError

from agent_hub.core.agent_sessions.agent_session import (
    MAX_MESSAGE_SCREENSHOTS,
    TERMINAL_STATUSES,
    AgentSessionStatus,
    CreateAgentSession,
    PermissionDecision,
    Screenshot,
    SendMessage,
    SessionSettings,
    StartCloud,
)

WORKDIR_ID = "0123456789abcdef"
PNG_DATA = "iVBORw0KGgo="


def test_refuses_decision_when_always_without_suggestion() -> None:
    with pytest.raises(ValidationError):
        PermissionDecision(decision="always")


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "allow", "suggestion": 0},
        {"decision": "allow", "message": "why"},
        {"decision": "deny", "answers": {"Which?": "A"}},
        {"decision": "deny", "mode": "acceptEdits"},
        {"decision": "always", "suggestion": 0, "mode": "default"},
        {"decision": "allow", "mode": "bypassPermissions"},
        {"decision": "allow", "answers": {f"q{n}": "a" for n in range(17)}},
        {"decision": "deny", "message": "x" * 2049},
    ],
)
def test_refuses_decision_when_fields_do_not_fit(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PermissionDecision.model_validate(body)


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "allow"},
        {"decision": "deny", "message": "use the worktree"},
        {"decision": "always", "suggestion": 1},
        {"decision": "allow", "answers": {"Which database?": "SQLite"}},
        {"decision": "allow", "mode": "acceptEdits"},
    ],
)
def test_accepts_decision_when_fields_fit(body: dict[str, object]) -> None:
    assert PermissionDecision.model_validate(body).decision == body["decision"]


def test_refuses_create_when_workdir_is_a_path() -> None:
    with pytest.raises(ValidationError):
        CreateAgentSession(project="demo", workdir_id="../../etc")


def test_refuses_create_when_fork_without_resume() -> None:
    with pytest.raises(ValidationError):
        CreateAgentSession(project="demo", workdir_id=WORKDIR_ID, fork=True)


def test_refuses_settings_when_empty_or_bypass() -> None:
    with pytest.raises(ValidationError):
        SessionSettings()
    with pytest.raises(ValidationError):
        SessionSettings.model_validate({"mode": "bypassPermissions"})


def test_refuses_cloud_task_when_it_starts_with_dash() -> None:
    with pytest.raises(ValidationError):
        StartCloud(project="demo", workdir_id=WORKDIR_ID, task="--dangerously-skip-permissions")


def test_marks_ended_and_failed_terminal_when_statuses_listed() -> None:
    assert {AgentSessionStatus.ENDED, AgentSessionStatus.FAILED} == TERMINAL_STATUSES


def test_refuses_screenshot_when_prompt_missing() -> None:
    with pytest.raises(ValidationError):
        CreateAgentSession.model_validate(
            {
                "project": "demo",
                "workdir_id": WORKDIR_ID,
                "screenshot": {"media_type": "image/png", "data": PNG_DATA},
            }
        )


def test_refuses_screenshot_when_media_type_not_png() -> None:
    with pytest.raises(ValidationError):
        CreateAgentSession.model_validate(
            {
                "project": "demo",
                "workdir_id": WORKDIR_ID,
                "prompt": "What is on this screen?",
                "screenshot": {"media_type": "image/jpeg", "data": PNG_DATA},
            }
        )


def test_accepts_screenshot_when_prompt_given() -> None:
    request = CreateAgentSession.model_validate(
        {
            "project": "demo",
            "workdir_id": WORKDIR_ID,
            "prompt": "What is on this screen?",
            "screenshot": {"media_type": "image/png", "data": PNG_DATA},
        }
    )

    assert request.screenshot == Screenshot(media_type="image/png", data=PNG_DATA)


def test_shows_only_media_type_and_length_when_screenshot_repr_printed() -> None:
    data = "iVBORw0KGgoSECRETPIXELS"
    request = CreateAgentSession(
        project="demo",
        workdir_id=WORKDIR_ID,
        prompt="What is on this screen?",
        screenshot=Screenshot(media_type="image/png", data=data),
    )

    assert repr(request.screenshot) == f"Screenshot(media_type='image/png', chars={len(data)})"
    for shown in (repr(request), str(request)):
        assert data not in shown
        assert "SECRET" not in shown


def test_takes_up_to_max_images_when_message_parsed() -> None:
    shot = {"media_type": "image/png", "data": PNG_DATA}
    at_cap = SendMessage.model_validate(
        {"text": "Look.", "screenshots": [shot] * MAX_MESSAGE_SCREENSHOTS}
    )

    assert at_cap.screenshots is not None
    assert len(at_cap.screenshots) == MAX_MESSAGE_SCREENSHOTS
    assert SendMessage(text="Look.").screenshots is None
    for refused in ([shot] * (MAX_MESSAGE_SCREENSHOTS + 1), []):
        with pytest.raises(ValidationError):
            SendMessage.model_validate({"text": "Look.", "screenshots": refused})
