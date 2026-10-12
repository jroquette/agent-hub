import json

import pytest
from pydantic import ValidationError

from agent_hub.core.approvals.approval import ApprovalKind
from agent_hub.core.testing.read_model_builders import an_approval

KINDS = ["guard_ask", "plan", "spec", "human_gate", "permission"]


def test_serializes_open_guard_ask_when_dumped() -> None:
    document = json.loads(an_approval().model_dump_json())

    assert (document["kind"], document["status"], document["decided"]) == (
        "guard_ask",
        "open",
        False,
    )
    assert document["how_to_decide"] == "cd /home/demo/demo-hub && claude --resume session-1"


def test_serializes_kinds_when_listed_in_spec() -> None:
    assert [kind.value for kind in ApprovalKind] == KINDS


def test_serializes_inferred_decline_when_decided() -> None:
    approval = an_approval(status="declined", decided=True, inferred=True)

    assert approval.model_dump(mode="json")["inferred"] is True


def test_rejects_approval_when_status_unknown() -> None:
    with pytest.raises(ValidationError, match="status"):
        an_approval(status="pending")
