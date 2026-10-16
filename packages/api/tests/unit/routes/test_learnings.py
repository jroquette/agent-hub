from typing import Any

import pytest

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestConflictError,
    ChangeRequestFailedError,
    ChangeRequestTimeoutError,
)
from agent_hub.core.learnings.learning import LearningStatus
from agent_hub.core.learnings.learning_ports import HubReadOnlyError, LearningConflictError
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.testing.read_model_builders import a_learning, a_learning_detail

# The learning actions need the server's own Origin (S7, local_security.py).
OWN_ORIGIN = {"Origin": "http://127.0.0.1:7420"}


def test_maps_filters_when_learnings_listed(wired: Any) -> None:
    wired.events.learnings.append(a_learning())

    response = wired.client.get("/api/v1/learnings", params={"status": "proposed"})

    assert response.json()["items"] == [a_learning().model_dump(mode="json")]
    assert wired.events.calls == [
        ("list_learnings", LearningFilter(status=LearningStatus.PROPOSED))
    ]


def test_maps_learning_when_learning_requested(wired: Any) -> None:
    wired.events.learnings.append(a_learning())

    assert wired.client.get("/api/v1/learnings/learning-1").json()["id"] == "learning-1"


def test_reads_detail_from_events_when_learning_reads_not_wired(wired: Any) -> None:
    wired.events.learnings.append(a_learning())

    document = wired.client.get("/api/v1/learnings/learning-1").json()

    assert (document["note"], document["suggested_target"]) == (None, "learnings/")
    assert document["target_choices"] == []


def test_reads_through_learning_reads_when_wired(wired: Any) -> None:
    wired.learning_reads.details.append(a_learning_detail())
    wired.wire(learning_reads=wired.learning_reads)

    document = wired.client.get("/api/v1/learnings/learning-1").json()
    listed = wired.client.get("/api/v1/learnings").json()

    assert document["note"]["path"] == "_inbox/testing-x.md"
    assert listed["items"][0]["summary"] == "Run `make migrations` before the PR."
    assert wired.events.calls == []


def test_answers_not_implemented_when_decisions_not_wired(wired: Any) -> None:
    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept", json={"target": "learnings/"}, headers=OWN_ORIGIN
    )

    assert response.status_code == 501


def test_opens_pull_request_when_learning_accepted(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept", json={"target": "learnings/"}, headers=OWN_ORIGIN
    )

    assert response.status_code == 201
    assert response.json()["state"] == "accepted_pr_open"
    assert wired.decisions.calls == [("accept", "learning-1", "learnings/")]


def test_passes_edited_body_when_learning_accepted_with_edit(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept",
        json={"target": "learnings/", "note_body": "# X\n\nEdited.\n"},
        headers=OWN_ORIGIN,
    )

    assert response.status_code == 201
    assert wired.decisions.note_bodies == ["# X\n\nEdited.\n"]


def test_rejects_empty_edited_body_when_learning_accepted(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept",
        json={"target": "learnings/", "note_body": ""},
        headers=OWN_ORIGIN,
    )

    assert response.status_code == 422
    assert wired.decisions.calls == []


def test_opens_pull_request_when_learning_rejected(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/reject", json={"reason": "  Duplicate  "}, headers=OWN_ORIGIN
    )

    assert response.status_code == 201
    assert response.json()["state"] == "rejected_pr_open"
    assert wired.decisions.calls == [("reject", "learning-1", "Duplicate")]


def test_rejects_body_when_reason_empty(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/reject", json={"reason": " "}, headers=OWN_ORIGIN
    )

    assert response.status_code == 422
    assert wired.decisions.calls == []


def test_answers_not_found_when_learning_unknown(wired: Any) -> None:
    assert wired.client.get("/api/v1/learnings/nope").status_code == 404


def test_rejects_body_when_target_too_long(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept", json={"target": "a" * 201}, headers=OWN_ORIGIN
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/target"
    assert wired.decisions.calls == []


def test_rejects_body_when_reason_too_long(wired: Any) -> None:
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/reject", json={"reason": "x" * 301}, headers=OWN_ORIGIN
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["pointer"] == "/reason"


def test_answers_conflict_with_pull_request_when_learning_already_decided(wired: Any) -> None:
    wired.decisions.failure = LearningConflictError(
        "Learning already accepted, PR open", pr_url="https://github.com/acme/demo-hub/pull/7"
    )
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept", json={"target": "learnings/"}, headers=OWN_ORIGIN
    )

    assert response.status_code == 409
    assert response.json()["reason"] == "Learning already accepted, PR open"
    assert response.json()["pr_url"] == "https://github.com/acme/demo-hub/pull/7"


def test_answers_conflict_when_hub_read_only(wired: Any) -> None:
    wired.decisions.failure = HubReadOnlyError("Hub is read-only here")
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/reject", json={"reason": "Duplicate"}, headers=OWN_ORIGIN
    )

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["reason"]) == (
        "hub_read_only",
        "Hub is read-only here",
    )


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ChangeRequestConflictError("Destination exists: brain/learnings/x.md"), 409),
        (ChangeRequestFailedError(step="push"), 502),
        (ChangeRequestTimeoutError(), 504),
    ],
)
def test_maps_change_request_error_when_pull_request_not_opened(
    wired: Any, error: Exception, status: int
) -> None:
    wired.decisions.failure = error
    wired.wire(learning_decisions=wired.decisions)

    response = wired.client.post(
        "/api/v1/learnings/learning-1/accept", json={"target": "learnings/"}, headers=OWN_ORIGIN
    )

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
