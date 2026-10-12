import json

import pytest
from pydantic import ValidationError

from agent_hub.core.runner.run_record import Stage
from agent_hub.core.runs.workflow_run import RunFailure
from agent_hub.core.testing.read_model_builders import EVENT_ID, a_run


def test_serializes_run_with_stage_and_caps_when_dumped() -> None:
    document = json.loads(a_run().model_dump_json())

    assert document["stage"] == "IMPLEMENTING"
    assert document["caps"]["budget_usd"] == "10.0000"
    assert document["steps"][0]["key"] == "implement"
    assert document["issue"] == {"key": "DEM-7", "title": None, "url": None}


def test_serializes_failure_when_run_failed() -> None:
    failure = RunFailure(stage=Stage.VERIFYING, reason="check failed", failing_event_id=EVENT_ID)

    document = json.loads(a_run(stage=Stage.FAILED, failure=failure).model_dump_json())

    assert document["failure"]["stage"] == "VERIFYING"
    assert document["failure"]["failing_event_id"] == EVENT_ID


def test_rejects_step_when_key_unknown() -> None:
    step = {
        "key": "deploy",
        "attempt": 1,
        "max_attempts": 1,
        "status": "ok",
        "started_at": "2026-10-09T00:00:00Z",
        "ended_at": None,
    }

    with pytest.raises(ValidationError, match="key"):
        a_run(steps=(step,))
