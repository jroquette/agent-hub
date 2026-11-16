import pytest
from pydantic import ValidationError

from agent_hub.api.schemas import (
    AcceptLearningBody,
    HookAccepted,
    HubCreate,
    ProblemDetails,
    RejectLearningBody,
)


def test_counts_when_hook_accepted_built() -> None:
    assert HookAccepted(appended=1, duplicates=0).model_dump() == {"appended": 1, "duplicates": 0}


def test_rejects_hub_create_when_path_empty() -> None:
    with pytest.raises(ValidationError, match="path"):
        HubCreate(path="")


def test_allows_extension_members_when_problem_parsed() -> None:
    problem = ProblemDetails.model_validate(
        {"title": "Invalid", "status": 422, "errors": [{"pointer": "/a", "message": "required"}]}
    )

    assert problem.type == "about:blank"
    assert problem.model_extra == {"errors": [{"pointer": "/a", "message": "required"}]}


@pytest.mark.parametrize("target", ["", "x" * 201])
def test_rejects_accept_body_when_target_out_of_bounds(target: str) -> None:
    with pytest.raises(ValidationError, match="target"):
        AcceptLearningBody(target=target)


@pytest.mark.parametrize("reason", ["", "   ", "x" * 301])
def test_rejects_reject_body_when_reason_out_of_bounds(reason: str) -> None:
    with pytest.raises(ValidationError, match="reason"):
        RejectLearningBody(reason=reason)


def test_strips_reason_when_reject_body_parsed() -> None:
    assert RejectLearningBody(reason="  Duplicate  ").reason == "Duplicate"


def test_refuses_unknown_field_when_accept_body_parsed() -> None:
    with pytest.raises(ValidationError, match="extra"):
        AcceptLearningBody.model_validate({"target": "learnings/", "force": True})
