from agent_hub.core.learnings.fold_learning import fold_learnings
from agent_hub.core.learnings.learning import LearningStatus
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_scenarios import (
    SCENARIO_START,
    as_stored,
    learning_events,
    shuffled,
    stored_event_id,
)


def test_proposes_learning_when_only_proposal_exists() -> None:
    learning = fold_learnings(as_stored(learning_events()))["learning-1"]

    assert learning.status == LearningStatus.PROPOSED
    assert learning.text == "Run the migrations check before the PR"
    assert (learning.target.kind, learning.target.path) == (
        "team",
        "brain/learnings/gotchas/testing.md",
    )
    assert learning.source_session_id == "session-1"
    assert learning.source_event_id == stored_event_id(1)
    assert learning.proposed_at == SCENARIO_START
    assert learning.author == "main"


def test_accepts_when_accept_precedes_reject_in_source_order() -> None:
    events = learning_events(decisions=[("learning.rejected", 5), ("learning.accepted", 2)])

    learning = fold_learnings(as_stored(events))["learning-1"]

    assert learning.status == LearningStatus.ACCEPTED
    assert learning.brain_path == "brain/learnings/gotchas/testing.md"
    assert learning.commit == "abc1234"
    assert learning.decided_by == "owner"
    assert learning.decided_at is not None
    assert learning.rejection_reason is None


def test_rejects_when_reject_precedes_accept_in_source_order() -> None:
    events = learning_events(decisions=[("learning.accepted", 9), ("learning.rejected", 1)])

    learning = fold_learnings(as_stored(events))["learning-1"]

    assert learning.status == LearningStatus.REJECTED
    assert learning.rejection_reason == "already documented"


def test_applies_early_accept_when_proposal_arrives_after_it() -> None:
    proposal, accept = learning_events(decisions=[("learning.accepted", 3)])

    assert fold_learnings(as_stored([accept])) == {}
    learning = fold_learnings(as_stored([accept, proposal]))["learning-1"]
    assert learning.status == LearningStatus.ACCEPTED


def test_folds_same_learnings_when_events_shuffled() -> None:
    events = as_stored(
        [
            *learning_events(decisions=[("learning.rejected", 4), ("learning.accepted", 2)]),
            *learning_events("learning-2"),
        ]
    )
    expected = fold_learnings(events)

    for seed in range(30):
        assert fold_learnings(shuffled([*events, events[0]], seed)) == expected
    assert sorted(expected) == ["learning-1", "learning-2"]


def test_matches_decision_by_path_when_proposal_came_from_inbox_write() -> None:
    inbox = an_event(
        type="learning.proposed",
        timestamp=SCENARIO_START,
        payload={"text": "Tests need docker", "target": "brain/_inbox/2026-10-09-docker.md"},
    )
    accept = an_event(
        type="learning.accepted",
        timestamp=SCENARIO_START.replace(hour=15),
        payload={"brain_path": "brain/_inbox/2026-10-09-docker.md"},
    )

    learnings = fold_learnings(as_stored([inbox, accept]))

    assert list(learnings) == ["brain/_inbox/2026-10-09-docker.md"]
    learning = learnings["brain/_inbox/2026-10-09-docker.md"]
    assert learning.status == LearningStatus.ACCEPTED
    assert learning.target.kind == "team"


def test_infers_target_kind_when_target_is_a_path() -> None:
    def kind_of(target: str) -> str | None:
        event = an_event(
            type="learning.proposed", payload={"proposal": "p", "text": "t", "target": target}
        )
        return fold_learnings(as_stored([event]))["p"].target.kind

    assert kind_of("demo-api/AGENTS.md") == "repo"
    assert kind_of("brain/auto/workspace/notes.md") == "personal"
    assert kind_of("somewhere/else.md") is None
