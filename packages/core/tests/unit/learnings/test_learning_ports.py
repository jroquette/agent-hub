from agent_hub.core.errors import AgentHubError
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.learnings.learning_ports import (
    HubReadOnlyError,
    LearningConflictError,
    LearningHub,
)


def test_names_reason_and_pr_when_conflict_raised() -> None:
    error = LearningConflictError(
        "Learning already accepted, PR open", pr_url="https://github.com/acme/demo-hub/pull/3"
    )

    assert isinstance(error, AgentHubError)
    assert error.reason == "Learning already accepted, PR open"
    assert error.pr_url == "https://github.com/acme/demo-hub/pull/3"


def test_names_reason_when_hub_read_only() -> None:
    error = HubReadOnlyError("Hub is read-only here")

    assert (error.reason, str(error)) == ("Hub is read-only here", "Hub is read-only here")


def test_keeps_identity_when_hub_described() -> None:
    hub = LearningHub(
        project="demo",
        path="/home/demo/demo-hub",
        hub_repo="acme/demo-hub",
        default_branch="main",
        branch_prefix="demo/",
        author=CommitAuthor(name="Demo Owner", email="owner@example.com"),
    )

    assert (hub.default_branch, hub.author.name) == ("main", "Demo Owner")
