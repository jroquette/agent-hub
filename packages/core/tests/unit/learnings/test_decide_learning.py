from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agent_hub.core.events.event import Event, EventSource, EventType
from agent_hub.core.events.event_store import AppendResult
from agent_hub.core.ingestion.ingest_events import IngestEvents
from agent_hub.core.learnings.brain_change_requests import (
    BrainChange,
    ChangeRequestFailedError,
    ChangeRequestResult,
    CommitAuthor,
)
from agent_hub.core.learnings.decide_learning import DecideLearning
from agent_hub.core.learnings.learning import LearningState
from agent_hub.core.learnings.learning_ports import (
    HubReadOnlyError,
    LearningConflictError,
    LearningHub,
)
from agent_hub.core.learnings.read_learnings import (
    HUB_NOT_REGISTERED,
    ReadLearnings,
    UnavailableHub,
)
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.testing.brain_fakes import (
    DEMO_HUB_PATH,
    FakeBrainOrigin,
    InMemoryBrainChangeRequests,
)
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader

NOW = datetime(2026, 10, 12, 12, 30, tzinfo=UTC)
# Synthetic token shape: the r1 "github token" rule recognises it; it opens nothing.
FAKE_TOKEN = "ghp_" + "A1b2C3d4" * 4
NOTE_TEXT = (
    "---\n"
    "type: learning-proposal\n"
    "status: proposed\n"
    "---\n"
    "# Testing x\n"
    "\n"
    "Run `make migrations` before the PR.\n"
)


def _proposal(name: str = "testing-x", proposal: str = "toolu_1") -> Event:
    return an_event(
        type="learning.proposed",
        timestamp=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        source="transcript",
        payload={"proposal": proposal, "text": "Testing x", "target": f"brain/_inbox/{name}.md"},
    )


def _hub() -> LearningHub:
    return LearningHub(
        project="demo",
        path=DEMO_HUB_PATH,
        hub_repo="acme/demo-hub",
        default_branch="main",
        branch_prefix="demo/",
        author=CommitAuthor(name="Demo Owner", email="owner@example.com"),
    )


@dataclass(kw_only=True)
class Setup:
    """A hub with inbox notes in its checkout and on ``origin``, and the use case over them."""

    notes: dict[str, str] = field(default_factory=lambda: {"testing-x": NOTE_TEXT})
    hub: LearningHub | UnavailableHub = field(default_factory=_hub)
    store: InMemoryEventStore = field(default_factory=InMemoryEventStore)
    origin: FakeBrainOrigin = field(default_factory=FakeBrainOrigin)
    changes: InMemoryBrainChangeRequests | None = None

    def __post_init__(self) -> None:
        for proposal, name in enumerate(self.notes, start=1):
            self.store.append([_proposal(name, f"toolu_{proposal}")])
            self.origin.put_on_default(f"brain/_inbox/{name}.md", self.notes[name])
        if self.changes is None:
            self.changes = InMemoryBrainChangeRequests(self.origin)

    @property
    def port(self) -> InMemoryBrainChangeRequests:
        assert self.changes is not None
        return self.changes

    def reads(self) -> ReadLearnings:
        brain = {f"_inbox/{name}.md": text.encode() for name, text in self.notes.items()}
        files = FakeHubFileReader({DEMO_HUB_PATH: FakeHub(brain=brain)})
        return ReadLearnings(
            FoldedEventReadModels(self.store, now=lambda: NOW),
            files,
            hub_of=lambda project: self.hub,
            availability=self.port.availability,
        )

    def decide(self) -> DecideLearning:
        return DecideLearning(
            self.reads(),
            IngestEvents(self.store),
            self.port,
            hub_of=lambda project: self.hub,
            today=lambda: NOW,
        )

    def decisions(self) -> list[Event]:
        return [
            event
            for event in self.store.read_all()
            if event.type in {EventType.LEARNING_ACCEPTED, EventType.LEARNING_REJECTED}
        ]


def test_opens_change_and_stores_event_when_accepted() -> None:
    setup = Setup()

    result = setup.decide().accept("toolu_1", target="learnings/gotchas/")

    branch = "demo/learning-accept-testing-x"
    assert result.state == LearningState.ACCEPTED_PR_OPEN
    assert (result.pr_url, result.branch) == ("https://github.com/acme/demo-hub/pull/1", branch)
    [change] = setup.port.calls
    assert (change.note, change.destination) == (
        "_inbox/testing-x.md",
        "learnings/gotchas/testing-x.md",
    )
    assert change.frontmatter == {"status": "accepted", "last_verified": "2026-10-12"}
    assert change.author.name == "Demo Owner"
    assert change.title == "Accept learning: Testing x"
    assert "Run `make migrations` before the PR." in change.body
    moved = setup.origin.file_on(branch, "brain/learnings/gotchas/testing-x.md")
    assert moved is not None
    assert "status: accepted" in moved
    [event] = setup.decisions()
    assert (event.type, event.source, event.session, event.agent) == (
        EventType.LEARNING_ACCEPTED,
        EventSource.CONTROL_PLANE,
        "control-plane",
        "you",
    )
    assert event.source_id == "learning:toolu_1:accepted"
    assert event.timestamp == NOW
    assert event.payload == {
        "proposal": "toolu_1",
        "brain_path": "brain/learnings/gotchas/testing-x.md",
        "pr_url": result.pr_url,
        "branch": branch,
        "state": "accepted_pr_open",
        "author": "you",
    }
    assert setup.reads().get_learning("toolu_1").state == LearningState.ACCEPTED_PR_OPEN


def test_writes_edited_body_and_names_edit_in_pr_when_accepted_with_edit() -> None:
    setup = Setup()

    setup.decide().accept(
        "toolu_1", target="learnings/gotchas/", note_body="# Testing x\n\nRun migrations first.\n"
    )

    [change] = setup.port.calls
    assert change.note_body == "# Testing x\n\nRun migrations first.\n"
    assert "The note was edited in agent-hub before it was accepted." in change.body
    assert "> Run migrations first." in change.body
    moved = setup.origin.file_on(change.branch, "brain/learnings/gotchas/testing-x.md")
    assert moved is not None
    assert moved.endswith("---\n# Testing x\n\nRun migrations first.\n")
    assert "status: accepted" in moved


@pytest.mark.parametrize("note_body", ["  \n", "x" * (256 * 1024 + 1)])
def test_refuses_edit_when_blank_or_too_large(note_body: str) -> None:
    setup = Setup()

    with pytest.raises(LearningConflictError):
        setup.decide().accept("toolu_1", target="learnings/", note_body=note_body)

    assert setup.port.calls == []
    assert setup.decisions() == []


def test_opens_change_and_stores_event_when_rejected() -> None:
    setup = Setup()

    result = setup.decide().reject("toolu_1", reason="  Already in\n the playbook  ")

    assert result.state == LearningState.REJECTED_PR_OPEN
    [change] = setup.port.calls
    assert change.destination == "_inbox/_archive/testing-x.md"
    assert change.frontmatter == {
        "status": "rejected",
        "rejected_reason": "Already in the playbook",
        "rejected_at": "2026-10-12",
    }
    assert change.title == "Reject learning: Testing x"
    assert "Already in the playbook" in change.body
    [event] = setup.decisions()
    assert event.source_id == "learning:toolu_1:rejected"
    assert event.payload["reason"] == "Already in the playbook"
    assert event.payload["state"] == "rejected_pr_open"


def test_refuses_when_learning_already_pr_open() -> None:
    setup = Setup()
    decide = setup.decide()
    opened = decide.accept("toolu_1", target="learnings/")

    with pytest.raises(LearningConflictError) as accepted:
        decide.accept("toolu_1", target="learnings/")
    with pytest.raises(LearningConflictError) as rejected:
        decide.reject("toolu_1", reason="changed my mind")

    assert accepted.value.reason == "Learning already accepted, PR open"
    assert (accepted.value.pr_url, rejected.value.pr_url) == (opened.pr_url, opened.pr_url)
    assert len(setup.port.calls) == 1
    assert len(setup.decisions()) == 1


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        pytest.param("decisions/", "A learning cannot be accepted into decisions/", id="decisions"),
        pytest.param("_inbox/", "A learning cannot be accepted into _inbox/", id="inbox"),
        pytest.param("../outside/", "Path has an empty, hidden or parent segment", id="outside"),
        pytest.param(
            "auto/workspace/", "brain/auto/ is personal memory and is never served", id="auto"
        ),
    ],
)
def test_refuses_when_destination_under_decisions(target: str, reason: str) -> None:
    setup = Setup()

    with pytest.raises(LearningConflictError) as refused:
        setup.decide().accept("toolu_1", target=target)

    assert refused.value.reason == reason
    assert setup.port.calls == []
    assert setup.decisions() == []


def test_stores_nothing_when_change_request_fails() -> None:
    setup = Setup()
    setup.port.fail_step = "gh pr create"

    with pytest.raises(ChangeRequestFailedError):
        setup.decide().accept("toolu_1", target="learnings/")

    assert setup.decisions() == []
    setup.port.fail_step = None
    result = setup.decide().accept("toolu_1", target="learnings/")
    assert result.state == LearningState.ACCEPTED_PR_OPEN
    assert len(setup.decisions()) == 1


def test_redacts_reason_and_body_when_note_holds_secret() -> None:
    text = NOTE_TEXT.replace("before the PR.", f"before the PR with token {FAKE_TOKEN}.")
    setup = Setup(notes={"testing-x": text})

    setup.decide().reject("toolu_1", reason=f"leaks {FAKE_TOKEN}")

    [change] = setup.port.calls
    [pull] = setup.origin.pull_requests()
    [event] = setup.decisions()
    texts = [
        change.title,
        change.body,
        change.commit_message,
        change.frontmatter["rejected_reason"],
        pull.title,
        pull.body,
        str(event.payload),
    ]
    assert all(FAKE_TOKEN not in value and "ghp_" not in value for value in texts)
    assert "[redacted: github token]" in change.body
    assert change.frontmatter["rejected_reason"] == "leaks [redacted: github token]"
    assert event.payload["reason"] == "leaks [redacted: github token]"


@pytest.mark.parametrize(
    ("hub", "unavailable", "reason"),
    [
        pytest.param(None, "Hub is read-only here", "Hub is read-only here", id="read_only"),
        pytest.param(
            UnavailableHub(reason=HUB_NOT_REGISTERED), None, HUB_NOT_REGISTERED, id="unregistered"
        ),
        pytest.param(
            UnavailableHub(reason="Hub remote is not on GitHub", path=DEMO_HUB_PATH),
            None,
            "Hub remote is not on GitHub",
            id="not_github",
        ),
    ],
)
def test_refuses_when_hub_read_only(
    hub: UnavailableHub | None, unavailable: str | None, reason: str
) -> None:
    origin = FakeBrainOrigin()
    setup = Setup(
        hub=_hub() if hub is None else hub,
        origin=origin,
        changes=InMemoryBrainChangeRequests(origin, unavailable=unavailable),
    )

    with pytest.raises(HubReadOnlyError) as refused:
        setup.decide().accept("toolu_1", target="learnings/")

    assert refused.value.reason == reason
    assert setup.port.calls == []
    assert setup.decisions() == []


def test_refuses_when_note_not_readable_in_checkout() -> None:
    setup = Setup()
    setup.store.append([_proposal("gone", "toolu_9")])

    with pytest.raises(LearningConflictError) as refused:
        setup.decide().accept("toolu_9", target="learnings/")

    assert refused.value.reason == "Note not in the hub checkout"
    assert setup.port.calls == []


class _ReentrantChanges(InMemoryBrainChangeRequests):
    """Starts a second action on the same hub while the first one is opening its PR."""

    decide: DecideLearning | None = None
    refused: LearningConflictError | None = None

    def accept(self, change: BrainChange) -> ChangeRequestResult:
        assert self.decide is not None
        try:
            self.decide.reject("toolu_2", reason="duplicate")
        except LearningConflictError as error:
            self.refused = error
        return super().accept(change)


def test_refuses_second_action_when_one_running() -> None:
    origin = FakeBrainOrigin()
    changes = _ReentrantChanges(origin)
    setup = Setup(
        notes={"testing-x": NOTE_TEXT, "other": NOTE_TEXT}, origin=origin, changes=changes
    )
    decide = setup.decide()
    changes.decide = decide

    decide.accept("toolu_1", target="learnings/")

    assert changes.refused is not None
    assert changes.refused.reason == "Another learning action is running for this hub"
    assert [call.action for call in changes.calls] == ["accept"]
    assert len(setup.decisions()) == 1
    assert decide.reject("toolu_2", reason="duplicate").state == LearningState.REJECTED_PR_OPEN


class _FlakyIngest(IngestEvents):
    """Fails the first ``execute`` (the store was down after the PR opened)."""

    failures: int = 1

    def execute(self, events: Sequence[Event]) -> AppendResult:
        if self.failures:
            self.failures -= 1
            raise OSError("event store unavailable")
        return super().execute(events)


def test_adopts_opened_pull_request_when_retried_after_ingest_failed() -> None:
    setup = Setup()
    decide = DecideLearning(
        setup.reads(),
        _FlakyIngest(setup.store),
        setup.port,
        hub_of=lambda project: setup.hub,
        today=lambda: NOW,
    )

    with pytest.raises(OSError, match="event store unavailable"):
        decide.accept("toolu_1", target="learnings/")
    assert setup.decisions() == []

    result = decide.accept("toolu_1", target="learnings/")

    assert result.state == LearningState.ACCEPTED_PR_OPEN
    assert result.pr_url == "https://github.com/acme/demo-hub/pull/1"
    assert len(setup.origin.pull_requests()) == 1
    [event] = setup.decisions()
    assert event.payload["pr_url"] == result.pr_url
