"""The cloud-session routes over a recording ``CloudSessionCommands`` (RT): what each route
passes on and the problem each cloud error becomes. The launcher is tested in claude_sessions."""

from typing import Any

import pytest

from agent_hub.core.agent_sessions.agent_session import CloudMessage, StartCloud
from agent_hub.core.agent_sessions.errors import (
    CloudFailedError,
    CloudTimeoutError,
    CloudUnavailableError,
    InvalidWorkdirError,
)
from agent_hub.core.testing.read_model_builders import WORKDIR_ID, a_cloud_session

CLOUD = "/api/v1/agent-sessions/cloud"
FOLLOW_UP = f"{CLOUD}/cse_01synthetic/messages"
TASK = {"project": "demo", "workdir_id": WORKDIR_ID, "task": "Upgrade the linter"}
PROBLEM = "urn:agent-hub:problem:agent-session-"
GUIDANCE = "Start it with claude --cloud in a terminal, then open its claude.ai/code link."


def test_answers_link_and_teleport_command_when_start_called(recorded_app: Any) -> None:
    response = recorded_app.client.post(CLOUD, json=TASK)

    assert response.status_code == 201, response.text
    assert response.json() == a_cloud_session().model_dump(mode="json")
    assert recorded_app.cloud.calls == [("start", (StartCloud.model_validate(TASK),))]


@pytest.mark.parametrize("task", ["", "--dangerously-skip-permissions", "-p x"])
def test_refuses_start_when_task_empty_or_flag(recorded_app: Any, task: str) -> None:
    response = recorded_app.client.post(CLOUD, json=TASK | {"task": task})

    assert response.status_code == 422, response.text
    assert recorded_app.cloud.calls == []


def test_passes_cloud_id_and_text_when_followup_url_posted(recorded_app: Any) -> None:
    response = recorded_app.client.post(FOLLOW_UP, json={"text": "Also the docs"})

    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("https://claude.ai/code/")
    assert recorded_app.cloud.calls == [
        ("follow_up", ("cse_01synthetic", CloudMessage(text="Also the docs")))
    ]


def test_refuses_followup_url_when_cloud_id_malformed(recorded_app: Any) -> None:
    response = recorded_app.client.post(
        f"{CLOUD}/cse%2F..%2Fx/messages", json={"text": "Also the docs"}
    )

    assert response.status_code in {400, 404}, response.text
    assert recorded_app.cloud.calls == []


def test_answers_501_with_guidance_when_followup_url_capability_missing(
    recorded_app: Any,
) -> None:
    recorded_app.cloud.failures["follow_up"] = CloudUnavailableError(GUIDANCE)

    response = recorded_app.client.post(FOLLOW_UP, json={"text": "Also the docs"})

    assert response.status_code == 501, response.text
    document = response.json()
    assert document["type"] == f"{PROBLEM}cloud-unavailable"
    assert (document["guidance"], document["detail"]) == (GUIDANCE, GUIDANCE)


def test_answers_502_naming_step_when_start_output_unreadable(recorded_app: Any) -> None:
    recorded_app.cloud.failures["start"] = CloudFailedError("parse")

    response = recorded_app.client.post(CLOUD, json=TASK)

    assert response.status_code == 502, response.text
    document = response.json()
    assert (document["type"], document["step"]) == (f"{PROBLEM}cloud-failed", "parse")
    assert TASK["task"] not in response.text


def test_answers_timeout_when_start_passes_deadline(recorded_app: Any) -> None:
    recorded_app.cloud.failures["start"] = CloudTimeoutError(seconds=60)

    response = recorded_app.client.post(CLOUD, json=TASK)

    assert response.status_code == 504, response.text
    assert response.json()["type"] == f"{PROBLEM}cloud-timeout"
    assert response.json()["seconds"] == 60


def test_answers_invalid_workdir_when_start_workdir_unknown(recorded_app: Any) -> None:
    recorded_app.cloud.failures["start"] = InvalidWorkdirError(WORKDIR_ID)

    response = recorded_app.client.post(CLOUD, json=TASK)

    assert response.status_code == 422, response.text
    assert response.json()["type"] == f"{PROBLEM}invalid-workdir"


def test_lists_cloud_starts_when_project_given(recorded_app: Any) -> None:
    response = recorded_app.client.get(CLOUD, params={"project": "demo"})

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["cloud_id"] == "cse_01synthetic"
    assert recorded_app.cloud.calls == [("list_cloud", ("demo",))]
