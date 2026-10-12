import pytest

from agent_hub.core.learnings.brain_change_requests import (
    ChangeRequestConflictError,
    ChangeRequestFailedError,
)
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests
from agent_hub.core.testing.builders import a_brain_change

NOTE = "brain/_inbox/testing-x.md"


def test_reports_reason_when_actions_unavailable() -> None:
    changes = InMemoryBrainChangeRequests(FakeBrainOrigin(), unavailable="Hub is read-only here")

    assert changes.availability("/home/demo/demo-hub") == "Hub is read-only here"


def test_pushes_nothing_when_step_fails() -> None:
    origin = FakeBrainOrigin()
    origin.put_on_default(NOTE, "# x\n")
    changes = InMemoryBrainChangeRequests(origin, fail_step="gh pr create")

    with pytest.raises(ChangeRequestFailedError, match="gh pr create"):
        changes.accept(a_brain_change())

    assert origin.branch_names() == frozenset({"main"})
    assert origin.pull_requests() == ()


def test_refuses_change_when_unavailable() -> None:
    origin = FakeBrainOrigin()
    origin.put_on_default(NOTE, "# x\n")
    changes = InMemoryBrainChangeRequests(origin, unavailable="Hub is read-only here")

    with pytest.raises(ChangeRequestConflictError, match="read-only"):
        changes.accept(a_brain_change())


def test_counts_calls_when_change_requested() -> None:
    origin = FakeBrainOrigin()
    origin.put_on_default(NOTE, "# x\n")
    changes = InMemoryBrainChangeRequests(origin)

    changes.accept(a_brain_change())

    assert [change.action for change in changes.calls] == ["accept"]
