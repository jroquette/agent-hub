import pytest
from pydantic import ValidationError

from agent_hub.api.schemas import HookAccepted, HubCreate, ProblemDetails


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
