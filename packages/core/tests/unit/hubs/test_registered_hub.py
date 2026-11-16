import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_hub.core.hubs.registered_hub import RegisteredHub, ValidationProblem
from agent_hub.core.testing.read_model_builders import HUB_ID, a_hub_view


def test_serializes_registry_entry_when_dumped() -> None:
    entry = RegisteredHub(
        id=HUB_ID, path="/home/demo/demo-hub", added_at=datetime(2026, 10, 9, tzinfo=UTC)
    )

    assert json.loads(entry.model_dump_json())["added_at"] == "2026-10-09T00:00:00.000Z"


def test_serializes_invalid_hub_with_pointers_when_dumped() -> None:
    problem = ValidationProblem(pointer="/repos/0/check_fast", message="required")
    view = a_hub_view(valid=False, validation_errors=(problem,), project=None)

    document = json.loads(view.model_dump_json())

    assert document["valid"] is False
    assert document["validation_errors"] == [
        {"pointer": "/repos/0/check_fast", "message": "required"}
    ]


def test_serializes_pin_warning_when_hub_pinned_elsewhere() -> None:
    view = a_hub_view(platform_pin="0.7.0", warnings=("pinned 0.7.0, running 0.8.0",))

    assert view.model_dump(mode="json")["warnings"] == ["pinned 0.7.0, running 0.8.0"]


def test_rejects_registry_entry_when_path_empty() -> None:
    with pytest.raises(ValidationError, match="path"):
        RegisteredHub(id=HUB_ID, path="", added_at=datetime(2026, 10, 9, tzinfo=UTC))
