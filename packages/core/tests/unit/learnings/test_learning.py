import json

import pytest
from pydantic import ValidationError

from agent_hub.core.brain.brain_note import BrainNote
from agent_hub.core.learnings.learning import (
    Learning,
    LearningActionResult,
    LearningDetail,
    LearningState,
)
from agent_hub.core.testing.read_model_builders import a_learning


def test_serializes_learning_when_dumped() -> None:
    document = json.loads(a_learning().model_dump_json())

    assert document["status"] == "proposed"
    assert document["target"] == {"kind": "team", "path": "brain/learnings/gotchas/testing.md"}
    assert document["proposed_at"] == "2026-10-09T14:00:00.123Z"


def test_rejects_learning_when_status_unknown() -> None:
    with pytest.raises(ValidationError, match="status"):
        a_learning(status="snoozed")


def test_serializes_clarity_fields_when_learning_read_with_note() -> None:
    learning = a_learning(
        note_path="brain/_inbox/testing-x.md",
        state=LearningState.ACCEPTED_PR_OPEN,
        summary="Run the migrations check before the PR.",
        pr_url="https://github.com/acme/demo-hub/pull/7",
        branch="dev/learning-accept-testing-x",
    )

    document = json.loads(learning.model_dump_json())

    assert document["note_path"] == "brain/_inbox/testing-x.md"
    assert document["state"] == "accepted_pr_open"
    assert (document["note_unavailable"], document["actions_unavailable"]) == (None, None)
    assert document["pr_url"] == "https://github.com/acme/demo-hub/pull/7"


def test_keeps_defaults_when_learning_has_no_clarity_fields() -> None:
    learning = a_learning()

    assert (learning.note_path, learning.state, learning.summary) == (None, None, None)


def test_serializes_detail_when_learning_detail_dumped() -> None:
    note = BrainNote(
        project="demo",
        path="_inbox/testing-x.md",
        frontmatter={"type": "learning", "tags": ["testing", "ci"]},
        markdown="Run the migrations check before the PR.\n",
        size=48,
    )
    detail = LearningDetail.model_validate(
        a_learning().model_dump()
        | {
            "note": note,
            "suggested_target": "learnings/",
            "target_choices": ("learnings/", "playbooks/"),
        }
    )

    document = json.loads(detail.model_dump_json())

    assert document["note"]["frontmatter"] == {"type": "learning", "tags": ["testing", "ci"]}
    assert document["suggested_target"] == "learnings/"
    assert document["target_choices"] == ["learnings/", "playbooks/"]


def test_serializes_action_result_when_pr_opened() -> None:
    result = LearningActionResult(
        state=LearningState.REJECTED_PR_OPEN,
        pr_url="https://github.com/acme/demo-hub/pull/8",
        branch="dev/learning-reject-testing-x",
    )

    assert result.model_dump(mode="json") == {
        "state": "rejected_pr_open",
        "pr_url": "https://github.com/acme/demo-hub/pull/8",
        "branch": "dev/learning-reject-testing-x",
    }


def test_marks_target_deprecated_when_schema_built() -> None:
    assert Learning.model_json_schema()["properties"]["target"]["deprecated"] is True
