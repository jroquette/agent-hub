from typing import Any

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.readmodels.filters import ApprovalFilter
from agent_hub.core.testing.read_model_builders import an_approval


def test_maps_filters_when_approvals_listed(wired: Any) -> None:
    wired.events.approvals.append(an_approval())

    response = wired.client.get(
        "/api/v1/approvals", params={"kind": "guard_ask", "status": "all", "limit": "10"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [an_approval().model_dump(mode="json")]
    assert wired.events.calls == [
        ("list_approvals", ApprovalFilter(kind=ApprovalKind.GUARD_ASK, status="all", limit=10))
    ]


def test_maps_approval_when_approval_requested(wired: Any) -> None:
    wired.events.approvals.append(an_approval())

    response = wired.client.get("/api/v1/approvals/toolu_demo_1")

    assert response.json()["how_to_decide"] == an_approval().how_to_decide


def test_answers_not_found_when_approval_unknown(wired: Any) -> None:
    assert wired.client.get("/api/v1/approvals/nope").status_code == 404
