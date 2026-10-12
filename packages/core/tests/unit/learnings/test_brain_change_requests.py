import pytest
from pydantic import ValidationError

from agent_hub.core.errors import AgentHubError
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    ChangeRequestConflictError,
    ChangeRequestError,
    ChangeRequestFailedError,
    ChangeRequestResult,
    ChangeRequestTimeoutError,
    CommitAuthor,
    RefspecRefusedError,
)


def a_change(**overrides: object) -> BrainChange:
    fields: dict[str, object] = {
        "hub_path": "/home/demo/demo-hub",
        "hub_repo": "acme/demo-hub",
        "default_branch": "main",
        "action": "accept",
        "note": "_inbox/testing-x.md",
        "destination": "learnings/testing-x.md",
        "frontmatter": {"status": "accepted", "last_verified": "2026-10-12"},
        "author": CommitAuthor(name="Demo Owner", email="owner@example.com"),
        "branch": "demo/learning-accept-testing-x",
        "title": "Accept learning: testing x",
        "body": "Moves brain/_inbox/testing-x.md to brain/learnings/testing-x.md.",
        "commit_message": "docs(brain): accept learning testing-x",
    }
    return BrainChange.model_validate(fields | overrides)


def test_keeps_fields_when_change_built() -> None:
    change = a_change()

    assert change.destination == "learnings/testing-x.md"
    assert change.author.email == "owner@example.com"


def test_rejects_change_when_branch_is_default() -> None:
    with pytest.raises(ValidationError, match="default branch"):
        a_change(branch="main")


def test_rejects_change_when_action_unknown() -> None:
    with pytest.raises(ValidationError, match="action"):
        a_change(action="snooze")


def test_names_reason_and_step_when_errors_raised() -> None:
    conflict = ChangeRequestConflictError("Note not on origin/main")
    failed = ChangeRequestFailedError(step="push")
    refused = RefspecRefusedError("Refusing to push the default branch")

    for error in (conflict, failed, ChangeRequestTimeoutError(), refused):
        assert isinstance(error, ChangeRequestError)
        assert isinstance(error, AgentHubError)
    assert conflict.reason == "Note not on origin/main"
    assert failed.step == "push"
    assert "push" in str(failed)
    assert refused.reason == "Refusing to push the default branch"


def test_keeps_url_when_result_built() -> None:
    result = ChangeRequestResult(
        pr_url="https://github.com/acme/demo-hub/pull/3", branch="demo/learning-accept-x"
    )

    assert result.branch == "demo/learning-accept-x"
