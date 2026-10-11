import json

import pytest
from pydantic import ValidationError

from agent_hub.core.testing.read_model_builders import a_learning


def test_serializes_learning_when_dumped() -> None:
    document = json.loads(a_learning().model_dump_json())

    assert document["status"] == "proposed"
    assert document["target"] == {"kind": "team", "path": "brain/learnings/gotchas/testing.md"}
    assert document["proposed_at"] == "2026-10-09T14:00:00.123Z"


def test_rejects_learning_when_status_unknown() -> None:
    with pytest.raises(ValidationError, match="status"):
        a_learning(status="snoozed")
