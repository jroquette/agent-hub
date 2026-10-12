from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.learnings.learning import Learning, LearningState
from agent_hub.core.learnings.learning_ports import LearningHub
from agent_hub.core.learnings.read_learnings import (
    HUB_NOT_REGISTERED,
    ReadLearnings,
    UnavailableHub,
)
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.readmodels.filters import LearningFilter
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.fakes import InMemoryEventStore
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader

HUB_PATH = "/home/demo/demo-hub"
NOTE_PATH = "brain/_inbox/testing-x.md"
NOTE = "_inbox/testing-x.md"
NOTE_TEXT = (
    "---\n"
    "type: learning-proposal\n"
    "status: proposed\n"
    "---\n"
    "# Testing x\n"
    "\n"
    "Run `make migrations`\n"
    "before the PR.\n"
    "\n"
    "Second paragraph.\n"
)
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
PR_URL = "https://github.com/acme/demo-hub/pull/4"


def _hub() -> LearningHub:
    return LearningHub(
        project="demo",
        path=HUB_PATH,
        hub_repo="acme/demo-hub",
        default_branch="main",
        branch_prefix="demo/",
        author=CommitAuthor(name="Demo Owner", email="owner@example.com"),
    )


def _proposal(note_path: str = NOTE_PATH, proposal: str = "toolu_1") -> Event:
    return an_event(
        type="learning.proposed",
        timestamp=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        source="transcript",
        payload={"proposal": proposal, "text": "Testing x", "target": note_path},
    )


def _app_decision(decision: str, *, brain_path: str) -> Event:
    return an_event(
        type=f"learning.{decision}",
        timestamp=datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
        session="control-plane",
        source="control_plane",
        source_id=f"learning:toolu_1:{decision}",
        agent="you",
        payload={
            "proposal": "toolu_1",
            "brain_path": brain_path,
            "pr_url": PR_URL,
            "branch": f"demo/learning-{decision.removesuffix('ed')}-testing-x",
            "state": f"{decision}_pr_open",
        },
    )


def _reads(
    brain: dict[str, bytes],
    events: Sequence[Event] = (),
    *,
    links: frozenset[str] = frozenset(),
    hub: LearningHub | UnavailableHub | None = None,
    unavailable: str | None = None,
) -> ReadLearnings:
    store = InMemoryEventStore()
    store.append(list(events) or [_proposal()])
    files = FakeHubFileReader({HUB_PATH: FakeHub(brain=brain, brain_links=links)})
    found = _hub() if hub is None else hub
    return ReadLearnings(
        FoldedEventReadModels(store, now=lambda: NOW),
        files,
        hub_of=lambda project: found,
        availability=lambda hub_path: unavailable,
    )


def _listed(reads: ReadLearnings) -> Learning:
    [learning] = reads.list_learnings(LearningFilter()).items
    return learning


def test_returns_note_when_inbox_note_exists() -> None:
    reads = _reads({NOTE: NOTE_TEXT.encode()})

    detail = reads.get_learning("toolu_1")

    assert detail.note is not None
    assert detail.note.path == NOTE
    assert detail.note.frontmatter == {"type": "learning-proposal", "status": "proposed"}
    assert detail.note.markdown.startswith("# Testing x\n")
    assert detail.note.size == len(NOTE_TEXT.encode())
    assert (detail.note_path, detail.state) == (NOTE_PATH, LearningState.PROPOSED)
    assert (detail.note_unavailable, detail.actions_unavailable) == (None, None)
    assert detail.source_session_id == "session-1"


def test_summarizes_first_paragraph_when_listed() -> None:
    learning = _listed(_reads({NOTE: NOTE_TEXT.encode()}))

    assert learning.summary == "Run `make migrations` before the PR."
    assert learning.state == LearningState.PROPOSED
    assert learning.note_unavailable is None


def test_omits_summary_when_note_over_summary_bound() -> None:
    long_note = NOTE_TEXT + "x" * 20_000

    learning = _listed(_reads({NOTE: long_note.encode()}))

    assert (learning.summary, learning.note_unavailable) == (None, None)


@dataclass(frozen=True, kw_only=True)
class Unreadable:
    note_path: str = NOTE_PATH
    brain: dict[str, bytes] = field(default_factory=dict)
    links: frozenset[str] = frozenset()
    hub: UnavailableHub | None = None
    reason: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(Unreadable(reason="Note not in the hub checkout"), id="missing"),
        pytest.param(
            Unreadable(note_path="brain/learnings/x.md", reason="Note outside brain/_inbox/"),
            id="outside",
        ),
        pytest.param(
            Unreadable(
                note_path="brain/_inbox/_archive/testing-x.md",
                brain={"_inbox/_archive/testing-x.md": b"# x\n"},
                reason="Note outside brain/_inbox/",
            ),
            id="archived",
        ),
        pytest.param(
            Unreadable(
                brain={NOTE: b"# x\n"}, links=frozenset({NOTE}), reason="Not a regular file"
            ),
            id="link",
        ),
        pytest.param(
            Unreadable(
                note_path="brain/_inbox/testing-x.txt",
                brain={"_inbox/testing-x.txt": b"x"},
                reason="Only .md notes are served",
            ),
            id="not_md",
        ),
        pytest.param(
            Unreadable(brain={NOTE: b"x" * 300_000}, reason="Note too large"), id="too_large"
        ),
        pytest.param(
            Unreadable(
                brain={NOTE: NOTE_TEXT.encode()},
                hub=UnavailableHub(reason=HUB_NOT_REGISTERED),
                reason=HUB_NOT_REGISTERED,
            ),
            id="hub_unregistered",
        ),
    ],
)
def test_reports_unavailable_when_note_unreadable(case: Unreadable) -> None:
    reads = _reads(case.brain, [_proposal(case.note_path)], links=case.links, hub=case.hub)

    learning = _listed(reads)
    detail = reads.get_learning("toolu_1")

    assert (learning.note_unavailable, learning.summary) == (case.reason, None)
    assert (detail.note_unavailable, detail.note) == (case.reason, None)
    assert learning.actions_unavailable == case.reason


def test_reports_unavailable_when_note_path_unknown() -> None:
    proposal = an_event(
        type="learning.proposed", payload={"proposal": "toolu_1", "text": "Testing x"}
    )

    learning = _listed(_reads({}, [proposal]))

    assert (learning.note_path, learning.note_unavailable) == (None, "Note outside brain/_inbox/")


def test_reports_actions_unavailable_when_hub_unregistered() -> None:
    reads = _reads({}, hub=UnavailableHub(reason=HUB_NOT_REGISTERED))

    learning = _listed(reads)

    assert learning.actions_unavailable == HUB_NOT_REGISTERED
    assert learning.state == LearningState.PROPOSED


def test_reads_note_when_hub_unusable_for_actions() -> None:
    reads = _reads(
        {NOTE: NOTE_TEXT.encode()},
        hub=UnavailableHub(reason="Hub remote is not on GitHub", path=HUB_PATH),
    )

    learning = _listed(reads)

    assert learning.actions_unavailable == "Hub remote is not on GitHub"
    assert (learning.note_unavailable, learning.summary) == (
        None,
        "Run `make migrations` before the PR.",
    )


def test_reports_actions_unavailable_when_hub_read_only() -> None:
    reads = _reads({NOTE: NOTE_TEXT.encode()}, unavailable="Hub is read-only here")

    assert _listed(reads).actions_unavailable == "Hub is read-only here"
    assert reads.get_learning("toolu_1").actions_unavailable == "Hub is read-only here"


@dataclass(frozen=True, kw_only=True)
class Decided:
    decision: str
    brain_path: str
    brain: dict[str, bytes]
    state: LearningState


ACCEPTED_TO = "brain/learnings/testing-x.md"
ARCHIVED_TO = "brain/_inbox/_archive/testing-x.md"


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            Decided(
                decision="accepted",
                brain_path=ACCEPTED_TO,
                brain={NOTE: NOTE_TEXT.encode()},
                state=LearningState.ACCEPTED_PR_OPEN,
            ),
            id="accepted_pr_open",
        ),
        pytest.param(
            Decided(
                decision="accepted",
                brain_path=ACCEPTED_TO,
                brain={"learnings/testing-x.md": NOTE_TEXT.encode()},
                state=LearningState.IN_BRAIN,
            ),
            id="in_brain",
        ),
        pytest.param(
            Decided(
                decision="rejected",
                brain_path=ARCHIVED_TO,
                brain={NOTE: NOTE_TEXT.encode()},
                state=LearningState.REJECTED_PR_OPEN,
            ),
            id="rejected_pr_open",
        ),
        pytest.param(
            Decided(
                decision="rejected",
                brain_path=ARCHIVED_TO,
                brain={"_inbox/_archive/testing-x.md": NOTE_TEXT.encode()},
                state=LearningState.ARCHIVED,
            ),
            id="archived",
        ),
    ],
)
def test_infers_state_when_note_at_target(case: Decided) -> None:
    events = [_proposal(), _app_decision(case.decision, brain_path=case.brain_path)]
    reads = _reads(case.brain, events)

    learning = _listed(reads)
    detail = reads.get_learning("toolu_1")

    assert (learning.state, detail.state) == (case.state, case.state)
    assert learning.pr_url == PR_URL
    assert learning.note_unavailable is None
    assert learning.summary == "Run `make migrations` before the PR."
    assert learning.actions_unavailable is None


def test_defaults_target_when_frontmatter_has_none() -> None:
    brain = {
        NOTE: NOTE_TEXT.encode(),
        "playbooks/cloud.md": b"# Cloud\n",
        "decisions/index.md": b"# Decisions\n",
        "auto/workspace/me.md": b"# Me\n",
        "now.md": b"# Now\n",
    }

    detail = _reads(brain).get_learning("toolu_1")

    assert detail.suggested_target == "learnings/"
    assert detail.target_choices == ("learnings/", "playbooks/")


@pytest.mark.parametrize(
    ("target", "brain", "suggested"),
    [
        pytest.param("brain/learnings/gotchas/", {}, "learnings/gotchas/", id="folder"),
        pytest.param(
            "brain/learnings/gotchas/testing.md", {}, "learnings/gotchas/testing.md", id="new_note"
        ),
        pytest.param(
            "brain/learnings/gotchas/testing.md",
            {"learnings/gotchas/testing.md": b"# Testing\n"},
            "learnings/gotchas/",
            id="existing_note",
        ),
        pytest.param("brain/decisions/0001.md", {}, "learnings/", id="refused"),
        pytest.param("demo-api/AGENTS.md", {}, "learnings/", id="repo"),
    ],
)
def test_suggests_frontmatter_target_when_note_names_one(
    target: str, brain: dict[str, bytes], suggested: str
) -> None:
    text = NOTE_TEXT.replace("status: proposed\n", f"status: proposed\ntarget: {target}\n")

    detail = _reads({NOTE: text.encode(), **brain}).get_learning("toolu_1")

    assert detail.suggested_target == suggested
